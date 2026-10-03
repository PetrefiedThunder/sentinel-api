"""2026-10-02 QA: real auth boundaries and security regression specifications.

All state is synthetic and in-memory. The application lifespan is deliberately
not entered. Known defects are strict xfails linked to the QA findings report.
"""

import csv
import io
import json
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import generate_api_key, hash_key
from app.config import settings
from app.db import Base, get_db
from app.models import (
    ApiKey,
    Approval,
    ApproverContact,
    AuditEvent,
    NotificationAttempt,
    Tenant,
    WebhookEndpoint,
)
from app.routers import approvals, audit, tenants, twilio_webhooks, webhooks
from app.services import onboarding
from app.services.contacts import destination_hash


@pytest_asyncio.fixture
async def qa_api(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", secrets.token_hex(32))
    monkeypatch.setattr(settings, "TSA_URL", "")
    monkeypatch.setattr(settings, "DEFAULT_APPROVERS", "")

    async def no_side_effects(*args, **kwargs):
        return None

    monkeypatch.setattr(approvals, "notify_decision", no_side_effects)
    monkeypatch.setattr(approvals, "dispatch_approval_webhook", no_side_effects)
    monkeypatch.setattr(
        "app.services.approval_service.dispatch_approval_notifications", no_side_effects
    )
    monkeypatch.setattr(tenants, "rate_limit", no_side_effects)
    monkeypatch.setattr(tenants, "send_recovery_email", no_side_effects)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    keys = {}
    async with factory() as session:
        for name in ("owner", "other"):
            tenant_id = f"ten_qa_{name}"
            session.add(
                Tenant(id=tenant_id, name=name, email=f"{name}@example.invalid", mode="test")
            )
            await session.flush()
            raw, prefix, key_hash = generate_api_key(mode="test")
            keys[name] = raw
            session.add(ApiKey(tenant_id=tenant_id, key_hash=key_hash, prefix=prefix))
            session.add(
                ApproverContact(
                    id=f"con_qa_{name}", tenant_id=tenant_id, channel="sms",
                    destination="+15551230000", destination_hash=destination_hash("+15551230000"),
                    destination_last4="0000", consent_status="active", consent_source="qa",
                )
            )
        raw, prefix, key_hash = generate_api_key(mode="test")
        keys["revoked"] = raw
        session.add(
            ApiKey(
                tenant_id="ten_qa_owner", key_hash=key_hash, prefix=prefix,
                revoked_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        session.add(
            Approval(id="act_qa_owner", tenant_id="ten_qa_owner", function_name="qa_action")
        )
        session.add(
            WebhookEndpoint(
                id="whk_qa_owner", tenant_id="ten_qa_owner",
                url="https://example.invalid/hook", secret=secrets.token_hex(32),
            )
        )
        await session.commit()

    async def database():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.include_router(approvals.router, prefix="/v1/approvals")
    app.include_router(audit.router, prefix="/v1/audit-events")
    app.include_router(tenants.router, prefix="/v1/tenants")
    app.include_router(webhooks.router, prefix="/v1/webhooks")
    app.include_router(twilio_webhooks.router)
    app.dependency_overrides[get_db] = database
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://qa.local") as client:
            yield SimpleNamespace(client=client, sessions=factory, keys=keys)
    finally:
        await engine.dispose()


def bearer(qa_api, name="owner"):
    return {"Authorization": f"Bearer {qa_api.keys[name]}"}


@pytest.mark.parametrize("identity", ["other", "revoked", "invalid", "missing"])
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/v1/approvals/act_qa_owner", None),
        ("GET", "/v1/approvals/act_qa_owner/wait?timeout=1", None),
        ("POST", "/v1/approvals/act_qa_owner/decision",
         {"decision": "approved", "decided_by": "qa"}),
        ("POST", "/v1/audit-events",
         {"action_id": "act_qa_owner", "execution_result": "qa"}),
        ("DELETE", "/v1/webhooks/whk_qa_owner", None),
    ],
)
async def test_auth_permissions_matrix_preserves_foreign_state(qa_api, identity, method, path, payload):
    headers = {} if identity == "missing" else (
        {"Authorization": "Bearer not-a-real-key"} if identity == "invalid"
        else bearer(qa_api, identity)
    )
    response = await qa_api.client.request(method, path, json=payload, headers=headers)
    expected = 404 if identity == "other" else (422 if identity == "missing" else 401)
    assert response.status_code == expected
    async with qa_api.sessions() as session:
        assert (await session.get(Approval, "act_qa_owner")).decision == "pending"
        assert (await session.get(WebhookEndpoint, "whk_qa_owner")).disabled_at is None
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_same_idempotency_key_is_isolated_between_real_authenticated_tenants(qa_api):
    payload = {"function_name": "qa_action", "approvers": ["qa@example.invalid"]}
    responses = []
    for name in ("owner", "other"):
        headers = {**bearer(qa_api, name), "Idempotency-Key": "qa-shared-key"}
        first = await qa_api.client.post("/v1/approvals", json=payload, headers=headers)
        replay = await qa_api.client.post("/v1/approvals", json=payload, headers=headers)
        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()
        assert first.json()["tenant_id"] == f"ten_qa_{name}"
        responses.append(first.json())
    assert responses[0]["id"] != responses[1]["id"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BE-001: recovery token can rotate keys repeatedly")
async def test_recovery_token_is_single_use_and_preserves_first_recovered_key(qa_api):
    token = onboarding.create_token("recover", "ten_qa_owner", ttl_seconds=300)
    first = await qa_api.client.post("/v1/tenants/recover/exchange", json={"token": token})
    if first.status_code != 200:
        pytest.fail("Recovery precondition failed: first valid exchange did not succeed")
    recovered_hash = hash_key(first.json()["api_key"])
    replay = await qa_api.client.post("/v1/tenants/recover/exchange", json={"token": token})
    async with qa_api.sessions() as session:
        recovered = await session.scalar(select(ApiKey).where(ApiKey.key_hash == recovered_hash))
        unchanged = recovered.revoked_at is None
    assert (replay.status_code in (400, 401, 409), unchanged) == (True, True)


def test_onboarding_rejects_weak_signing_configuration(monkeypatch):
    # Exercise the actual configured default without printing or minting a token.
    weak_default = type(settings).model_fields["JWT_SECRET"].default
    monkeypatch.setattr(settings, "JWT_SECRET", weak_default)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        onboarding._sign("qa-non-token-payload")


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "[::1]"])
async def test_webhook_registration_rejects_private_network_targets(qa_api, scheme, host):
    # BE-003: reject unsafe registrations without persisting an endpoint.
    # Registration alone has no outbound request. Never resolve or call the URL.
    url = f"{scheme}://{host}/hook"
    response = await qa_api.client.post("/v1/webhooks", json={"url": url}, headers=bearer(qa_api))
    if response.status_code not in (200, 400, 422):
        pytest.fail("Webhook registration failed outside the destination-validation boundary")
    assert response.status_code in (400, 422)
    async with qa_api.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(WebhookEndpoint)) == 1


