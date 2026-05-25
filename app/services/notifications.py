import json
import logging
from html import escape
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.db import SessionLocal
from app.services.approval_tokens import create_decision_token
from app.services.audit_log import append_audit_event
from app.services.contacts import find_active_sms_contact, normalize_phone_number
from app.services.notification_attempts import (
    create_sms_attempt,
    mark_attempt_failed,
    mark_attempt_sent,
)

logger = logging.getLogger(__name__)


async def dispatch_approval_notifications(approval, tenant, db=None):
    await _send_email(approval, tenant)
    if db is not None or tenant is None:
        await _send_sms(approval, tenant, db)
        return
    async with SessionLocal() as session:
        await _send_sms(approval, tenant, session)


async def _send_email(approval, tenant):
    api_key = settings.RESEND_API_KEY
    if not api_key:
        return
    recipients: list[str] = []
    for approver in approval.approvers or []:
        if not isinstance(approver, str):
            continue
        if approver.startswith("mailto:"):
            recipients.append(approver[len("mailto:"):])
        elif "@" in approver and not approver.startswith("sms:"):
            recipients.append(approver)
    if not recipients:
        return
    try:
        approve_url = _decision_url(approval, "approved")
        reject_url = _decision_url(approval, "rejected")
        args_str = escape(json.dumps(approval.arguments, indent=2, default=str), quote=True)
        function_name = escape(str(approval.function_name), quote=True)
        risk_level = escape(str(approval.risk_level), quote=True)
        html = (
            f"<h2>Approval needed: {function_name}</h2>"
            f"<p><b>Risk:</b> {risk_level}</p>"
            f"<pre>{args_str}</pre>"
            f'<p><a href="{approve_url}">Approve</a> &middot; '
            f'<a href="{reject_url}">Reject</a></p>'
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": "Sentinel <onboarding@resend.dev>",
                    "to": recipients,
                    "subject": f"Approval needed: {approval.function_name}",
                    "html": html,
                },
            )
    except Exception as e:
        logger.warning("email notify failed: %s", e)


async def _send_sms(approval, tenant, db=None):
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_FROM_NUMBER
    messaging_service_sid = settings.TWILIO_MESSAGING_SERVICE_SID
    if not account_sid or not auth_token or not (from_number or messaging_service_sid):
        return
    recipients: list[str] = []
    for approver in approval.approvers or []:
        if isinstance(approver, str) and approver.startswith("sms:"):
            recipients.append(approver[len("sms:"):])
    if not recipients:
        return
    try:
        approve_url = _decision_url(approval, "approved")
        reject_url = _decision_url(approval, "rejected")
        body = (
            f"Sentinel approval needed: {approval.function_name}\n"
            f"Risk: {approval.risk_level}\n"
            f"Approve: {approve_url}\n"
            f"Reject: {reject_url}\n"
            "Reply STOP to opt out, HELP for help."
        )
        url = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{account_sid}/Messages.json"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            for recipient in recipients:
                normalized_recipient = normalize_phone_number(recipient)
                contact = None
                if db is not None and tenant is not None:
                    contact = await find_active_sms_contact(db, tenant.id, normalized_recipient)
                    if contact is None:
                        logger.warning("sms notify skipped: no active consent contact for %s", normalized_recipient[-4:])
                        continue
                attempt = None
                if db is not None and tenant is not None:
                    attempt = await create_sms_attempt(
                        db,
                        tenant.id,
                        approval.id,
                        contact.id if contact else None,
                        normalized_recipient,
                    )
                message_data = {
                    "To": normalized_recipient,
                    "Body": body,
                }
                if settings.PUBLIC_API_URL:
                    message_data["StatusCallback"] = (
                        f"{settings.PUBLIC_API_URL.rstrip('/')}/webhooks/twilio/status"
                    )
                if messaging_service_sid:
                    message_data["MessagingServiceSid"] = messaging_service_sid
                else:
                    message_data["From"] = from_number
                try:
                    response = await client.post(
                        url,
                        auth=(account_sid, auth_token),
                        data=message_data,
                    )
                    response.raise_for_status()
                    provider_payload = response.json()
                    if attempt is not None:
                        await mark_attempt_sent(
                            db,
                            attempt,
                            provider_payload.get("sid"),
                            provider_payload.get("status"),
                        )
                except Exception as e:
                    error_message = _provider_error_message(e)
                    if attempt is not None:
                        await mark_attempt_failed(db, attempt, error_message, _provider_error_code(e))
                        await append_audit_event(
                            db,
                            tenant.id,
                            approval.id,
                            "notification:sms:failed",
                            error_message,
                        )
                    logger.warning("sms notify failed: %s", e)
    except Exception as e:
        logger.warning("sms notify failed: %s", e)


def _decision_url(approval, decision: str) -> str:
    token = create_decision_token(
        approval.id,
        decision,
        expires_in_seconds=approval.timeout_seconds,
    )
    query = urlencode({"d": decision, "t": token})
    return f"{settings.PUBLIC_APP_URL}/approve/{approval.id}?{query}"


def _provider_error_message(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}: {error.response.text}"
    return str(error)


def _provider_error_code(error: Exception) -> str | None:
    if isinstance(error, httpx.HTTPStatusError):
        return str(error.response.status_code)
    return None
