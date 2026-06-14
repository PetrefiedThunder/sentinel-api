"""Coverage for app/routers/audit.py — emit, list, verify, CSV export."""
from sqlalchemy import select
from test_support import client_for, make_sqlite_session, run

from app.models import Approval, AuditEvent
from app.services.audit_log import append_audit_event


def _seed_approval(session, tenant):
    approval = Approval(tenant_id=tenant.id, function_name="wire", decision="approved")
    session.add(approval)
    run(session.commit())
    run(session.refresh(approval))
    return approval


def test_emit_audit_event_for_owned_action():
    engine, session, tenant = run(make_sqlite_session())
    approval = _seed_approval(session, tenant)
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/audit-events",
                json={"action_id": approval.id, "execution_result": "success"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["action_id"] == approval.id
        assert body["event_hash"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_emit_404_for_unknown_action():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/audit-events",
                json={"action_id": "act_missing", "execution_result": "success"},
            )
        assert resp.status_code == 404
    finally:
        run(session.close())
        run(engine.dispose())


def test_list_events_legacy_and_paginated():
    engine, session, tenant = run(make_sqlite_session())
    approval = _seed_approval(session, tenant)
    for _ in range(3):
        run(append_audit_event(session, tenant.id, approval.id, "success", None))
    try:
        with client_for(session, tenant) as client:
            legacy = client.get("/v1/audit-events")
            assert legacy.status_code == 200
            assert isinstance(legacy.json(), list)
            assert len(legacy.json()) == 3

            paged = client.get("/v1/audit-events?limit=2")
            assert paged.status_code == 200
            env = paged.json()
            assert env["has_more"] is True
            assert len(env["data"]) == 2

            filtered = client.get(f"/v1/audit-events?action_id={approval.id}")
            assert filtered.status_code == 200
            assert len(filtered.json()) == 3
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_chain_valid():
    engine, session, tenant = run(make_sqlite_session())
    approval = _seed_approval(session, tenant)
    run(append_audit_event(session, tenant.id, approval.id, "success", None))
    run(append_audit_event(session, tenant.id, approval.id, "success", None))
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/audit-events/verify")
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["events_checked"] == 2
        assert body["first_invalid_event_id"] is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_chain_detects_tampering():
    engine, session, tenant = run(make_sqlite_session())
    approval = _seed_approval(session, tenant)
    run(append_audit_event(session, tenant.id, approval.id, "success", None))
    # tamper: mutate a stored event's payload without recomputing hash
    rows = run(session.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant.id)))
    evt = rows.scalars().first()
    evt.execution_result = "TAMPERED"
    run(session.commit())
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/audit-events/verify")
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["first_invalid_event_id"] == evt.id
    finally:
        run(session.close())
        run(engine.dispose())


def test_export_csv_has_header_and_rows():
    engine, session, tenant = run(make_sqlite_session())
    approval = _seed_approval(session, tenant)
    run(append_audit_event(session, tenant.id, approval.id, "success", None))
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/audit-events.csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        text = resp.text
        assert "id,action_id,created_at_utc" in text.splitlines()[0]
        assert approval.id in text
    finally:
        run(session.close())
        run(engine.dispose())