@pytest.mark.parametrize(
    "path", ["/v1/approvals/act_qa_owner/token-decision",
             "/v1/tenants/recover/exchange", "/v1/tenants/verify-email"],
)
@pytest.mark.parametrize("token", ["", "without-dot", "payload.bad-signature"])
async def test_malformed_ascii_token_classes_fail_closed(qa_api, path, token):
    response = await qa_api.client.post(path, json={"token": token})
    assert response.status_code in (400, 401)


@pytest.mark.parametrize(
    "path", ["/v1/approvals/act_qa_owner/token-decision",
             "/v1/tenants/recover/exchange", "/v1/tenants/verify-email"],
)
@pytest.mark.parametrize(
    "token",
    ["invalid.\N{SNOWMAN}", "\N{SNOWMAN}.invalid", "invalid.\ud800", "\ud800.invalid"],
    ids=["unicode-signature", "unicode-payload", "surrogate-signature", "surrogate-payload"],
)
async def test_unicode_token_signature_is_a_client_error(qa_api, path, token):
    # BE-004: reject malformed encoding before signing or comparing strings.
    response = await qa_api.client.post(
        path, content=json.dumps({"token": token}), headers={"Content-Type": "application/json"}
    )
    assert response.status_code in (400, 401)
    async with qa_api.sessions() as session:
        assert (await session.get(Approval, "act_qa_owner")).decision == "pending"
        assert (await session.get(Tenant, "ten_qa_owner")).email_verified_at is None
        assert await session.scalar(select(func.count()).select_from(ApiKey)) == 3


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BE-005: recovery emits a live key prefix for a test workspace")
async def test_recovered_key_keeps_test_workspace_mode(qa_api):
    token = onboarding.create_token("recover", "ten_qa_owner", ttl_seconds=300)
    response = await qa_api.client.post("/v1/tenants/recover/exchange", json={"token": token})
    if response.status_code != 200:
        pytest.fail("Recovery precondition failed: valid exchange did not succeed")
    has_test_prefix = response.json()["api_key"].startswith("sk_test_")
    assert has_test_prefix


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BE-006: fallback SMS approvers skip create-time consent validation")
async def test_default_sms_approver_obeys_same_consent_requirement_as_explicit_approver(qa_api):
    destination = "sms:+15551234567"
    payload = {"function_name": "qa_action", "approvers": [destination]}
    explicit = await qa_api.client.post("/v1/approvals", json=payload, headers=bearer(qa_api))
    if explicit.status_code != 400:
        pytest.fail("Consent precondition failed: explicit unconsented destination was not rejected")
    settings_response = await qa_api.client.patch(
        "/v1/tenants/me", json={"default_approvers": [destination]}, headers=bearer(qa_api)
    )
    if settings_response.status_code != 200:
        pytest.fail("Consent precondition failed: default approver setting was not saved")
    fallback = await qa_api.client.post(
        "/v1/approvals", json={"function_name": "qa_action"}, headers=bearer(qa_api)
    )
    assert fallback.status_code == 400


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize(("keyword", "initial_status"), [("STOP", "active"), ("START", "revoked")])
async def test_unsigned_twilio_callback_cannot_change_multiple_tenants(
    qa_api, monkeypatch, configured, keyword, initial_status
):
    # BE-007: reject before contact or audit mutation in either consent direction.
    async with qa_api.sessions() as session:
        for contact in await session.scalars(select(ApproverContact)):
            contact.consent_status = initial_status
        await session.commit()
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", secrets.token_hex(32) if configured else "")
    response = await qa_api.client.post(
        "/webhooks/twilio/inbound", data={"From": "+15551230000", "Body": keyword}
    )
    async with qa_api.sessions() as session:
        contacts = (await session.scalars(select(ApproverContact))).all()
        unchanged = all(contact.consent_status == initial_status for contact in contacts)
        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert response.status_code == (401 if configured else 503)
    assert unchanged
    assert audit_count == 0


