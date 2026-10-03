"""BE-003: webhook SSRF guards, exercised without DNS or network sockets."""

import asyncio
import ipaddress
import socket
import ssl
from types import SimpleNamespace

import httpcore
import httpx
import pytest
from fastapi import FastAPI

import app.db
from app.auth import get_current_tenant
from app.db import get_db
from app.models import Approval, WebhookEndpoint
from app.routers import webhooks as router
from app.services import webhooks


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",
        "https://",
        "https://user:synthetic@example.com/hook",
        "https://127.0.0.1/hook",
        "https://10.0.0.1/hook",
        "https://169.254.169.254/hook",
        "https://192.0.0.8/hook",
        "https://224.0.0.1/hook",
        "https://[::1]/hook",
        "https://[fc00::1]/hook",
        "https://[fe80::1%25lo0]/hook",
        "https://[::ffff:127.0.0.1]/hook",
        "https://[64:ff9b::7f00:1]/hook",
        "https://[2002:7f00:1::]/hook",
        "https://localhost/hook",
        "https://localhost./hook",
    ],
)
async def test_be003_registration_rejects_unsafe_destinations(url):
    added = []

    async def commit():
        pass

    async def refresh(endpoint):
        pass

    db = SimpleNamespace(add=added.append, commit=commit, refresh=refresh)
    application = FastAPI()
    application.include_router(router.router, prefix="/v1/webhooks")
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_tenant] = lambda: SimpleNamespace(id="ten_qa")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://qa.invalid"
    ) as client:
        response = await client.post("/v1/webhooks", json={"url": url})
    assert response.status_code == 400
    assert added == []


@pytest.fixture
def deliver(monkeypatch):
    """Use real HTTPX/HTTPCore routing and TLS setup with an inert network backend."""
    real_client = httpx.AsyncClient

    async def invoke(url, *, addresses=None, response_status=200, dns_error=None):
        result = SimpleNamespace(
            connections=[], tls=[], writes=[], records=[], dns_queries=[], client_options=[]
        )
        endpoint = WebhookEndpoint(
            id="whk_qa", tenant_id="ten_qa", url=url, secret="synthetic-signing-value"
        )

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def add(self, delivery):
                result.records.append(delivery)

            async def get(self, *args):
                return endpoint

            async def commit(self):
                pass

        monkeypatch.setattr(app.db, "SessionLocal", Session)

        async def getaddrinfo(host, port, **kwargs):
            result.dns_queries.append((host, port))
            if dns_error is not None:
                raise dns_error
            # A second DNS lookup would rebind to loopback.
            selected = (
                (["93.184.216.34"] if addresses is None else addresses)
                if len(result.dns_queries) == 1
                else ["127.0.0.1"]
            )
            return [
                (
                    socket.AF_INET6
                    if ipaddress.ip_address(address).version == 6
                    else socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (address, port),
                )
                for address in selected
            ]

        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", getaddrinfo)

        class Stream(httpcore.AsyncMockStream):
            async def write(self, buffer, timeout=None):
                result.writes.append(buffer)

            async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
                result.tls.append(
                    (server_hostname, ssl_context.check_hostname, ssl_context.verify_mode)
                )
                return self

        class Backend(httpcore.AsyncMockBackend):
            async def connect_tcp(self, host, port, **kwargs):
                result.connections.append((host, port))
                redirect = (
                    b"Location: https://127.0.0.1/internal\r\n" if response_status == 302 else b""
                )
                return Stream(
                    [
                        f"HTTP/1.1 {response_status} Test\r\n".encode()
                        + redirect
                        + b"Content-Length: 2\r\n\r\nOK"
                    ]
                )

        def client(**kwargs):
            result.client_options.append(kwargs.copy())
            transport = httpx.AsyncHTTPTransport()
            transport._pool = httpcore.AsyncConnectionPool(network_backend=Backend([]))
            return real_client(transport=transport, **kwargs)

        monkeypatch.setattr(webhooks.httpx, "AsyncClient", client)
        monkeypatch.setattr(webhooks, "BACKOFF_SECONDS", [0, 0, 0])
        approval = Approval(
            id="act_qa",
            tenant_id="ten_qa",
            function_name="qa",
            decision="approved",
            arguments={},
        )
        await webhooks._deliver_with_retries(endpoint, "approval.approved", approval)
        return result

    return invoke


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:4700:4700::1111"])
async def test_be003_delivery_pins_dns_ip_preserving_host_and_tls(deliver, address):
    result = await deliver("https://receiver.example:8443/a%20b?event=yes", addresses=[address])
    assert result.dns_queries == [("receiver.example", 8443)]
    assert result.connections == [(address, 8443)]
    assert result.tls == [("receiver.example", True, ssl.CERT_REQUIRED)]
    wire = b"".join(result.writes)
    assert b"POST /a%20b?event=yes HTTP/1.1" in wire
    assert b"Host: receiver.example:8443" in wire
    assert result.client_options[0]["trust_env"] is False
    assert result.client_options[0]["follow_redirects"] is False
    assert result.records[0].status_code == 200
    assert result.records[0].delivered_at is not None


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["224.0.0.1"],
        ["::1"],
        ["fc00::1"],
        ["::ffff:127.0.0.1"],
        ["64:ff9b::7f00:1"],
        ["2002:7f00:1::"],
        ["93.184.216.34", "127.0.0.1"],
        ["2606:4700:4700::1111", "::1"],
    ],
)
async def test_be003_delivery_rejects_every_unsafe_dns_answer(deliver, addresses):
    result = await deliver("https://receiver.example/hook", addresses=addresses)
    assert result.connections == []
    assert result.writes == []
    assert len(result.records) == 1
    assert result.records[0].status_code is None
    assert result.records[0].delivered_at is None
    assert result.records[0].response_snippet == "Webhook destination is not allowed"
    assert result.records[0].attempt == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/internal",
        "https://10.0.0.1/internal",
        "https://[::1]/internal",
        "https://user:synthetic@example.com/hook",
    ],
)
async def test_be003_legacy_unsafe_endpoint_is_blocked_before_dns(deliver, url):
    result = await deliver(url)
    assert result.dns_queries == []
    assert result.connections == []
    assert result.records[0].response_snippet == "Webhook destination is not allowed"


