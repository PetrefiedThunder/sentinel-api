import hashlib
import hmac
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ApproverContact


ACTIVE = "active"
REVOKED = "revoked"


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_phone_number(value: str) -> str:
    cleaned = re.sub(r"[\s().-]+", "", (value or "").strip())
    if not re.fullmatch(r"\+[1-9]\d{7,14}", cleaned):
        raise ValueError("phone_number must be E.164, e.g. +15551234567")
    return cleaned


def destination_hash(destination: str) -> str:
    return hmac.new(
        settings.JWT_SECRET.encode(),
        destination.encode(),
        hashlib.sha256,
    ).hexdigest()


def sms_approver_phone(approver: str) -> str | None:
    if isinstance(approver, str) and approver.startswith("sms:"):
        return normalize_phone_number(approver[len("sms:"):])
    return None


async def find_sms_contact(
    db: AsyncSession,
    tenant_id: str,
    phone_number: str,
) -> ApproverContact | None:
    phone = normalize_phone_number(phone_number)
    result = await db.execute(
        select(ApproverContact).where(
            ApproverContact.tenant_id == tenant_id,
            ApproverContact.channel == "sms",
            ApproverContact.destination_hash == destination_hash(phone),
        )
    )
    return result.scalar_one_or_none()


async def find_active_sms_contact(
    db: AsyncSession,
    tenant_id: str,
    phone_number: str,
) -> ApproverContact | None:
    contact = await find_sms_contact(db, tenant_id, phone_number)
    if contact and contact.consent_status == ACTIVE:
        return contact
    return None


async def create_or_reactivate_sms_contact(
    db: AsyncSession,
    tenant_id: str,
    phone_number: str,
    display_name: str | None,
    consent_source: str,
    consent_note: str | None = None,
) -> ApproverContact:
    phone = normalize_phone_number(phone_number)
    now = utcnow()
    contact = await find_sms_contact(db, tenant_id, phone)
    if contact is None:
        contact = ApproverContact(
            tenant_id=tenant_id,
            channel="sms",
            destination=phone,
            destination_hash=destination_hash(phone),
            destination_last4=phone[-4:],
            display_name=display_name,
            consent_status=ACTIVE,
            consent_source=consent_source,
            consent_note=consent_note,
            consented_at=now,
            revoked_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(contact)
    else:
        contact.destination = phone
        contact.destination_last4 = phone[-4:]
        contact.display_name = display_name
        contact.consent_status = ACTIVE
        contact.consent_source = consent_source
        contact.consent_note = consent_note
        contact.consented_at = now
        contact.revoked_at = None
        contact.updated_at = now
    await db.commit()
    await db.refresh(contact)
    return contact


async def list_contacts(db: AsyncSession, tenant_id: str) -> list[ApproverContact]:
    result = await db.execute(
        select(ApproverContact)
        .where(ApproverContact.tenant_id == tenant_id)
        .order_by(ApproverContact.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_contact(db: AsyncSession, tenant_id: str, contact_id: str) -> ApproverContact | None:
    contact = await db.get(ApproverContact, contact_id)
    if not contact or contact.tenant_id != tenant_id:
        return None
    contact.consent_status = REVOKED
    contact.revoked_at = utcnow()
    contact.updated_at = contact.revoked_at
    await db.commit()
    await db.refresh(contact)
    return contact


async def set_sms_contact_status_by_phone(
    db: AsyncSession,
    phone_number: str,
    status: str,
    consent_source: str,
) -> list[ApproverContact]:
    phone = normalize_phone_number(phone_number)
    result = await db.execute(
        select(ApproverContact).where(
            ApproverContact.channel == "sms",
            ApproverContact.destination_hash == destination_hash(phone),
        )
    )
    contacts = list(result.scalars().all())
    now = utcnow()
    for contact in contacts:
        contact.consent_status = status
        contact.consent_source = consent_source
        contact.updated_at = now
        if status == ACTIVE:
            contact.consented_at = now
            contact.revoked_at = None
        else:
            contact.revoked_at = now
    await db.commit()
    for contact in contacts:
        await db.refresh(contact)
    return contacts


def serialize_contact(contact: ApproverContact) -> dict:
    return {
        "id": contact.id,
        "tenant_id": contact.tenant_id,
        "channel": contact.channel,
        "phone_number": contact.destination,
        "destination_last4": contact.destination_last4,
        "display_name": contact.display_name,
        "consent_status": contact.consent_status,
        "consent_source": contact.consent_source,
        "consent_note": contact.consent_note,
        "consented_at": contact.consented_at,
        "revoked_at": contact.revoked_at,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }
