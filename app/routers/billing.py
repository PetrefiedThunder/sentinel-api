"""Stripe billing — Checkout Session generation + webhook handling.

Scaffolding only — no quota enforcement yet. The MVP gives tenants a way
to upgrade themselves to Pro and reflects the resulting `tenant.plan`
state. Quota enforcement on free-tier hits comes later, when we know what
the right cap is from real usage.

Disabled by default — until STRIPE_SECRET_KEY is set on Railway, both
endpoints return 503.
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.config import settings
from app.db import get_db
from app.models import Tenant

log = logging.getLogger(__name__)
router = APIRouter()

STRIPE_API = "https://api.stripe.com/v1"


def _stripe_enabled() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            503, "Billing is disabled. STRIPE_SECRET_KEY not configured."
        )


async def _stripe_post(path: str, form: dict) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{STRIPE_API}{path}",
            auth=(settings.STRIPE_SECRET_KEY, ""),
            data=form,
        )
    if r.status_code >= 400:
        try:
            detail = r.json().get("error", {}).get("message", r.text[:300])
        except Exception:
            detail = r.text[:300]
        raise HTTPException(r.status_code, f"Stripe API error: {detail}")
    return r.json()


# ── Checkout Session ─────────────────────────────────────────────────
class CheckoutRequest(BaseModel):
    plan: str = "pro"  # currently only "pro" is supported


@router.post("/checkout")
async def create_checkout(
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Generate a Stripe Checkout Session URL the user can click to subscribe."""
    _stripe_enabled()
    if payload.plan != "pro":
        raise HTTPException(400, "Only 'pro' plan is available")
    if not settings.STRIPE_PRICE_PRO:
        raise HTTPException(503, "STRIPE_PRICE_PRO not configured")

    # Reuse the tenant's Stripe Customer if we have one — otherwise let
    # Checkout create one via the customer_email field.
    form: dict = {
        "mode": "subscription",
        "line_items[0][price]": settings.STRIPE_PRICE_PRO,
        "line_items[0][quantity]": 1,
        "success_url": settings.STRIPE_SUCCESS_URL,
        "cancel_url": settings.STRIPE_CANCEL_URL,
        "client_reference_id": tenant.id,
        "metadata[tenant_id]": tenant.id,
        "allow_promotion_codes": "true",
    }
    if tenant.stripe_customer_id:
        form["customer"] = tenant.stripe_customer_id
    else:
        form["customer_email"] = tenant.email

    session = await _stripe_post("/checkout/sessions", form)
    return {"url": session.get("url"), "id": session.get("id")}


# ── Stripe webhook (subscription events) ─────────────────────────────
@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """Receive subscription lifecycle events from Stripe. Signature-verified
    via the STRIPE_WEBHOOK_SECRET. Updates tenant.plan on success."""
    _stripe_enabled()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "STRIPE_WEBHOOK_SECRET not configured")
    if not stripe_signature:
        raise HTTPException(401, "Missing Stripe-Signature header")

    raw_body = await request.body()
    if not _verify_stripe_signature(
        raw_body, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
    ):
        raise HTTPException(401, "Invalid Stripe signature")

    try:
        event = httpx.Response(200, content=raw_body).json()
    except Exception:
        raise HTTPException(400, "Malformed JSON body") from None

    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    tenant_id = (
        obj.get("client_reference_id")
        or (obj.get("metadata") or {}).get("tenant_id")
        or None
    )

    if not tenant_id:
        # try to find by stripe_customer_id (subscription.updated events
        # don't always carry client_reference_id)
        customer_id = obj.get("customer")
        if customer_id:
            r = await db.execute(
                select(Tenant).where(Tenant.stripe_customer_id == customer_id)
            )
            tenant = r.scalar_one_or_none()
            if tenant:
                tenant_id = tenant.id

    if not tenant_id:
        log.warning("Stripe webhook %s — no tenant_id resolvable", event_type)
        return {"ok": True, "ignored": True}

    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        log.warning("Stripe webhook %s — tenant %s not found", event_type, tenant_id)
        return {"ok": True, "ignored": True}

    now = datetime.utcnow()

    if event_type in ("checkout.session.completed", "customer.subscription.created"):
        tenant.plan = "pro"
        if obj.get("customer"):
            tenant.stripe_customer_id = obj["customer"]
        if obj.get("subscription"):
            tenant.stripe_subscription_id = obj["subscription"]
        elif obj.get("id") and event_type == "customer.subscription.created":
            tenant.stripe_subscription_id = obj["id"]
        tenant.plan_updated_at = now

    elif event_type == "customer.subscription.updated":
        status = obj.get("status")
        if status in ("active", "trialing"):
            tenant.plan = "pro"
        elif status in ("past_due", "unpaid", "incomplete"):
            # Don't downgrade automatically — let dunning handle it.
            pass
        elif status in ("canceled", "incomplete_expired"):
            tenant.plan = "free"
        tenant.plan_updated_at = now

    elif event_type == "customer.subscription.deleted":
        tenant.plan = "free"
        tenant.stripe_subscription_id = None
        tenant.plan_updated_at = now

    await db.commit()
    return {"ok": True, "event": event_type, "tenant_id": tenant.id, "plan": tenant.plan}


def _verify_stripe_signature(
    raw_body: bytes, sig_header: str, secret: str, tolerance: int = 300
) -> bool:
    """Verify Stripe's v1 webhook signature. Format: 't=TIMESTAMP,v1=SIG[,...]'.

    Manual implementation so we don't take a hard dep on the stripe SDK.
    Standard pattern; matches stripe.Webhook.construct_event().
    """
    import hashlib
    import hmac
    import time as _time

    try:
        parts = dict(p.split("=", 1) for p in sig_header.split(","))
    except ValueError:
        return False
    ts = parts.get("t")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False

    # tolerance to mitigate replay
    try:
        if abs(_time.time() - int(ts)) > tolerance:
            return False
    except ValueError:
        return False

    signed_payload = f"{ts}.".encode() + raw_body
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)


# ── GET current plan ─────────────────────────────────────────────────
@router.get("/me")
async def get_billing_info(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Current billing state. Always returns something, even if Stripe is disabled."""
    return {
        "plan": tenant.plan,
        "stripe_customer_id": tenant.stripe_customer_id,
        "stripe_subscription_id": tenant.stripe_subscription_id,
        "plan_updated_at": tenant.plan_updated_at,
        "billing_enabled": bool(settings.STRIPE_SECRET_KEY),
    }
