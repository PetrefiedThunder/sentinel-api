from app.models import ApproverContact
from app.services.contacts import destination_hash, normalize_phone_number
from test_support import TENANT_ID, client_for, make_sqlite_session, run


def test_create_approval_rejects_unregistered_sms_approver():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            response = client.post(
                "/v1/approvals",
                json={
                    "function_name": "transfer_funds",
                    "arguments": {"amount": 1000},
                    "risk_level": "high",
                    "approvers": ["sms:+15551234567"],
                    "timeout_seconds": 300,
                },
            )

        assert response.status_code == 400
        assert "active sms consent" in response.json()["detail"].lower()
    finally:
        run(session.close())
        run(engine.dispose())


def test_create_approval_rejects_revoked_sms_approver():
    engine, session, tenant = run(make_sqlite_session())
    try:
        phone = normalize_phone_number("+15551234567")
        session.add(
            ApproverContact(
                tenant_id=TENANT_ID,
                channel="sms",
                destination=phone,
                destination_hash=destination_hash(phone),
                destination_last4=phone[-4:],
                display_name="Chris",
                consent_status="revoked",
                consent_source="dashboard",
            )
        )
        run(session.commit())

        with client_for(session, tenant) as client:
            response = client.post(
                "/v1/approvals",
                json={
                    "function_name": "transfer_funds",
                    "arguments": {"amount": 1000},
                    "risk_level": "high",
                    "approvers": ["sms:+15551234567"],
                    "timeout_seconds": 300,
                },
            )

        assert response.status_code == 400
        assert "active sms consent" in response.json()["detail"].lower()
    finally:
        run(session.close())
        run(engine.dispose())


def test_create_approval_accepts_active_sms_contact(monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    try:
        async def noop_dispatch(approval, tenant, db=None):
            return None

        monkeypatch.setattr("app.services.approval_service.dispatch_approval_notifications", noop_dispatch)

        with client_for(session, tenant) as client:
            contact_response = client.post(
                "/v1/approver-contacts",
                json={
                    "channel": "sms",
                    "phone_number": "+15551234567",
                    "display_name": "Chris",
                    "consent_attested": True,
                    "consent_source": "dashboard",
                },
            )
            assert contact_response.status_code == 200

            response = client.post(
                "/v1/approvals",
                json={
                    "function_name": "transfer_funds",
                    "arguments": {"amount": 1000},
                    "risk_level": "high",
                    "approvers": ["sms:+15551234567"],
                    "timeout_seconds": 300,
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "pending"
    finally:
        run(session.close())
        run(engine.dispose())
