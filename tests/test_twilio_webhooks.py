from twilio.request_validator import RequestValidator
from sqlalchemy import select

from app.config import settings
from app.models import Approval, ApproverContact, AuditEvent, NotificationAttempt
from app.services.contacts import destination_hash, normalize_phone_number
from test_support import TENANT_ID, client_for, make_sqlite_session, run


def _signature(url: str, params: dict[str, str], token: str) -> str:
    return RequestValidator(token).compute_signature(url, params)


def test_twilio_status_webhook_rejects_invalid_signature(monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    try:
        monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
        with client_for(session, tenant) as client:
            response = client.post(
                "/webhooks/twilio/status",
                data={"MessageSid": "SM123", "MessageStatus": "delivered"},
                headers={"X-Twilio-Signature": "bad"},
            )

        assert response.status_code == 401
    finally:
        run(session.close())
        run(engine.dispose())


def test_twilio_status_webhook_updates_attempt_once(monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    try:
        monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
        approval = Approval(
            id="act_123",
            tenant_id=TENANT_ID,
            function_name="transfer_funds",
            arguments={"amount": 1000},
            risk_level="high",
            approvers=["sms:+15551234567"],
            timeout_seconds=300,
        )
        attempt = NotificationAttempt(
            tenant_id=TENANT_ID,
            action_id="act_123",
            channel="sms",
            destination_hash=destination_hash("+15551234567"),
            destination_last4="4567",
            provider="twilio",
            provider_message_sid="SM123",
            provider_status="accepted",
        )
        session.add_all([approval, attempt])
        run(session.commit())

        params = {
            "MessageSid": "SM123",
            "MessageStatus": "undelivered",
            "ErrorCode": "30034",
            "ErrorMessage": "A2P registration incomplete",
        }
        with client_for(session, tenant) as client:
            signature = _signature("http://testserver/webhooks/twilio/status", params, "secret")
            first = client.post(
                "/webhooks/twilio/status",
                data=params,
                headers={"X-Twilio-Signature": signature},
            )
            second = client.post(
                "/webhooks/twilio/status",
                data=params,
                headers={"X-Twilio-Signature": signature},
            )

        assert first.status_code == 200
        assert second.status_code == 200
        run(session.refresh(attempt))
        assert attempt.provider_status == "undelivered"
        assert attempt.error_code == "30034"

        events = run(session.execute(select(AuditEvent)))
        assert [event.execution_result for event in events.scalars().all()] == [
            "notification:sms:undelivered"
        ]
    finally:
        run(session.close())
        run(engine.dispose())


def test_twilio_inbound_stop_revokes_and_start_reactivates_contact(monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    try:
        monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
        phone = normalize_phone_number("+15551234567")
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
        session.add(contact)
        run(session.commit())

        stop = {"From": "+15551234567", "Body": "STOP", "OptOutType": "STOP"}
        start = {"From": "+15551234567", "Body": "START", "OptOutType": "START"}
        with client_for(session, tenant) as client:
            stop_signature = _signature("http://testserver/webhooks/twilio/inbound", stop, "secret")
            stop_response = client.post(
                "/webhooks/twilio/inbound",
                data=stop,
                headers={"X-Twilio-Signature": stop_signature},
            )
        assert stop_response.status_code == 200
        run(session.refresh(contact))
        assert contact.consent_status == "revoked"
        assert contact.revoked_at is not None

        with client_for(session, tenant) as client:
            blocked = client.post(
                "/v1/approvals",
                json={
                    "function_name": "transfer_funds",
                    "arguments": {"amount": 1000},
                    "risk_level": "high",
                    "approvers": ["sms:+15551234567"],
                    "timeout_seconds": 300,
                },
            )
            start_signature = _signature("http://testserver/webhooks/twilio/inbound", start, "secret")
            start_response = client.post(
                "/webhooks/twilio/inbound",
                data=start,
                headers={"X-Twilio-Signature": start_signature},
            )

        assert blocked.status_code == 400
        assert start_response.status_code == 200
        run(session.refresh(contact))
        assert contact.consent_status == "active"
        assert contact.revoked_at is None
    finally:
        run(session.close())
        run(engine.dispose())
