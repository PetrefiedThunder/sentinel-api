"""Coverage for app/routers/billing.py — Stripe checkout, webhook, /me.

Stripe HTTP is never hit: we either run with billing disabled (503 paths) or
monkeypatch the _stripe_post / signature helpers so no network call happens.
"""
import hashlib
import hmac
import json
import time

import pytest
from test_support import client_for, make_sqlite_session, run

import app.routers.billing as billing
from app.config import settings


@pytest.fixture(autouse=True)
def _reset_stripe_settings():
    """Snapshot/restore the Stripe-related settings each test mutates."""
    keys = (
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_PRO",
    )
    saved = {k: getattr(settings, k) for k in keys}
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(settings, k, v)


def test_billing_me_works_when_stripe_disabled():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = ""
    try:
        with client_for(session, tenant) as client:
            resp = client.get("/v1/billing/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "free"
        assert body["billing_enabled"] is False
        assert body["stripe_customer_id"] is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_checkout_returns_503_when_disabled():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = ""
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/checkout", json={"plan": "pro"})
        assert resp.status_code == 503
        assert "disabled" in resp.json()["detail"].lower()
    finally:
        run(session.close())
        run(engine.dispose())


def test_checkout_rejects_non_pro_plan():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/checkout", json={"plan": "enterprise"})
        assert resp.status_code == 400
        assert "pro" in resp.json()["detail"].lower()
    finally:
        run(session.close())
        run(engine.dispose())


def test_checkout_requires_price_configured():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_PRICE_PRO = ""
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/checkout", json={"plan": "pro"})
        assert resp.status_code == 503
        assert "STRIPE_PRICE_PRO" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_checkout_happy_path_uses_customer_email(monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_PRICE_PRO = "price_123"

    captured = {}

    async def fake_post(path, form):
        captured["path"] = path
        captured["form"] = form
        return {"url": "https://checkout.stripe.com/c/sess_1", "id": "cs_1"}

    monkeypatch.setattr(billing, "_stripe_post", fake_post)
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/checkout", json={"plan": "pro"})
        assert resp.status_code == 200
        assert resp.json()["url"].endswith("sess_1")
        assert captured["path"] == "/checkout/sessions"
        # tenant had no stripe_customer_id → checkout uses customer_email
        assert captured["form"]["customer_email"] == tenant.email
        assert captured["form"]["client_reference_id"] == tenant.id
    finally:
        run(session.close())
        run(engine.dispose())


def test_checkout_reuses_existing_customer(monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_PRICE_PRO = "price_123"
    tenant.stripe_customer_id = "cus_existing"
    run(session.commit())

    captured = {}

    async def fake_post(path, form):
        captured["form"] = form
        return {"url": "https://checkout.stripe.com/c/sess_2", "id": "cs_2"}

    monkeypatch.setattr(billing, "_stripe_post", fake_post)
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/checkout", json={"plan": "pro"})
        assert resp.status_code == 200
        assert captured["form"]["customer"] == "cus_existing"
        assert "customer_email" not in captured["form"]
    finally:
        run(session.close())
        run(engine.dispose())


# ── Webhook ───────────────────────────────────────────────────────────
def _signed_headers(secret: str, raw: bytes) -> dict:
    ts = str(int(time.time()))
    signed_payload = f"{ts}.".encode() + raw
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={sig}"}


def test_webhook_503_when_webhook_secret_missing():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = ""
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/webhook", content=b"{}")
        assert resp.status_code == 503
    finally:
        run(session.close())
        run(engine.dispose())


def test_webhook_missing_signature_header():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/billing/webhook", content=b"{}")
        assert resp.status_code == 401
        assert "Stripe-Signature" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_webhook_invalid_signature():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/billing/webhook",
                content=b"{}",
                headers={"Stripe-Signature": "t=123,v1=deadbeef"},
            )
        assert resp.status_code == 401
        assert "Invalid Stripe signature" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_webhook_checkout_completed_upgrades_to_pro():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": tenant.id,
                "customer": "cus_new",
                "subscription": "sub_new",
            }
        },
    }
    raw = json.dumps(event).encode()
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/billing/webhook",
                content=raw,
                headers=_signed_headers("whsec_test", raw),
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "pro"
        assert body["tenant_id"] == tenant.id
        run(session.refresh(tenant))
        assert tenant.plan == "pro"
        assert tenant.stripe_customer_id == "cus_new"
        assert tenant.stripe_subscription_id == "sub_new"
    finally:
        run(session.close())
        run(engine.dispose())


def test_webhook_subscription_deleted_downgrades():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    tenant.plan = "pro"
    tenant.stripe_customer_id = "cus_z"
    tenant.stripe_subscription_id = "sub_z"
    run(session.commit())
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_z"}},
    }
    raw = json.dumps(event).encode()
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/billing/webhook",
                content=raw,
                headers=_signed_headers("whsec_test", raw),
            )
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"
        run(session.refresh(tenant))
        assert tenant.plan == "free"
        assert tenant.stripe_subscription_id is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_webhook_subscription_updated_status_canceled():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    tenant.plan = "pro"
    run(session.commit())
    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "metadata": {"tenant_id": tenant.id},
                "status": "canceled",
            }
        },
    }
    raw = json.dumps(event).encode()
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/billing/webhook",
                content=raw,
                headers=_signed_headers("whsec_test", raw),
            )
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"
    finally:
        run(session.close())
        run(engine.dispose())


def test_webhook_no_resolvable_tenant_is_ignored():
    engine, session, tenant = run(make_sqlite_session())
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test"
    event = {"type": "customer.subscription.updated", "data": {"object": {}}}
    raw = json.dumps(event).encode()
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/billing/webhook",
                content=raw,
                headers=_signed_headers("whsec_test", raw),
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "ignored": True}
    finally:
        run(session.close())
        run(engine.dispose())


def test_verify_stripe_signature_malformed_header():
    assert billing._verify_stripe_signature(b"{}", "garbage", "secret") is False
    assert billing._verify_stripe_signature(b"{}", "t=123", "secret") is False


def test_verify_stripe_signature_outside_tolerance():
    old_ts = str(int(time.time()) - 10_000)
    sig = hmac.new(
        b"secret", f"{old_ts}.".encode() + b"{}", hashlib.sha256
    ).hexdigest()
    header = f"t={old_ts},v1={sig}"
    assert billing._verify_stripe_signature(b"{}", header, "secret") is False
