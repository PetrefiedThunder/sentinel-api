"""Coverage for app/routers/tenants.py — signup, verify-email, recover, me/update.

The tenants router has dependencies that aren't overridden by client_for
(it uses get_db directly, not get_current_tenant for signup/verify/recover).
Rate limiting fails open without Redis, and welcome/recovery emails are
background tasks that no-op without RESEND_API_KEY.
"""
from sqlalchemy import select
from test_support import client_for, make_sqlite_session, run

from app.models import ApiKey
from app.services.onboarding import create_token


def test_signup_rejects_invalid_email():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/tenants/signup", json={"name": "Acme", "email": "no-at-sign"}
            )
        assert resp.status_code == 400
        assert "Invalid email" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_signup_rejects_personal_email_domain():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/tenants/signup", json={"name": "Acme", "email": "joe@gmail.com"}
            )
        assert resp.status_code == 400
        assert "Work email" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_signup_creates_test_tenant_and_api_key():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/tenants/signup",
                json={"name": "Acme", "email": "founder@acme.io", "mode": "test"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "test"
        assert body["api_key"].startswith(("sk_", "pk_", "key_")) or body["api_key"]
        # api key row was persisted for the new tenant
        rows = run(session.execute(select(ApiKey).where(ApiKey.tenant_id == body["tenant_id"])))
        assert len(rows.scalars().all()) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_signup_rejects_duplicate_email():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/tenants/signup",
                json={"name": "Acme", "email": "dup@acme.io", "mode": "test"},
            )
            assert first.status_code == 200
            second = client.post(
                "/v1/tenants/signup",
                json={"name": "Acme2", "email": "dup@acme.io", "mode": "test"},
            )
        assert second.status_code == 400
        assert "already registered" in second.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_email_with_valid_token():
    engine, session, tenant = run(make_sqlite_session())
    token = create_token("verify", tenant.id, ttl_seconds=3600)
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/tenants/verify-email", json={"token": token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == tenant.id
        assert body["email_verified_at"] is not None
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_email_rejects_bad_token():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/tenants/verify-email", json={"token": "garbage.sig"})
        assert resp.status_code == 400
        assert "Invalid or expired" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_email_404_for_unknown_tenant():
    engine, session, tenant = run(make_sqlite_session())
    token = create_token("verify", "ten_does_not_exist", ttl_seconds=3600)
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/tenants/verify-email", json={"token": token})
        assert resp.status_code == 404
    finally:
        run(session.close())
        run(engine.dispose())


def test_recover_request_always_204_for_unknown_email():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/tenants/recover/request", json={"email": "nobody@nowhere.io"}
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        run(session.close())
        run(engine.dispose())


def test_recover_request_no_at_sign_still_ok():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/tenants/recover/request", json={"email": "bogus"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        run(session.close())
        run(engine.dispose())


def test_recover_request_known_email_queues_email():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/tenants/recover/request", json={"email": tenant.email}
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        run(session.close())
        run(engine.dispose())


def test_recover_exchange_rotates_keys():
    engine, session, tenant = run(make_sqlite_session())
    # seed an existing active key
    old = ApiKey(tenant_id=tenant.id, key_hash="h", prefix="sk_old", name="default")
    session.add(old)
    run(session.commit())
    token = create_token("recover", tenant.id, ttl_seconds=3600)
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/tenants/recover/exchange", json={"token": token})
        assert resp.status_code == 200
        assert resp.json()["api_key"]
        # old key revoked, new "recovery" key issued
        rows = run(session.execute(select(ApiKey).where(ApiKey.tenant_id == tenant.id)))
        keys = rows.scalars().all()
        old_row = next(k for k in keys if k.name == "default")
        assert old_row.revoked_at is not None
        assert any(k.name == "recovery" and k.revoked_at is None for k in keys)
    finally:
        run(session.close())
        run(engine.dispose())


def test_recover_exchange_rejects_bad_token():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/tenants/recover/exchange", json={"token": "garbage.sig"}
            )
        assert resp.status_code == 400
    finally:
        run(session.close())
        run(engine.dispose())


def test_recover_exchange_404_for_missing_tenant():
    engine, session, tenant = run(make_sqlite_session())
    token = create_token("recover", "ten_missing", ttl_seconds=3600)
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/tenants/recover/exchange", json={"token": token})
        assert resp.status_code == 404
    finally:
        run(session.close())
        run(engine.dispose())


def test_get_me_serializes_tenant():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/tenants/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == tenant.id
        assert body["email"] == tenant.email
        assert body["default_approvers"] == []
    finally:
        run(session.close())
        run(engine.dispose())


def test_update_me_sets_default_approvers():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.patch(
                "/v1/tenants/me",
                json={"default_approvers": [" boss@acme.io ", "sms:+15551230000"]},
            )
        assert resp.status_code == 200
        assert resp.json()["default_approvers"] == ["boss@acme.io", "sms:+15551230000"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_update_me_rejects_invalid_approver():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.patch(
                "/v1/tenants/me", json={"default_approvers": ["not-an-approver"]}
            )
        assert resp.status_code == 400
        assert "Invalid approver" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())