@pytest.mark.parametrize("configured", [True, False])
async def test_be007_unsigned_status_callback_preserves_attempt_and_audit(qa_api, monkeypatch, configured):
    async with qa_api.sessions() as session:
        session.add(NotificationAttempt(
            id="nat_qa_owner", tenant_id="ten_qa_owner", action_id="act_qa_owner",
            channel="sms", destination_hash=destination_hash("+15551230000"),
            destination_last4="0000", provider="twilio", provider_message_sid="SMqa",
            provider_status="accepted",
        ))
        await session.commit()
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", secrets.token_hex(32) if configured else "")
    response = await qa_api.client.post(
        "/webhooks/twilio/status", data={"MessageSid": "SMqa", "MessageStatus": "delivered"}
    )
    async with qa_api.sessions() as session:
        attempt = await session.get(NotificationAttempt, "nat_qa_owner")
        assert attempt.provider_status == "accepted"
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0
    assert response.status_code == (401 if configured else 503)


async def test_audit_csv_neutralizes_spreadsheet_formula_cells(qa_api):
    response = await qa_api.client.post(
        "/v1/audit-events",
        json={"action_id": "act_qa_owner", "execution_result": "failed", "error": "=1+1"},
        headers=bearer(qa_api),
    )
    if response.status_code != 200:
        pytest.fail("CSV precondition failed: synthetic audit event could not be created")
    exported = await qa_api.client.get("/v1/audit-events.csv", headers=bearer(qa_api))
    if exported.status_code != 200:
        pytest.fail("CSV precondition failed: audit export could not be fetched")
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    if len(rows) != 1:
        pytest.fail("CSV precondition failed: expected exactly one synthetic event")
    assert rows[0]["error"].startswith("'=")
