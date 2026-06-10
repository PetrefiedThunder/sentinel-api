"""Webhook delivery — HMAC-signed POSTs to customer URLs on approval decisions.

Flow:
  1. Customer registers an endpoint via POST /v1/webhooks with a URL.
     We mint a random secret and return it ONCE.
  2. When an approval is decided (approved/rejected), we look up matching
     endpoints for that tenant and fire a POST.
  3. The POST body is JSON: {event, action_id, decision, decided_by, ...}
  4. We sign the body with HMAC-SHA256(secret, raw_body) and put the
     signature in the `X-Sentinel-Signature` header. Customer can verify.
  5. We log every attempt in webhook_deliveries (status_code, response_snippet).
  6. Best-effort with 3 retries on 5xx/timeout, exponential backoff
     (1s, 4s, 16s). Never blocks the decision endpoint.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approval, WebhookDelivery, WebhookEndpoint

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [1.0, 4.0, 16.0]
HTTP_TIMEOUT = 8.0
SIGNATURE_HEADER = "X-Sentinel-Signature"
EVENT_HEADER = "X-Sentinel-Event"
ID_HEADER = "X-Sentinel-Delivery"

# The event loop only keeps weak references to tasks; without a strong
# reference here, an in-flight delivery (and its retries) can be GC'd.
_inflight: set[asyncio.Task] = set()


def _track(task: asyncio.Task) -> None:
    _inflight.add(task)
    task.add_done_callback(_on_delivery_done)


def _on_delivery_done(task: asyncio.Task) -> None:
    _inflight.discard(task)
    if not task.cancelled() and (exc := task.exception()) is not None:
        log.error("webhook delivery task crashed: %s", exc, exc_info=exc)


def generate_secret() -> str:
    """64-char URL-safe random secret. Shown ONCE on creation."""
    return f"whsec_{secrets.token_urlsafe(32)}"


def sign_body(secret: str, raw_body: bytes) -> str:
    """HMAC-SHA256 hex digest of the raw POST body, signed with the endpoint secret.

    Customer verifies via:
        expected = hmac.new(secret.encode(), raw_body, sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers["X-Sentinel-Signature"]):
            return 401
    """
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def _event_type_for(approval: Approval) -> str | None:
    if approval.decision == "approved":
        return "approval.approved"
    if approval.decision == "rejected":
        return "approval.rejected"
    return None


def _matches_filter(endpoint: WebhookEndpoint, event_type: str) -> bool:
    """Endpoint subscribes to event if filter is empty or contains the event."""
    f = endpoint.event_filter or []
    if not f:
        return True
    return event_type in f


def _build_payload(event_type: str, approval: Approval, delivery_id: str) -> dict[str, Any]:
    return {
        "id": delivery_id,
        "event": event_type,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "action_id": approval.id,
        "tenant_id": approval.tenant_id,
        "function_name": approval.function_name,
        "arguments": approval.arguments,
        "risk_level": approval.risk_level,
        "decision": approval.decision,
        "decided_by": approval.decided_by,
        "decided_at": approval.decided_at.isoformat() + "Z" if approval.decided_at else None,
        "reason": approval.reason,
    }


async def dispatch_approval_webhook(
    db: AsyncSession, approval: Approval
) -> None:
    """Look up all webhook endpoints for this tenant subscribed to the event,
    fire each one as a background task (best-effort with retries)."""
    event_type = _event_type_for(approval)
    if event_type is None:
        return

    result = await db.execute(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == approval.tenant_id,
            WebhookEndpoint.disabled_at.is_(None),
        )
    )
    endpoints = [e for e in result.scalars() if _matches_filter(e, event_type)]
    if not endpoints:
        return

    for endpoint in endpoints:
        # Spawn each delivery as its own task — never block the caller.
        _track(asyncio.create_task(_deliver_with_retries(endpoint, event_type, approval)))


async def _deliver_with_retries(
    endpoint: WebhookEndpoint, event_type: str, approval: Approval
) -> None:
    """Run in a background task. Owns its own DB session to avoid lifecycle issues."""
    from app.db import SessionLocal

    delivery_id = f"whd_{secrets.token_hex(8)}"
    payload = _build_payload(event_type, approval, delivery_id)
    raw_body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = sign_body(endpoint.secret, raw_body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Sentinel-Webhook/1.0",
        SIGNATURE_HEADER: signature,
        EVENT_HEADER: event_type,
        ID_HEADER: delivery_id,
    }

    last_status: int | None = None
    last_snippet: str | None = None
    success = False

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                r = await client.post(endpoint.url, content=raw_body, headers=headers)
                last_status = r.status_code
                last_snippet = (r.text or "")[:512]
                if 200 <= r.status_code < 300:
                    success = True
                    break
                # 4xx (except 408/429) — don't retry, the customer rejected us
                if 400 <= r.status_code < 500 and r.status_code not in (408, 429):
                    break
            except httpx.RequestError as e:
                last_snippet = f"{type(e).__name__}: {str(e)[:400]}"
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])

    # Record delivery + bump endpoint last-used/status
    try:
        async with SessionLocal() as db2:
            db2.add(
                WebhookDelivery(
                    id=delivery_id,
                    endpoint_id=endpoint.id,
                    tenant_id=endpoint.tenant_id,
                    event_type=event_type,
                    action_id=approval.id,
                    payload=payload,
                    attempt=attempt,
                    status_code=last_status,
                    response_snippet=last_snippet,
                    delivered_at=datetime.utcnow() if success else None,
                )
            )
            ep = await db2.get(WebhookEndpoint, endpoint.id)
            if ep is not None:
                ep.last_used_at = datetime.utcnow()
                ep.last_status_code = last_status
            await db2.commit()
    except Exception:
        log.exception("Failed to record webhook delivery for endpoint %s", endpoint.id)
