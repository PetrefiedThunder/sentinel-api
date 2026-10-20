"""Coverage for app/services/contacts.py — phone normalization + CRUD helpers."""
import pytest
from test_support import make_sqlite_session, run

import app.services.contacts as contacts
from app.models import ApproverContact


def test_normalize_phone_number_strips_formatting():
    assert contacts.normalize_phone_number("+1 (555) 123-4567") == "+15551234567"
    assert contacts.normalize_phone_number(" +15551234567 ") == "+15551234567"


def test_normalize_phone_number_rejects_non_e164():
    with pytest.raises(ValueError):
        contacts.normalize_phone_number("5551234567")  # no +
    with pytest.raises(ValueError):
        contacts.normalize_phone_number("+0123")  # leading 0, too short


def test_sms_approver_phone_extraction():
    assert contacts.sms_approver_phone("sms:+15551234567") == "+15551234567"
    assert contacts.sms_approver_phone("boss@acme.io") is None
    assert contacts.sms_approver_phone(123) is None  # non-string


def test_destination_hash_is_stable_and_keyed():
    h1 = contacts.destination_hash("+15551234567")
    h2 = contacts.destination_hash("+15551234567")
    h3 = contacts.destination_hash("+15559999999")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_create_then_find_active_sms_contact():
    engine, session, tenant = run(make_sqlite_session())
    try:
        created = run(
            contacts.create_or_reactivate_sms_contact(
                session,
                tenant.id,
                "+15551234567",
                display_name="Chris",
                consent_source="dashboard",
                consent_note="ok",
                consent_attested=True,
            )
        )
        assert created.consent_status == "active"
        assert created.destination_last4 == "4567"

        found = run(contacts.find_active_sms_contact(session, tenant.id, "+15551234567"))
        assert found is not None
        assert found.id == created.id
    finally:
        run(session.close())
        run(engine.dispose())


def test_contact_without_explicit_status_defaults_to_not_consented():
    engine, session, tenant = run(make_sqlite_session())
    try:
        phone = "+15551234567"
        contact = ApproverContact(
            tenant_id=tenant.id,
            channel="sms",
            destination=phone,
            destination_hash=contacts.destination_hash(phone),
            destination_last4=phone[-4:],
            consent_source="dashboard",
        )
        session.add(contact)
        run(session.commit())
        assert contact.consent_status == contacts.NOT_CONSENTED
        assert run(contacts.find_active_sms_contact(session, tenant.id, phone)) is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_reactivate_updates_existing_row():
    engine, session, tenant = run(make_sqlite_session())
    try:
        first = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Chris", "dashboard", consent_attested=True
            )
        )
        # revoke then re-create → same row reactivated
        run(contacts.revoke_contact(session, tenant.id, first.id))
        second = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Christopher", "api", consent_attested=True
            )
        )
        assert second.id == first.id
        assert second.consent_status == "active"
        assert second.display_name == "Christopher"
        assert second.revoked_at is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_list_contacts_returns_tenant_rows():
    engine, session, tenant = run(make_sqlite_session())
    try:
        run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "A", "dashboard", consent_attested=True
            )
        )
        rows = run(contacts.list_contacts(session, tenant.id))
        assert len(rows) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_revoke_contact_unknown_returns_none():
    engine, session, tenant = run(make_sqlite_session())
    try:
        assert run(contacts.revoke_contact(session, tenant.id, "con_missing")) is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_find_active_returns_none_when_revoked():
    engine, session, tenant = run(make_sqlite_session())
    try:
        created = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "A", "dashboard", consent_attested=True
            )
        )
        run(contacts.revoke_contact(session, tenant.id, created.id))
        assert run(contacts.find_active_sms_contact(session, tenant.id, "+15551234567")) is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_set_status_by_phone_revokes_all_matching():
    engine, session, tenant = run(make_sqlite_session())
    try:
        run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "A", "dashboard", consent_attested=True
            )
        )
        updated = run(
            contacts.set_sms_contact_status_by_phone(
                session, "+15551234567", contacts.REVOKED, "sms_stop"
            )
        )
        assert len(updated) == 1
        assert updated[0].consent_status == "revoked"
        assert updated[0].revoked_at is not None

        # reactivate via START
        reactivated = run(
            contacts.set_sms_contact_status_by_phone(
                session, "+15551234567", contacts.ACTIVE, "sms_start"
            )
        )
        assert reactivated[0].consent_status == "active"
        assert reactivated[0].revoked_at is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_unchecked_save_preserves_revoked_contact():
    engine, session, tenant = run(make_sqlite_session())
    try:
        created = run(
            contacts.create_or_reactivate_sms_contact(
                session,
                tenant.id,
                "+15551234567",
                "Chris",
                "dashboard",
                "orig note",
                consent_attested=True,
            )
        )
        revoked = run(contacts.revoke_contact(session, tenant.id, created.id))
        assert revoked.consent_status == "revoked"

        saved = run(
            contacts.create_or_reactivate_sms_contact(
                session,
                tenant.id,
                "+15551234567",
                "Chris Renamed",
                "other-source",
                "other note",
                consent_attested=False,
            )
        )
        assert saved.id == created.id
        # Revocation state and provenance survive the unchecked save.
        assert saved.consent_status == "revoked"
        assert saved.consent_source == "dashboard"
        assert saved.consent_note == "orig note"
        assert saved.consented_at == created.consented_at
        assert saved.revoked_at == revoked.revoked_at
        # Unrelated fields are still updated.
        assert saved.display_name == "Chris Renamed"
        # SMS delivery stays gated on active consent.
        assert run(contacts.find_active_sms_contact(session, tenant.id, "+15551234567")) is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_unchecked_save_on_not_consented_contact_keeps_no_consent():
    engine, session, tenant = run(make_sqlite_session())
    try:
        first = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Chris", "dashboard", consent_attested=False
            )
        )
        assert first.consent_status == "not_consented"

        second = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Chris", "dashboard", consent_attested=False
            )
        )
        assert second.id == first.id
        assert second.consent_status == "not_consented"
        assert second.consented_at is None
        assert second.revoked_at is None
        assert run(contacts.find_active_sms_contact(session, tenant.id, "+15551234567")) is None
    finally:
        run(session.close())
        run(engine.dispose())


def test_explicit_reconsent_after_revoke_records_new_provenance():
    engine, session, tenant = run(make_sqlite_session())
    try:
        created = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Chris", "dashboard", consent_attested=True
            )
        )
        revoked = run(contacts.revoke_contact(session, tenant.id, created.id))
        assert revoked.revoked_at is not None

        reconsented = run(
            contacts.create_or_reactivate_sms_contact(
                session,
                tenant.id,
                "+15551234567",
                "Chris",
                "api",
                "re-consented",
                consent_attested=True,
            )
        )
        assert reconsented.id == created.id
        assert reconsented.consent_status == "active"
        assert reconsented.revoked_at is None
        assert reconsented.consent_source == "api"
        assert reconsented.consent_note == "re-consented"
        assert reconsented.consented_at is not None
        assert run(contacts.find_active_sms_contact(session, tenant.id, "+15551234567")) is not None
    finally:
        run(session.close())
        run(engine.dispose())


def test_serialize_contact_shape():
    engine, session, tenant = run(make_sqlite_session())
    try:
        created = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "A", "dashboard", consent_attested=True
            )
        )
        out = contacts.serialize_contact(created)
        assert out["phone_number"] == "+15551234567"
        assert out["destination_last4"] == "4567"
        assert out["channel"] == "sms"
    finally:
        run(session.close())
        run(engine.dispose())
