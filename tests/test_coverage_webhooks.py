"""Coverage for app/routers/webhooks.py and app/services/webhooks.py."""
import asyncio

from test_support import client_for, make_sqlite_session, run

import app.services.webhooks as whsvc
from app.models import Approval, WebhookDelivery, WebhookEndpoint


# ── Router ────────────────────────────────────────────────────────────
def test_create_webhook_returns_secret_once():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/webhooks",
                json={"url": "https://example.com/hook", "description": "test"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["secret"].startswith("whsec_")
        assert body["url"] == "https://example.com/hook"
        # list does NOT include the secret
        with client_for(session, tenant) as client:
            listed = client.get("/v1/webhooks")
        assert listed.status_code == 200
        items = listed.json()
        assert len(items) == 1
        assert "secret" not in items[0]
    finally:
        run(session.close())
        run(engine.dispose())


def test_create_webhook_rejects_bad_url():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post("/v1/webhooks", json={"url": "ftp://example.com"})
        assert resp.status_code == 400
        assert "url must start" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_create_webhook_rejects_unknown_event_filter():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/webhooks",
                json={"url": "https://x.io/h", "event_filter": ["approval.exploded"]},
            )
        assert resp.status_code == 400
        assert "Unknown event" in resp.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_disable_webhook_soft_deletes():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            created = client.post("/v1/webhooks", json={"url": "https://x.io/h"})
            wid = created.json()["id"]
            resp = client.delete(f"/v1/webhooks/{wid}")
        assert resp.status_code == 200
        assert resp.json()["disabled_at"] is not None
    finally:
        run(session.close())
        run(engine.dispose())


def test_disable_webhook_404_for_unknown_id():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.delete("/v1/webhooks/whk_nope")
        assert resp.status_code == 404
    finally:
        run(session.close())
        run(engine.dispose())


def test_list_deliveries_legacy_array_and_paginated():
    engine, session, tenant = run(make_sqlite_session())
    ep = WebhookEndpoint(tenant_id=tenant.id, url="https://x.io/h", secret="whsec_a")
    session.add(ep)
    run(session.flush())
    for i in range(3):
        session.add(
            WebhookDelivery(
                endpoint_id=ep.id,
                tenant_id=tenant.id,
                event_type="approval.approved",
                action_id=f"act_{i}",
                attempt=1,
                status_code=200,
            )
        )
    run(session.commit())
    try:
        with client_for(session, tenant) as client:
            legacy = client.get("/v1/webhooks/deliveries")
            assert legacy.status_code == 200
            assert isinstance(legacy.json(), list)
            assert len(legacy.json()) == 3

            paged = client.get("/v1/webhooks/deliveries?limit=2")
            assert paged.status_code == 200
            env = paged.json()
            assert env["has_more"] is True
            assert len(env["data"]) == 2
    finally:
        run(session.close())
        run(engine.dispose())


# ── Service: pure helpers ─────────────────────────────────────────────
def test_generate_secret_prefix_and_uniqueness():
    a = whsvc.generate_secret()
    b = whsvc.generate_secret()
    assert a.startswith("whsec_")
    assert a != b


def test_sign_body_is_deterministic_hmac():
    sig1 = whsvc.sign_body("secret", b"hello")
    sig2 = whsvc.sign_body("secret", b"hello")
    sig3 = whsvc.sign_body("other", b"hello")
    assert sig1 == sig2
    assert sig1 != sig3
    assert len(sig1) == 64  # sha256 hex


def test_event_type_for_maps_decisions():
    approved = Approval(tenant_id="t", function_name="f", decision="approved")
    rejected = Approval(tenant_id="t", function_name="f", decision="rejected")
    pending = Approval(tenant_id="t", function_name="f", decision="pending")
    assert whsvc._event_type_for(approved) == "approval.approved"
    assert whsvc._event_type_for(rejected) == "approval.rejected"
    assert whsvc._event_type_for(pending) is None


def test_matches_filter():
    e_all = WebhookEndpoint(tenant_id="t", url="u", secret="s", event_filter=None)
    e_only = WebhookEndpoint(
        tenant_id="t", url="u", secret="s", event_filter=["approval.rejected"]
    )
    assert whsvc._matches_filter(e_all, "approval.approved") is True
    assert whsvc._matches_filter(e_only, "approval.approved") is False
    assert whsvc._matches_filter(e_only, "approval.rejected") is True


def test_build_payload_shape():
    approval = Approval(
        id="act_1",
        tenant_id="t",
        function_name="wire",
        arguments={"amount": 100},
        risk_level="high",
        decision="approved",
        decided_by="boss@x.io",
    )
    payload = whsvc._build_payload("approval.approved", approval, "whd_x")
    assert payload["id"] == "whd_x"
    assert payload["event"] == "approval.approved"
    assert payload["action_id"] == "act_1"
    assert payload["function_name"] == "wire"
    assert payload["decided_at"] is None  # decided_at not set


# ── Service: dispatch short-circuits ──────────────────────────────────
def test_dispatch_skips_non_decision():
    engine, session, tenant = run(make_sqlite_session())
    approval = Approval(tenant_id=tenant.id, function_name="f", decision="pending")
    session.add(approval)
    run(session.commit())
    try:
        # Should return without spawning tasks (no event type for pending)
        run(whsvc.dispatch_approval_webhook(session, approval))
    finally:
        run(session.close())
        run(engine.dispose())


def test_dispatch_no_endpoints_is_noop():
    engine, session, tenant = run(make_sqlite_session())
    approval = Approval(tenant_id=tenant.id, function_name="f", decision="approved")
    session.add(approval)
    run(session.commit())
    try:
        run(whsvc.dispatch_approval_webhook(session, approval))
    finally:
        run(session.close())
        run(engine.dispose())


def test_dispatch_spawns_delivery_task(monkeypatch):
    """dispatch_approval_webhook should create a task per matching endpoint."""
    engine, session, tenant = run(make_sqlite_session())
    ep = WebhookEndpoint(tenant_id=tenant.id, url="https://x.io/h", secret="whsec_a")
    session.add(ep)
    approval = Approval(tenant_id=tenant.id, function_name="f", decision="approved")
    session.add(approval)
    run(session.commit())

    spawned = []

    async def fake_deliver(endpoint, event_type, appr):
        spawned.append((endpoint.id, event_type))

    monkeypatch.setattr(whsvc, "_deliver_with_retries", fake_deliver)

    async def scenario():
        await whsvc.dispatch_approval_webhook(session, approval)
        # let the spawned task run
        await asyncio.sleep(0)

    try:
        run(scenario())
        assert spawned == [(ep.id, "approval.approved")]
    finally:
        run(session.close())
        run(engine.dispose())
