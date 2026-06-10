from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from test_support import TENANT_ID, make_sqlite_session

from app.config import settings
from app.models import Approval, ApproverContact, AuditEvent, NotificationAttempt
from app.services import notifications
from app.services.contacts import destination_hash, normalize_phone_number


class FakeResponse:
    def __init__(self, status_code=201, payload=None):
        self.status_code = status_code
        self._payload = payload or {"sid": "SM123", "status": "accepted"}
        self.text = str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.twilio.com")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("provider error", request=request, response=response)


class FakeAsyncClient:
    requests = []
    responses = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.responses:
            return self.responses.pop(0)
        return FakeResponse()


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    FakeAsyncClient.requests = []
    FakeAsyncClient.responses = []
    monkeypatch.setattr(notifications.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "")
    monkeypatch.setattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "", raising=False)
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "PUBLIC_APP_URL", "https://app.pauseapi.app")


@pytest.mark.asyncio
async def test_send_sms_posts_twilio_message_for_sms_approvers(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "+15550000000")
    monkeypatch.setattr(
        notifications,
        "create_decision_token",
        lambda action_id, decision, expires_in_seconds: f"{decision}_token",
        raising=False,
    )
    approval = SimpleNamespace(
        id="act_123",
        function_name="transfer_funds",
        risk_level="high",
        approvers=["sms:+15551234567"],
        timeout_seconds=300,
    )

    await notifications.dispatch_approval_notifications(approval, tenant=None)

    assert FakeAsyncClient.requests == [
        (
            "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json",
            {
                "auth": ("AC123", "secret"),
                "data": {
                    "From": "+15550000000",
                    "To": "+15551234567",
                    "StatusCallback": "https://api.pauseapi.app/webhooks/twilio/status",
                    "Body": (
                        "Sentinel approval needed: transfer_funds\n"
                        "Risk: high\n"
                        "Approve: https://app.pauseapi.app/approve/act_123?d=approved&t=approved_token\n"
                        "Reject: https://app.pauseapi.app/approve/act_123?d=rejected&t=rejected_token\n"
                        "Reply STOP to opt out, HELP for help."
                    ),
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_send_sms_uses_messaging_service_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "")
    monkeypatch.setattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "MG123", raising=False)
    monkeypatch.setattr(
        notifications,
        "create_decision_token",
        lambda action_id, decision, expires_in_seconds: f"{decision}_token",
        raising=False,
    )
    approval = SimpleNamespace(
        id="act_123",
        function_name="transfer_funds",
        risk_level="high",
        approvers=["sms:+15551234567"],
        timeout_seconds=300,
    )

    await notifications.dispatch_approval_notifications(approval, tenant=None)

    assert FakeAsyncClient.requests[0][1]["data"]["MessagingServiceSid"] == "MG123"
    assert "From" not in FakeAsyncClient.requests[0][1]["data"]


@pytest.mark.asyncio
async def test_send_sms_records_attempt_and_status_callback_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "MG123", raising=False)
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.pauseapi.app", raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET", "x" * 32)
    monkeypatch.setattr(
        notifications,
        "create_decision_token",
        lambda action_id, decision, expires_in_seconds: f"{decision}_token",
        raising=False,
    )
    engine, session, tenant = await make_sqlite_session()
    try:
        phone = normalize_phone_number("+15551234567")
        approval = Approval(
            id="act_123",
            tenant_id=TENANT_ID,
            function_name="transfer_funds",
            arguments={"amount": 1000},
            risk_level="high",
            approvers=["sms:+15551234567"],
            timeout_seconds=300,
        )
        contact = ApproverContact(
            tenant_id=TENANT_ID,
            channel="sms",
            destination=phone,
            destination_hash=destination_hash(phone),
            destination_last4=phone[-4:],
            display_name="Chris",
            consent_status="active",
            consent_source="dashboard",
        )
        session.add_all([approval, contact])
        await session.commit()

        await notifications.dispatch_approval_notifications(approval, tenant, db=session)

        request_data = FakeAsyncClient.requests[0][1]["data"]
        assert request_data["MessagingServiceSid"] == "MG123"
        assert request_data["StatusCallback"] == "https://api.pauseapi.app/webhooks/twilio/status"
        assert "From" not in request_data

        result = await session.execute(select(NotificationAttempt))
        attempt = result.scalar_one()
        assert attempt.contact_id == contact.id
        assert attempt.destination_hash == destination_hash(phone)
        assert attempt.destination_last4 == "4567"
        assert attempt.provider_message_sid == "SM123"
        assert attempt.provider_status == "accepted"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_send_sms_records_failed_attempt_and_audit_event(monkeypatch):
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "TWILIO_MESSAGING_SERVICE_SID", "MG123", raising=False)
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.pauseapi.app", raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET", "x" * 32)
    FakeAsyncClient.responses = [FakeResponse(status_code=400, payload={"message": "bad request"})]
    engine, session, tenant = await make_sqlite_session()
    try:
        phone = normalize_phone_number("+15551234567")
        approval = Approval(
            id="act_123",
            tenant_id=TENANT_ID,
            function_name="transfer_funds",
            arguments={"amount": 1000},
            risk_level="high",
            approvers=["sms:+15551234567"],
            timeout_seconds=300,
        )
        contact = ApproverContact(
            tenant_id=TENANT_ID,
            channel="sms",
            destination=phone,
            destination_hash=destination_hash(phone),
            destination_last4=phone[-4:],
            display_name="Chris",
            consent_status="active",
            consent_source="dashboard",
        )
        session.add_all([approval, contact])
        await session.commit()

        await notifications.dispatch_approval_notifications(approval, tenant, db=session)

        attempts = await session.execute(select(NotificationAttempt))
        attempt = attempts.scalar_one()
        assert attempt.provider_status == "failed"
        assert "400" in attempt.error_message

        events = await session.execute(select(AuditEvent))
        assert [event.execution_result for event in events.scalars().all()] == [
            "notification:sms:failed"
        ]
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_email_notification_escapes_dynamic_html(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "resend_secret")
    monkeypatch.setattr(settings, "JWT_SECRET", "x" * 32)
    approval = SimpleNamespace(
        id="act_123",
        function_name="<b>transfer</b>",
        risk_level="high",
        arguments={"payload": "<script>alert(1)</script>"},
        approvers=["mailto:ops@example.com"],
        timeout_seconds=300,
    )

    await notifications.dispatch_approval_notifications(approval, tenant=None)

    html = FakeAsyncClient.requests[0][1]["json"]["html"]
    assert "<b>transfer</b>" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;b&gt;transfer&lt;/b&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


@pytest.mark.asyncio
async def test_sms_is_not_sent_without_twilio_credentials():
    approval = SimpleNamespace(
        id="act_123",
        function_name="transfer_funds",
        risk_level="high",
        approvers=["sms:+15551234567"],
        timeout_seconds=300,
    )

    await notifications.dispatch_approval_notifications(approval, tenant=None)

    assert FakeAsyncClient.requests == []


@pytest.mark.asyncio
async def test_slack_approvers_do_not_dispatch_notifications():
    approval = SimpleNamespace(
        id="act_123",
        function_name="transfer_funds",
        risk_level="high",
        arguments={"amount": 1000},
        approvers=["slack://channel/C123"],
        timeout_seconds=300,
    )

    await notifications.dispatch_approval_notifications(approval, tenant=None)

    assert not hasattr(settings, "SLACK_BOT_TOKEN")
    assert not hasattr(notifications, "_send_slack")
    assert FakeAsyncClient.requests == []
