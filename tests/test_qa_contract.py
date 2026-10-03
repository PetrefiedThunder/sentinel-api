"""QA consumer-contract checks; known defects reference the 2026-10-02 findings.

The HTTP harness uses SQLite in memory and ASGI transport without lifespan.
No provider calls, database sockets, or application background bus are needed.
"""

import csv
import io
import json
import socket
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import get_current_tenant
from app.db import Base, get_db
from app.main import app
from app.models import Tenant

PAYLOAD = {
    "function_name": "qa_contract_action",
    "arguments": {"sample": "synthetic"},
    "approvers": ["reviewer@example.com"],
}


@pytest.fixture
async def contract_client(monkeypatch):
    """Each test owns its database; all non-ASGI network attempts fail closed."""

    def deny_network(*args, **kwargs):
        raise AssertionError("QA contract tests must not open network sockets")

    async def no_notifications(*args, **kwargs):
        return None

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    monkeypatch.setattr(
        "app.services.approval_service.dispatch_approval_notifications", no_notifications
    )
    monkeypatch.setattr("app.routers.audit.timestamp_audit_event", no_notifications)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    old_overrides = app.dependency_overrides.copy()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            tenant = Tenant(
                id="ten_qa_contract", name="QA Contract", email="qa@example.com", mode="test"
            )
            session.add(tenant)
            await session.commit()

            async def local_database():
                yield session

            async def local_tenant():
                return tenant

            app.dependency_overrides[get_db] = local_database
            app.dependency_overrides[get_current_tenant] = local_tenant
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://qa.invalid"
            ) as client:
                yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)
        await engine.dispose()


def test_committed_openapi_operations_remain_registered():
    """Protect the checked-in downstream integration surface from removal."""
    baseline = json.loads(
        (Path(__file__).parents[1] / "docs" / "openapi.baseline.json").read_text()
    )
    current = app.openapi()
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}
    for path, operations in baseline["paths"].items():
        assert path in current["paths"], path
        for method in methods.intersection(operations):
            assert method in current["paths"][path], (method, path)


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="FE-001: approval success schemas are unconstrained"
)
@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/v1/approvals", "post"),
        ("/v1/approvals", "get"),
        ("/v1/approvals/{action_id}", "get"),
        ("/v1/approvals/{action_id}/wait", "get"),
    ],
)
def test_openapi_types_primary_approval_responses(path, method):
    schema = app.openapi()
    response = schema["paths"][path][method]["responses"]["200"]
    assert response["content"]["application/json"]["schema"], (method, path)


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="FE-002: validator bounds/enums are absent from OpenAPI"
)
@pytest.mark.parametrize(
    ("component", "field", "expected"),
    [
        ("ApprovalCreate", "timeout_seconds", {"minimum": 1, "maximum": 86400}),
        ("ApprovalCreate", "risk_level", {"enum": {"low", "medium", "high", "critical"}}),
        ("TenantSignup", "mode", {"enum": {"live", "test"}}),
    ],
)
def test_openapi_declares_runtime_request_constraints(component, field, expected):
    schemas = app.openapi()["components"]["schemas"]
    actual = {
        key: set(schemas[component]["properties"][field].get(key, []))
        if key == "enum"
        else schemas[component]["properties"][field].get(key)
        for key in expected
    }
    assert actual == expected


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="FE-003: CSV download is documented as application/json"
)
async def test_openapi_csv_media_type_matches_runtime(contract_client):
    response = await contract_client.get("/v1/audit-events.csv")
    if response.status_code != 200:
        pytest.fail(f"CSV setup failed: HTTP {response.status_code}")
    media_type = response.headers["content-type"].split(";", 1)[0]
    documented = app.openapi()["paths"]["/v1/audit-events.csv"]["get"]["responses"]["200"]
    assert media_type in documented["content"]


async def test_create_fetch_and_empty_page_response_shapes(contract_client):
    empty = await contract_client.get("/v1/approvals", params={"limit": 1})
    assert empty.status_code == 200
    assert empty.json() == {"data": [], "has_more": False, "next_cursor": None}

    created = await contract_client.post("/v1/approvals", json=PAYLOAD)
    assert created.status_code == 200
    body = created.json()
    assert body["action_id"] == body["id"]
    assert body["status"] == body["decision"] == "pending"
    assert body["function_name"] == PAYLOAD["function_name"]
    fetched = await contract_client.get(f"/v1/approvals/{body['action_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


@pytest.mark.parametrize("timeout", [None, {}, [], 1.5])
async def test_invalid_timeout_scalar_equivalence_classes(contract_client, timeout):
    response = await contract_client.post(
        "/v1/approvals", json={**PAYLOAD, "timeout_seconds": timeout}
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"][0]["loc"] == ["body", "timeout_seconds"]


@pytest.mark.parametrize("risk", ["", "HIGH", "unknown", "critical "])
async def test_invalid_risk_equivalence_classes(contract_client, risk):
    response = await contract_client.post("/v1/approvals", json={**PAYLOAD, "risk_level": risk})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "risk_level"]


@pytest.mark.parametrize("cursor", ["%%%", "e30", "bnVsbA", "W10", "eyJjIjoiYmFkIiwiaSI6IngifQ"])
@pytest.mark.parametrize("path", ["/v1/approvals", "/v1/audit-events"])
async def test_malformed_cursor_equivalence_classes(contract_client, path, cursor):
    response = await contract_client.get(path, params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination cursor"}


async def test_malformed_json_is_a_machine_readable_validation_error(contract_client):
    response = await contract_client.post(
        "/v1/approvals", content="{", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


async def test_csv_quotes_unicode_commas_and_newlines(contract_client):
    created = await contract_client.post("/v1/approvals", json=PAYLOAD)
    assert created.status_code == 200
    payload = {
        "action_id": created.json()["action_id"],
        "execution_result": 'Completed, "reviewed"\nCaf\u00e9',
        "error": 'Synthetic, "error"\nSecond line',
    }
    emitted = await contract_client.post("/v1/audit-events", json=payload)
    assert emitted.status_code == 200
    exported = await contract_client.get("/v1/audit-events.csv")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 1
    assert json.loads(rows[0]["execution_result_json"]) == payload["execution_result"]
    assert rows[0]["error"] == payload["error"]
