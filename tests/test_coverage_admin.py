"""Coverage for app/routers/admin.py — token gate, stats, purge-unverified.

Admin endpoints use _check_admin (header bearer token), NOT get_current_tenant,
so we must set settings.ADMIN_TOKEN and pass Authorization headers. get_db is
still overridden by client_for so the in-memory session is used.
"""
from datetime import datetime, timedelta

import pytest
from test_support import client_for, make_sqlite_session, run

from app.config import settings
from app.models import ApiKey, Approval, AuditEvent, Tenant


@pytest.fixture(autouse=True)
def _admin_token():
    saved = settings.ADMIN_TOKEN
    try:
        yield
    finally:
        settings.ADMIN_TOKEN = saved


def test_stats_503_when_admin_disabled():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = ""
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/admin/stats")
        assert resp.status_code == 503
    finally:
        run(session.close())
        run(engine.dispose())


def test_stats_401_without_bearer():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = "secret-admin"
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/admin/stats")
        assert resp.status_code == 401
    finally:
        run(session.close())
        run(engine.dispose())


def test_stats_403_with_wrong_token():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = "secret-admin"
    try:
        with client_for(session, tenant) as client:
            resp = client.get(
                "/v1/admin/stats", headers={"Authorization": "Bearer nope"}
            )
        assert resp.status_code == 403
    finally:
        run(session.close())
        run(engine.dispose())


def test_stats_returns_counts():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = "secret-admin"
    # verified tenant + one approval
    tenant.email_verified_at = datetime.utcnow()
    session.add(Approval(tenant_id=tenant.id, function_name="f"))
    run(session.commit())
    try:
        with client_for(session, tenant) as client:
            resp = client.get(
                "/v1/admin/stats", headers={"Authorization": "Bearer secret-admin"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenants_total"] == 1
        assert body["tenants_verified"] == 1
        assert body["tenants_unverified"] == 0
        assert body["approvals_total"] == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_purge_rejects_bad_window():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = "secret-admin"
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/admin/purge-unverified?older_than_days=0",
                headers={"Authorization": "Bearer secret-admin"},
            )
        assert resp.status_code == 400
    finally:
        run(session.close())
        run(engine.dispose())


def test_purge_dry_run_reports_targets():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = "secret-admin"
    # add an old unverified tenant
    old = Tenant(
        id="ten_old",
        name="Old",
        email="old@acme.io",
        created_at=datetime.utcnow() - timedelta(days=60),
    )
    session.add(old)
    run(session.commit())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/admin/purge-unverified?older_than_days=30",
                headers={"Authorization": "Bearer secret-admin"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        assert body["would_delete"] == 1
        assert body["sample"][0]["email"] == "old@acme.io"
    finally:
        run(session.close())
        run(engine.dispose())


def test_purge_actually_deletes_with_cascade():
    engine, session, tenant = run(make_sqlite_session())
    settings.ADMIN_TOKEN = "secret-admin"
    old = Tenant(
        id="ten_old",
        name="Old",
        email="old@acme.io",
        created_at=datetime.utcnow() - timedelta(days=60),
    )
    session.add(old)
    run(session.flush())
    session.add(ApiKey(tenant_id=old.id, key_hash="h", prefix="sk", name="default"))
    appr = Approval(tenant_id=old.id, function_name="f")
    session.add(appr)
    run(session.flush())
    session.add(
        AuditEvent(tenant_id=old.id, action_id=appr.id, event_hash="abc")
    )
    run(session.commit())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/admin/purge-unverified?older_than_days=30&dry_run=false",
                headers={"Authorization": "Bearer secret-admin"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is False
        assert body["deleted_tenants"] == 1
        assert body["deleted_api_keys"] == 1
        assert body["deleted_approvals"] == 1
        assert body["deleted_audit_events"] == 1
        # the active test tenant must survive
        assert run(session.get(Tenant, tenant.id)) is not None
        assert run(session.get(Tenant, "ten_old")) is None
    finally:
        run(session.close())
        run(engine.dispose())
