from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from app.config import settings
from app.db import get_db
from app.services.audit_log import append_audit_event
from app.services.contacts import ACTIVE, REVOKED, set_sms_contact_status_by_phone
from app.services.notification_attempts import update_attempt_from_provider_status

router = APIRouter(prefix="/webhooks/twilio", tags=["twilio"])

STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
START_WORDS = {"START", "YES", "UNSTOP"}


async def _verified_form(request: Request):
    if not settings.TWILIO_AUTH_TOKEN:
        raise HTTPException(503, "Twilio webhook authentication is not configured")
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    validation_url = f"{settings.PUBLIC_API_URL.rstrip('/')}{request.url.path}"
    if request.url.query:
        validation_url = f"{validation_url}?{request.url.query}"
    if not validator.validate(validation_url, params, signature):
        raise HTTPException(401, "Invalid Twilio signature")
    return params


@router.post("/status")
async def status_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    params = await _verified_form(request)
    message_sid = params.get("MessageSid")
    message_status = params.get("MessageStatus")
    if not message_sid or not message_status:
        raise HTTPException(400, "Missing MessageSid or MessageStatus")
    attempt, changed = await update_attempt_from_provider_status(
        db,
        message_sid,
        message_status,
        params.get("ErrorCode"),
        params.get("ErrorMessage"),
    )
    if attempt and changed:
        await append_audit_event(
            db,
            attempt.tenant_id,
            attempt.action_id,
            f"notification:sms:{message_status}",
            params.get("ErrorMessage") or params.get("ErrorCode"),
        )
    return {"ok": True}


@router.post("/inbound")
async def inbound_message(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    params = await _verified_form(request)
    sender = params.get("From")
    if not sender:
        raise HTTPException(400, "Missing From")
    keyword = (params.get("OptOutType") or params.get("Body") or "").strip().upper()
    status = None
    action = None
    if keyword in STOP_WORDS:
        status = REVOKED
        action = "opt_out"
    elif keyword in START_WORDS:
        status = ACTIVE
        action = "opt_in"
    if status:
        contacts = await set_sms_contact_status_by_phone(db, sender, status, "twilio_inbound")
        for contact in contacts:
            await append_audit_event(
                db,
                contact.tenant_id,
                None,
                f"notification:sms:{action}",
                None,
            )
    return Response(content="", media_type="text/plain")
