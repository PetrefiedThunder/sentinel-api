"""BE-008: neutralize spreadsheet formulas only in exported error text."""

import csv
import io
import json

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from test_support import make_sqlite_session

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Approval, AuditEvent
from app.routers import audit


@pytest_asyncio.fixture
async def audit_api(monkeypatch):
    engine, session, tenant = await make_sqlite_session()
    approval = Approval(tenant_id=tenant.id, function_name="qa", decision="approved")
    session.add(approval)
    await session.commit()

    async def database():
        yield session

    async def no_timestamp(*args):
        return None

    monkeypatch.setattr(audit, "timestamp_audit_event", no_timestamp)
    application = FastAPI()
    application.include_router(audit.router, prefix="/v1/audit-events")
    application.dependency_overrides[get_db] = database
    application.dependency_overrides[get_current_tenant] = lambda: tenant
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://qa.invalid"
        ) as client:
            yield client, session, approval
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.parametrize(
    ("error", "escaped"),
    [
        ("=1+1", True),
        ("+1+1", True),
        ("-1+1", True),
        ("@SUM(1,1)", True),
        ("\tordinary text", True),
        ("\rordinary text", True),
        ("\nordinary text", True),
        (" =1+1", True),
        (" \t=1+1", True),
        ("\r\n=1+1", True),
        ("\n +1+1", True),
        ("\u00a0=1+1", True),
        ("ordinary text", False),
        ("  ordinary text", False),
        ("'=1+1", False),
        ('ordinary, "quoted" error', False),
        ("ordinary\n=1+1", False),
        ('ordinary",=1+1\nsecond line', False),
        ("", False),
        (None, False),
    ],
)
async def test_be008_csv_error_is_safe_without_mutating_audit_evidence(audit_api, error, escaped):
    client, session, approval = audit_api
    created = await client.post(
        "/v1/audit-events",
        json={"action_id": approval.id, "execution_result": "=1+1", "error": error},
    )
    assert created.status_code == 200
    body = created.json()
    before_hash = body["event_hash"]
    assert body["error"] == error

    exported = await client.get("/v1/audit-events.csv")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exported.text, newline="")))
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == [
        "id",
        "action_id",
        "created_at_utc",
        "execution_result_json",
        "error",
        "prev_hash",
        "event_hash",
    ]
    assert row["error"] == ("'" + error if escaped else error or "")
    assert json.loads(row["execution_result_json"]) == "=1+1"
    assert row["event_hash"] == before_hash

    listed = await client.get("/v1/audit-events")
    assert listed.status_code == 200
    assert listed.json()[0]["error"] == error
    assert listed.json()[0]["event_hash"] == before_hash
    stored = await session.get(AuditEvent, body["id"])
    await session.refresh(stored)
    assert stored.error == error
    assert stored.event_hash == before_hash
    verified = await client.get("/v1/audit-events/verify")
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    assert verified.json()["events_checked"] == 1
