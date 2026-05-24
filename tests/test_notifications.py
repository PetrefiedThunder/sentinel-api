from types import SimpleNamespace

import pytest

from app.config import settings
from app.services import notifications


class FakeAsyncClient:
    requests = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return SimpleNamespace(status_code=201)


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch):
    FakeAsyncClient.requests = []
    monkeypatch.setattr(notifications.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "")
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
                    "Body": (
                        "Sentinel approval needed: transfer_funds\n"
                        "Risk: high\n"
                        "Approve: https://app.pauseapi.app/approve/act_123?d=approved&t=approved_token\n"
                        "Reject: https://app.pauseapi.app/approve/act_123?d=rejected&t=rejected_token"
                    ),
                },
            },
        )
    ]


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
