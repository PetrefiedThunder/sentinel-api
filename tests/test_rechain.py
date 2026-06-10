"""Regression: the one-time admin rechain heals chain forks left by the
pre-fix append race (see app/services/audit_log.py advisory-lock comment)."""
from sqlalchemy import update
from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.config import settings
from app.models import AuditEvent
from app.services.audit_log import append_audit_event


async def _build_chain(session, n):
    events = []
    for i in range(n):
        events.append(
            await append_audit_event(session, TENANT_ID, None, f"decision:approved:{i}")
        )
    return events


def test_rechain_heals_forked_chain(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "adm_testtoken")
    engine, session, tenant = run(make_sqlite_session())
    try:
        events = run(_build_chain(session, 4))
        # Simulate the race: event 2 forks off event 0's hash instead of 1's
        run(
            session.execute(
                update(AuditEvent)
                .where(AuditEvent.id == events[2].id)
                .values(prev_hash=events[0].event_hash)
            )
        )
        run(session.commit())

        with client_for(session, tenant) as client:
            admin = {"Authorization": "Bearer adm_testtoken"}

            broken = client.get("/v1/audit-events/verify").json()
            assert broken["valid"] is False

            dry = client.post("/v1/admin/rechain-audit?dry_run=true", headers=admin).json()
            assert dry["dry_run"] is True
            assert dry["events_rewritten"] >= 1
            # dry run must not have fixed anything
            assert client.get("/v1/audit-events/verify").json()["valid"] is False

            fixed = client.post(
                "/v1/admin/rechain-audit?dry_run=false", headers=admin
            ).json()
            assert fixed["dry_run"] is False
            assert fixed["events_rewritten"] == dry["events_rewritten"]

            healed = client.get("/v1/audit-events/verify").json()
            assert healed["valid"] is True
            assert healed["events_checked"] == 4
    finally:
        run(session.close())
        run(engine.dispose())
