"""Coverage for app/services/contacts.py — phone normalization + CRUD helpers."""
import pytest
from test_support import make_sqlite_session, run

import app.services.contacts as contacts


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


def test_reactivate_updates_existing_row():
    engine, session, tenant = run(make_sqlite_session())
    try:
        first = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Chris", "dashboard"
            )
        )
        # revoke then re-create → same row reactivated
        run(contacts.revoke_contact(session, tenant.id, first.id))
        second = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "Christopher", "api"
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
                session, tenant.id, "+15551234567", "A", "dashboard"
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
                session, tenant.id, "+15551234567", "A", "dashboard"
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
                session, tenant.id, "+15551234567", "A", "dashboard"
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


def test_serialize_contact_shape():
    engine, session, tenant = run(make_sqlite_session())
    try:
        created = run(
            contacts.create_or_reactivate_sms_contact(
                session, tenant.id, "+15551234567", "A", "dashboard"
            )
        )
        out = contacts.serialize_contact(created)
        assert out["phone_number"] == "+15551234567"
        assert out["destination_last4"] == "4567"
        assert out["channel"] == "sms"
    finally:
        run(session.close())
        run(engine.dispose())
