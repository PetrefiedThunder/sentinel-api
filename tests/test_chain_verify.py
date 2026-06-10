from sqlalchemy import update

from app.models import AuditEvent
from app.services.audit_log import append_audit_event
from test_support import TENANT_ID, client_for, make_sqlite_session, run


async def _build_chain(session, n):
    events = []
    for i in range(n):
        event = await append_audit_event(
            session, TENANT_ID, None, f"decision:approved:{i}"
        )
        events.append(event)
    return events


def test_verify_empty_tenant_is_valid():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            response = client.get("/v1/audit-events/verify")

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert body["events_checked"] == 0
        assert body["first_invalid_event_id"] is None
        assert body["checked_at"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_intact_chain_is_valid():
    engine, session, tenant = run(make_sqlite_session())
    try:
        events = run(_build_chain(session, 3))
        assert events[0].prev_hash is None
        assert events[1].prev_hash == events[0].event_hash
        assert events[2].prev_hash == events[1].event_hash

        with client_for(session, tenant) as client:
            response = client.get("/v1/audit-events/verify")

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert body["events_checked"] == 3
        assert body["first_invalid_event_id"] is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_detects_tampered_payload():
    engine, session, tenant = run(make_sqlite_session())
    try:
        events = run(_build_chain(session, 3))
        tampered = events[1]

        async def corrupt():
            await session.execute(
                update(AuditEvent)
                .where(AuditEvent.id == tampered.id)
                .values(execution_result="decision:rejected")
            )
            await session.commit()

        run(corrupt())

        with client_for(session, tenant) as client:
            response = client.get("/v1/audit-events/verify")

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["events_checked"] == 3
        assert body["first_invalid_event_id"] == tampered.id
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_detects_tampered_hash():
    engine, session, tenant = run(make_sqlite_session())
    try:
        events = run(_build_chain(session, 2))
        tampered = events[0]

        async def corrupt():
            await session.execute(
                update(AuditEvent)
                .where(AuditEvent.id == tampered.id)
                .values(event_hash="deadbeef" * 8)
            )
            await session.commit()

        run(corrupt())

        with client_for(session, tenant) as client:
            response = client.get("/v1/audit-events/verify")

        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["events_checked"] == 2
        assert body["first_invalid_event_id"] == tampered.id
    finally:
        run(session.close())
        run(engine.dispose())