async def test_be003_redirect_to_private_destination_is_not_followed(deliver):
    result = await deliver("https://receiver.example/hook", response_status=302)
    assert result.connections == [("93.184.216.34", 443)]
    assert all(b"/internal" not in write for write in result.writes)
    # The next retry sees a DNS rebind and must stop before another request.
    assert len(result.dns_queries) == 2
    assert result.records[0].delivered_at is None


@pytest.mark.parametrize("error", [socket.gaierror("synthetic DNS failure"), TimeoutError()])
async def test_be003_dns_failure_is_recorded_without_a_connection(deliver, error):
    result = await deliver("https://receiver.example/hook", dns_error=error)
    assert result.connections == []
    assert len(result.records) == 1
    assert result.records[0].delivered_at is None
    assert result.records[0].attempt == webhooks.MAX_ATTEMPTS


@pytest.mark.parametrize(
    ("url", "address", "host"),
    [
        ("https://93.184.216.34/hook", "93.184.216.34", "93.184.216.34"),
        ("https://[2606:4700:4700::1111]/hook", "2606:4700:4700::1111", "[2606:4700:4700::1111]"),
    ],
)
async def test_be003_public_literal_keeps_https_without_dns(deliver, url, address, host):
    result = await deliver(url)
    assert result.dns_queries == []
    assert result.connections == [(address, 443)]
    assert result.tls == [(address, True, ssl.CERT_REQUIRED)]
    assert f"Host: {host}".encode() in b"".join(result.writes)
    assert result.records[0].delivered_at is not None


async def test_be003_empty_dns_result_never_connects(deliver):
    result = await deliver("https://receiver.example/hook", addresses=[])
    assert result.connections == []
    assert result.records[0].delivered_at is None
