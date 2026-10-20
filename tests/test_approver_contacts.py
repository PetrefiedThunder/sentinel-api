from sqlalchemy import select
from test_support import client_for, make_sqlite_session, run

from app.models import ApproverContact


def test_contact_api_saves_without_sms_consent_attestation():
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

            assert response.status_code == 200
            contact = response.json()
            assert contact["consent_status"] == "not_consented"
            assert contact["consented_at"] is None
            assert contact["revoked_at"] is None

            listed = client.get("/v1/approver-contacts")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == contact["id"]
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
            assert contact["consented_at"] is not None
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


def test_unchecked_attestation_deactivates_existing_sms_contact():
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            payload = {
                "channel": "sms",
                "phone_number": "+15551234567",
                "display_name": "Chris",
                "consent_source": "dashboard",
            }
            active = client.post(
                "/v1/approver-contacts", json={**payload, "consent_attested": True}
            )
            assert active.status_code == 200

            not_consented = client.post(
                "/v1/approver-contacts", json={**payload, "consent_attested": False}
            )
            assert not_consented.status_code == 200
            assert not_consented.json()["id"] == active.json()["id"]
            assert not_consented.json()["consent_status"] == "not_consented"
            assert not_consented.json()["consented_at"] is None
            assert not_consented.json()["revoked_at"] is not None
    finally:
        run(session.close())
        run(engine.dispose())
