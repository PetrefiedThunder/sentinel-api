"""Validate customer webhook destinations and pin DNS before connecting."""

import asyncio
import ipaddress
import socket

import httpx


class UnsafeWebhookDestination(ValueError):
    pass


def _public_address(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise UnsafeWebhookDestination("Invalid webhook address") from exc
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise UnsafeWebhookDestination("Webhook destination is not allowed")
    if isinstance(address, ipaddress.IPv4Address):
        # Keep protocol-assignment ranges blocked on all supported Python versions.
        if address in ipaddress.ip_network("192.0.0.0/24"):
            raise UnsafeWebhookDestination("Webhook destination is not allowed")
    elif (
        address not in ipaddress.ip_network("2000::/3")
        or address.sixtofour is not None
        or address.teredo is not None
        or address.scope_id is not None
    ):
        # Exclude mapped/translated IPv4, tunnels, and scoped addresses.
        raise UnsafeWebhookDestination("Webhook destination is not allowed")
    return address.compressed


def validate_webhook_url(value: str) -> httpx.URL:
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL as exc:
        raise UnsafeWebhookDestination("Invalid webhook URL") from exc
    if url.scheme != "https" or not url.host or url.userinfo or url.port == 0:
        raise UnsafeWebhookDestination("url must start with https:// and have no credentials")
    host = url.host.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or "%" in host:
        raise UnsafeWebhookDestination("Webhook destination is not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # Hostnames are resolved and checked immediately before delivery.
    else:
        _public_address(host)
    return url


async def pin_webhook_url(value: str, *, timeout: float) -> tuple[httpx.URL, httpx.URL]:
    url = validate_webhook_url(value)
    host = url.raw_host.decode("ascii")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    host, url.port or 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise httpx.ConnectTimeout("Webhook DNS resolution timed out") from exc
        except socket.gaierror as exc:
            raise httpx.ConnectError("Webhook DNS resolution failed") from exc
        if not answers:
            raise httpx.ConnectError("Webhook DNS returned no addresses") from None
        # Reject mixed safe/unsafe answers, then connect to an already checked IP.
        addresses = [_public_address(str(answer[4][0])) for answer in answers]
        pinned_host = addresses[0]
    else:
        pinned_host = _public_address(str(address))
    return url, url.copy_with(host=pinned_host)
