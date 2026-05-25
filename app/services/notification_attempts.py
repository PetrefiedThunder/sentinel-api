from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationAttempt
from app.services.contacts import destination_hash, normalize_phone_number


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


async def create_sms_attempt(
    db: AsyncSession,
    tenant_id: str,
    action_id: str,
    contact_id: str | None,
    phone_number: str,
) -> NotificationAttempt:
    phone = normalize_phone_number(phone_number)
    now = utcnow()
    attempt = NotificationAttempt(
        tenant_id=tenant_id,
        action_id=action_id,
        contact_id=contact_id,
        channel="sms",
        destination_hash=destination_hash(phone),
        destination_last4=phone[-4:],
        provider="twilio",
        provider_status="pending",
        created_at=now,
        updated_at=now,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def mark_attempt_sent(
    db: AsyncSession,
    attempt: NotificationAttempt,
    provider_message_sid: str | None,
    provider_status: str | None,
) -> NotificationAttempt:
    attempt.provider_message_sid = provider_message_sid
    attempt.provider_status = provider_status or "accepted"
    attempt.error_code = None
    attempt.error_message = None
    attempt.updated_at = utcnow()
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def mark_attempt_failed(
    db: AsyncSession,
    attempt: NotificationAttempt,
    error_message: str,
    error_code: str | None = None,
) -> NotificationAttempt:
    attempt.provider_status = "failed"
    attempt.error_code = error_code
    attempt.error_message = error_message
    attempt.updated_at = utcnow()
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def update_attempt_from_provider_status(
    db: AsyncSession,
    provider_message_sid: str,
    provider_status: str,
    error_code: str | None = None,
    error_message: str | None = None,
) -> tuple[NotificationAttempt | None, bool]:
    result = await db.execute(
        select(NotificationAttempt).where(
            NotificationAttempt.provider_message_sid == provider_message_sid
        )
    )
    attempt = result.scalar_one_or_none()
    if attempt is None:
        return None, False
    changed = (
        attempt.provider_status != provider_status
        or attempt.error_code != error_code
        or attempt.error_message != error_message
    )
    if not changed:
        return attempt, False
    attempt.provider_status = provider_status
    attempt.error_code = error_code
    attempt.error_message = error_message
    attempt.updated_at = utcnow()
    await db.commit()
    await db.refresh(attempt)
    return attempt, True
