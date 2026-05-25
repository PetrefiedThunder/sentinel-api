from sqlalchemy import select

from app.models import ApproverContact
from test_support import client_for, make_sqlite_session, run


def test_contact_api_requires_explicit_sms_consent_attestation():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            response = client.post(
                "/v1/approver-contacts",
                json={
                    "channel": "sms",
                    "phone_number": "+15551234567",
                    "display_name": "Chris",
                    "consent_attested": False,
                    "consent_source": "dashboard",
                },
            )

        assert response.status_code == 400
        assert "consent" in response.json()["detail"].lower()
    finally:
        run(session.close())
        run(engine.dispose())


def test_contact_api_normalizes_lists_revokes_and_reactivates_sms_contact():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            created = client.post(
                "/v1/approver-contacts",
                json={
                    "channel": "sms",
                    "phone_number": "+1 (555) 123-4567",
                    "display_name": "Chris",
                    "consent_attested": True,
                    "consent_source": "dashboard",
                    "consent_note": "Approver consented during setup.",
                },
            )

            assert created.status_code == 200
            contact = created.json()
            assert contact["phone_number"] == "+15551234567"
            assert contact["destination_last4"] == "4567"
            assert contact["consent_status"] == "active"
            assert contact["revoked_at"] is None

            listed = client.get("/v1/approver-contacts")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [contact["id"]]

            revoked = client.delete(f"/v1/approver-contacts/{contact['id']}")
            assert revoked.status_code == 200
            assert revoked.json()["consent_status"] == "revoked"
            assert revoked.json()["revoked_at"] is not None

            reactivated = client.post(
                "/v1/approver-contacts",
                json={
                    "channel": "sms",
                    "phone_number": "+15551234567",
                    "display_name": "Chris",
                    "consent_attested": True,
                    "consent_source": "dashboard",
                },
            )
            assert reactivated.status_code == 200
            assert reactivated.json()["id"] == contact["id"]
            assert reactivated.json()["consent_status"] == "active"
            assert reactivated.json()["revoked_at"] is None

        rows = run(session.execute(select(ApproverContact)))
        assert len(rows.scalars().all()) == 1
    finally:
        run(session.close())
        run(engine.dispose())
