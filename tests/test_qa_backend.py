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
from _qa_values import rbase_url, rhex, rhost, rid, rphone
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

# Generated per run; +999 is not an assigned ITU country code.
QA_PHONE_CONSENTED = rphone()
QA_PHONE_UNCONSENTED = rphone()
while QA_PHONE_UNCONSENTED == QA_PHONE_CONSENTED:
    QA_PHONE_UNCONSENTED = rphone()
TENANT_IDS = {"owner": rid("ten"), "other": rid("ten")}
CONTACT_IDS = {"owner": rid("con"), "other": rid("con")}
ACTION_ID = rid("act")
WEBHOOK_ID = rid("whk")
ATTEMPT_ID = rid("nat")
MESSAGE_SID = f"SM{rhex(16)}"
FUNCTION_NAME = rid("fn")
SHARED_KEY = rhex()
INVALID_KEY = rhex()
QA_TEXT = rhex()
HOOK_URL = f"https://{rhost()}/hook"
BASE_URL = rbase_url()


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
            tenant_id = TENANT_IDS[name]
            session.add(
                Tenant(
                    id=tenant_id, name=name, mode="test",
                    email=f"{secrets.token_hex(8)}@example.invalid",
                )
            )
            await session.flush()
            raw, prefix, key_hash = generate_api_key(mode="test")
            keys[name] = raw
            session.add(ApiKey(tenant_id=tenant_id, key_hash=key_hash, prefix=prefix))
            session.add(
                ApproverContact(
                    id=CONTACT_IDS[name], tenant_id=tenant_id, channel="sms",
                    destination=QA_PHONE_CONSENTED,
                    destination_hash=destination_hash(QA_PHONE_CONSENTED),
                    destination_last4=QA_PHONE_CONSENTED[-4:],
                    consent_status="active", consent_source=QA_TEXT,
                )
            )
        raw, prefix, key_hash = generate_api_key(mode="test")
        keys["revoked"] = raw
        session.add(
            ApiKey(
                tenant_id=TENANT_IDS["owner"], key_hash=key_hash, prefix=prefix,
                revoked_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        session.add(
            Approval(id=ACTION_ID, tenant_id=TENANT_IDS["owner"], function_name=FUNCTION_NAME)
        )
        session.add(
            WebhookEndpoint(
                id=WEBHOOK_ID, tenant_id=TENANT_IDS["owner"],
                url=HOOK_URL, secret=secrets.token_hex(32),
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
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield SimpleNamespace(client=client, sessions=factory, keys=keys)
    finally:
        await engine.dispose()


def bearer(qa_api, name="owner"):
    return {"Authorization": f"Bearer {qa_api.keys[name]}"}


@pytest.mark.parametrize("identity", ["other", "revoked", "invalid", "missing"])
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", f"/v1/approvals/{ACTION_ID}", None),
        ("GET", f"/v1/approvals/{ACTION_ID}/wait?timeout=1", None),
        ("POST", f"/v1/approvals/{ACTION_ID}/decision",
         {"decision": "approved", "decided_by": QA_TEXT}),
        ("POST", "/v1/audit-events",
         {"action_id": ACTION_ID, "execution_result": QA_TEXT}),
        ("DELETE", f"/v1/webhooks/{WEBHOOK_ID}", None),
    ],
)
async def test_auth_permissions_matrix_preserves_foreign_state(qa_api, identity, method, path, payload):
    headers = {} if identity == "missing" else (
        {"Authorization": f"Bearer {INVALID_KEY}"} if identity == "invalid"
        else bearer(qa_api, identity)
    )
    response = await qa_api.client.request(method, path, json=payload, headers=headers)
    expected = 404 if identity == "other" else (422 if identity == "missing" else 401)
    assert response.status_code == expected
    async with qa_api.sessions() as session:
        assert (await session.get(Approval, ACTION_ID)).decision == "pending"
        assert (await session.get(WebhookEndpoint, WEBHOOK_ID)).disabled_at is None
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_same_idempotency_key_is_isolated_between_real_authenticated_tenants(qa_api):
    payload = {
        "function_name": FUNCTION_NAME,
        "approvers": [f"{secrets.token_hex(8)}@example.invalid"],
    }
    responses = []
    for name in ("owner", "other"):
        headers = {**bearer(qa_api, name), "Idempotency-Key": SHARED_KEY}
        first = await qa_api.client.post("/v1/approvals", json=payload, headers=headers)
        replay = await qa_api.client.post("/v1/approvals", json=payload, headers=headers)
        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()
        assert first.json()["tenant_id"] == TENANT_IDS[name]
        responses.append(first.json())
    assert responses[0]["id"] != responses[1]["id"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BE-001: recovery token can rotate keys repeatedly")
async def test_recovery_token_is_single_use_and_preserves_first_recovered_key(qa_api):
    token = onboarding.create_token("recover", TENANT_IDS["owner"], ttl_seconds=300)
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
    "path", [f"/v1/approvals/{ACTION_ID}/token-decision",
             "/v1/tenants/recover/exchange", "/v1/tenants/verify-email"],
)
@pytest.mark.parametrize("token", ["", "without-dot", "payload.bad-signature"])
async def test_malformed_ascii_token_classes_fail_closed(qa_api, path, token):
    response = await qa_api.client.post(path, json={"token": token})
    assert response.status_code in (400, 401)


@pytest.mark.parametrize(
    "path", [f"/v1/approvals/{ACTION_ID}/token-decision",
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
        assert (await session.get(Approval, ACTION_ID)).decision == "pending"
        assert (await session.get(Tenant, TENANT_IDS["owner"])).email_verified_at is None
        assert await session.scalar(select(func.count()).select_from(ApiKey)) == 3


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BE-005: recovery emits a live key prefix for a test workspace")
async def test_recovered_key_keeps_test_workspace_mode(qa_api):
    token = onboarding.create_token("recover", TENANT_IDS["owner"], ttl_seconds=300)
    response = await qa_api.client.post("/v1/tenants/recover/exchange", json={"token": token})
    if response.status_code != 200:
        pytest.fail("Recovery precondition failed: valid exchange did not succeed")
    has_test_prefix = response.json()["api_key"].startswith("sk_test_")
    assert has_test_prefix


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="BE-006: fallback SMS approvers skip create-time consent validation")
async def test_default_sms_approver_obeys_same_consent_requirement_as_explicit_approver(qa_api):
    destination = f"sms:{QA_PHONE_UNCONSENTED}"
    payload = {"function_name": FUNCTION_NAME, "approvers": [destination]}
    explicit = await qa_api.client.post("/v1/approvals", json=payload, headers=bearer(qa_api))
    if explicit.status_code != 400:
        pytest.fail("Consent precondition failed: explicit unconsented destination was not rejected")
    settings_response = await qa_api.client.patch(
        "/v1/tenants/me", json={"default_approvers": [destination]}, headers=bearer(qa_api)
    )
    if settings_response.status_code != 200:
        pytest.fail("Consent precondition failed: default approver setting was not saved")
    fallback = await qa_api.client.post(
        "/v1/approvals", json={"function_name": FUNCTION_NAME}, headers=bearer(qa_api)
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
        "/webhooks/twilio/inbound", data={"From": QA_PHONE_CONSENTED, "Body": keyword}
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
            id=ATTEMPT_ID, tenant_id=TENANT_IDS["owner"], action_id=ACTION_ID,
            channel="sms", destination_hash=destination_hash(QA_PHONE_CONSENTED),
            destination_last4=QA_PHONE_CONSENTED[-4:], provider="twilio", provider_message_sid=MESSAGE_SID,
            provider_status="accepted",
        ))
        await session.commit()
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", secrets.token_hex(32) if configured else "")
    response = await qa_api.client.post(
        "/webhooks/twilio/status", data={"MessageSid": MESSAGE_SID, "MessageStatus": "delivered"}
    )
    async with qa_api.sessions() as session:
        attempt = await session.get(NotificationAttempt, ATTEMPT_ID)
        assert attempt.provider_status == "accepted"
        assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0
    assert response.status_code == (401 if configured else 503)


async def test_audit_csv_neutralizes_spreadsheet_formula_cells(qa_api):
    response = await qa_api.client.post(
        "/v1/audit-events",
        json={"action_id": ACTION_ID, "execution_result": "failed", "error": "=1+1"},
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
