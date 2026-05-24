import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import Approval
from app.services.audit_log import append_audit_event

router = APIRouter()


def _verify_slack(body: bytes, timestamp: str, signature: str) -> bool:
    secret = settings.SLACK_SIGNING_SECRET
    if not secret:
        return False
    basestring = f"v0:{timestamp}:{body.decode()}"
    expected = (
        "v0="
        + hmac.new(secret.encode(), basestring.encode(), hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


@router.post("/slack/interactivity")
async def slack_interactivity(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if settings.SLACK_SIGNING_SECRET and not _verify_slack(body, timestamp, signature):
        raise HTTPException(401, "Invalid Slack signature")
    form = urllib.parse.parse_qs(body.decode())
    if "payload" not in form:
        raise HTTPException(400, "Missing payload")
    payload = json.loads(form["payload"][0])
    actions = payload.get("actions") or []
    if not actions:
        return {"ok": True}
    action = actions[0]
    action_id = action.get("value")
    action_kind = action.get("action_id")
    decision = "approved" if action_kind == "approve" else "rejected"
    user = (payload.get("user") or {}).get("username", "unknown")
    approval = await db.get(Approval, action_id)
    if approval and approval.decision == "pending":
        approval.decision = decision
        approval.decided_by = f"slack:{user}"
        approval.decided_at = datetime.utcnow()
        await db.commit()
        await append_audit_event(
            db, approval.tenant_id, approval.id, f"decision:{decision}"
        )
    return {"text": f"Decision recorded: {decision}"}
