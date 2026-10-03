"""Webhook management endpoints — CRUD on webhook_endpoints + read deliveries.

Authenticated with the standard per-tenant API key (Authorization: Bearer sk_live_...).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Tenant, WebhookDelivery, WebhookEndpoint
from app.services.pagination import paginate_stmt
from app.services.webhook_destinations import UnsafeWebhookDestination, validate_webhook_url
from app.services.webhooks import generate_secret

router = APIRouter()


ALLOWED_EVENTS = {"approval.approved", "approval.rejected"}


class CreateWebhookRequest(BaseModel):
    url: str
    description: str | None = None
    event_filter: list[str] | None = None  # empty/None = all events


def _serialize_endpoint(e: WebhookEndpoint, *, include_secret: bool = False) -> dict:
    out = {
        "id": e.id,
        "url": e.url,
        "description": e.description,
        "event_filter": e.event_filter or [],
        "created_at": e.created_at,
        "disabled_at": e.disabled_at,
        "last_used_at": e.last_used_at,
        "last_status_code": e.last_status_code,
    }
    if include_secret:
        out["secret"] = e.secret  # only on creation
    return out


def _serialize_delivery(d: WebhookDelivery) -> dict:
    return {
        "id": d.id,
        "endpoint_id": d.endpoint_id,
        "event_type": d.event_type,
        "action_id": d.action_id,
        "attempt": d.attempt,
        "status_code": d.status_code,
        "response_snippet": d.response_snippet,
        "delivered_at": d.delivered_at,
        "created_at": d.created_at,
    }


@router.post("")
async def create_webhook(
    payload: CreateWebhookRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Register a new webhook endpoint. The `secret` is returned ONCE — store it,
    we don't expose it again. Customer uses it to verify HMAC signatures."""
    try:
        validate_webhook_url(payload.url)
    except UnsafeWebhookDestination as exc:
        raise HTTPException(400, str(exc)) from exc
    if payload.event_filter:
        bad = [e for e in payload.event_filter if e not in ALLOWED_EVENTS]
        if bad:
            raise HTTPException(
                400,
                f"Unknown event(s): {bad}. Allowed: {sorted(ALLOWED_EVENTS)}",
            )

    secret = generate_secret()
    endpoint = WebhookEndpoint(
        tenant_id=tenant.id,
        url=payload.url,
        secret=secret,
        description=payload.description,
        event_filter=payload.event_filter or None,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return _serialize_endpoint(endpoint, include_secret=True)


@router.get("")
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """List this tenant's webhook endpoints. Secrets are NOT included."""
    result = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant.id)
        .order_by(desc(WebhookEndpoint.created_at))
    )
    return [_serialize_endpoint(e) for e in result.scalars()]


@router.delete("/{endpoint_id}")
async def disable_webhook(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Soft-disable an endpoint (we keep its delivery history for audit)."""
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.tenant_id != tenant.id:
        raise HTTPException(404, "Webhook not found")
    if endpoint.disabled_at is None:
        endpoint.disabled_at = datetime.utcnow()
        await db.commit()
    return {"id": endpoint.id, "disabled_at": endpoint.disabled_at}


@router.get("/deliveries")
async def list_deliveries(
    endpoint_id: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=200),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Inspect webhook deliveries for this tenant.

    Backward-compatible: no limit + no cursor → legacy top-50 bare array.
    Either present → cursor-paginated envelope {data, has_more, next_cursor}.
    """
    base = select(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant.id)
    if endpoint_id:
        base = base.where(WebhookDelivery.endpoint_id == endpoint_id)

    if limit is None and cursor is None:
        stmt = base.order_by(
            desc(WebhookDelivery.created_at), desc(WebhookDelivery.id)
        ).limit(50)
        result = await db.execute(stmt)
        return [_serialize_delivery(d) for d in result.scalars()]

    page = await paginate_stmt(
        db, base, WebhookDelivery, limit=limit or 50, cursor=cursor
    )
    return {
        "data": [_serialize_delivery(d) for d in page.items],
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
    }
