from datetime import datetime, timedelta

from sqlalchemy import select
from test_support import client_for, make_sqlite_session, run

from app.config import settings
from app.models import UptimeProbe

ADMIN_TOKEN = "test-admin-token"

PROBE_BODY = {
    "region": "us-east",
    "target": "https://api.pauseapi.app/health",
    "ok": True,
    "status_code": 200,
    "latency_ms": 42,
}


def test_probe_returns_503_when_admin_token_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "")
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            response = client.post("/v1/status/probe", json=PROBE_BODY)
        assert response.status_code == 503
    finally:
        run(session.close())
        run(engine.dispose())


def test_probe_rejected_without_or_with_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", ADMIN_TOKEN)
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            missing = client.post("/v1/status/probe", json=PROBE_BODY)
            wrong = client.post(
                "/v1/status/probe",
                json=PROBE_BODY,
                headers={"Authorization": "Bearer not-the-token"},
            )
        assert missing.status_code == 401
        assert wrong.status_code == 403

        rows = run(session.execute(select(UptimeProbe)))
        assert rows.scalars().all() == []
    finally:
        run(session.close())
        run(engine.dispose())


def test_probe_accepted_with_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", ADMIN_TOKEN)
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            response = client.post(
                "/v1/status/probe",
                json=PROBE_BODY,
                headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
            )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

        rows = run(session.execute(select(UptimeProbe)))
        probes = rows.scalars().all()
        assert len(probes) == 1
        assert probes[0].region == "us-east"
        assert probes[0].ok is True
        assert probes[0].status_code == 200
        assert probes[0].latency_ms == 42
        assert probes[0].id.startswith("upt_")
    finally:
        run(session.close())
        run(engine.dispose())


def test_history_aggregates_daily_and_is_public():
    engine, session, tenant = run(make_sqlite_session())
    try:
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        long_ago = now - timedelta(days=40)

        async def seed():
            session.add_all(
                [
                    # today: 3 probes, 2 ok
                    UptimeProbe(region="us-east", target="t", ok=True, created_at=now),
                    UptimeProbe(region="us-east", target="t", ok=True, created_at=now),
                    UptimeProbe(region="eu-west", target="t", ok=False, created_at=now),
                    # yesterday: 1 probe, 1 ok
                    UptimeProbe(region="us-east", target="t", ok=True, created_at=yesterday),
                    # outside the 30-day window: excluded
                    UptimeProbe(region="us-east", target="t", ok=False, created_at=long_ago),
                ]
            )
            await session.commit()

        run(seed())

        with client_for(session, tenant) as client:
            # no Authorization header — endpoint is public
            response = client.get("/v1/status/history")
        assert response.status_code == 200
        data = response.json()

        assert [d["date"] for d in data] == [
            yesterday.strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
        ]
        assert data[0] == {
            "date": yesterday.strftime("%Y-%m-%d"),
            "probes": 1,
            "ok": 1,
            "uptime_pct": 100.0,
        }
        assert data[1]["probes"] == 3
        assert data[1]["ok"] == 2
        assert data[1]["uptime_pct"] == round(2 / 3 * 100, 3)
    finally:
        run(session.close())
        run(engine.dispose())


def test_history_days_param_bounds():
    engine, session, tenant = run(make_sqlite_session())
    try:
        long_ago = datetime.utcnow() - timedelta(days=40)

        async def seed():
            session.add(UptimeProbe(region="us-east", target="t", ok=True, created_at=long_ago))
            await session.commit()

        run(seed())

        with client_for(session, tenant) as client:
            assert client.get("/v1/status/history", params={"days": 0}).status_code == 422
            assert client.get("/v1/status/history", params={"days": 93}).status_code == 422

            within_max = client.get("/v1/status/history", params={"days": 92})
            assert within_max.status_code == 200
            assert [d["probes"] for d in within_max.json()] == [1]

            default_window = client.get("/v1/status/history")
            assert default_window.status_code == 200
            assert default_window.json() == []  # 40-day-old probe is outside default 30
    finally:
        run(session.close())
        run(engine.dispose())
