"""Admin endpoints, gated by a header-based bearer token.

The token is set via the ADMIN_TOKEN env var on Railway. Endpoints here
are not exposed in the public OpenAPI schema (include_in_schema=False)
and should NEVER use the per-tenant API key auth — they operate across
tenants.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import ApiKey, Approval, AuditEvent, Tenant

router = APIRouter(include_in_schema=False)


def _check_admin(
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Reject unless Authorization: Bearer matches settings.ADMIN_TOKEN."""
    expected = settings.ADMIN_TOKEN
    if not expected:
        raise HTTPException(503, "Admin endpoints disabled (ADMIN_TOKEN not set)")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing admin token")
    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(403, "Invalid admin token")


@router.get("/admin/stats", dependencies=[Depends(_check_admin)])
async def stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Quick tenant + activity stats."""
    total = (await db.execute(select(func.count(Tenant.id)))).scalar_one()
    verified = (
        await db.execute(
            select(func.count(Tenant.id)).where(Tenant.email_verified_at.is_not(None))
        )
    ).scalar_one()
    approvals = (await db.execute(select(func.count(Approval.id)))).scalar_one()
    audit = (await db.execute(select(func.count(AuditEvent.id)))).scalar_one()
    return {
        "tenants_total": total,
        "tenants_verified": verified,
        "tenants_unverified": total - verified,
        "approvals_total": approvals,
        "audit_events_total": audit,
    }


@router.post("/admin/purge-unverified", dependencies=[Depends(_check_admin)])
async def purge_unverified(
    older_than_days: int = 30,
    dry_run: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete tenants that signed up more than `older_than_days` ago and
    never verified their email. Cascades to api_keys + approvals + audit_events.

    Defaults to dry_run=True — pass dry_run=false to actually delete.
    """
    if older_than_days < 1:
        raise HTTPException(400, "older_than_days must be >= 1")

    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    q = await db.execute(
        select(Tenant).where(
            and_(
                Tenant.email_verified_at.is_(None),
                Tenant.created_at < cutoff,
            )
        )
    )
    targets = list(q.scalars())

    sample = [{"id": t.id, "email": t.email, "created_at": str(t.created_at)} for t in targets[:5]]

    if dry_run:
        return {
            "dry_run": True,
            "older_than_days": older_than_days,
            "cutoff": cutoff.isoformat(),
            "would_delete": len(targets),
            "sample": sample,
        }

    deleted_keys = 0
    deleted_approvals = 0
    deleted_audit = 0
    for t in targets:
        # delete dependent rows first to avoid FK violations
        r = await db.execute(delete(AuditEvent).where(AuditEvent.tenant_id == t.id))
        deleted_audit += r.rowcount or 0
        r = await db.execute(delete(ApiKey).where(ApiKey.tenant_id == t.id))
        deleted_keys += r.rowcount or 0
        r = await db.execute(delete(Approval).where(Approval.tenant_id == t.id))
        deleted_approvals += r.rowcount or 0
        await db.execute(delete(Tenant).where(Tenant.id == t.id))
    await db.commit()

    return {
        "dry_run": False,
        "older_than_days": older_than_days,
        "deleted_tenants": len(targets),
        "deleted_api_keys": deleted_keys,
        "deleted_approvals": deleted_approvals,
        "deleted_audit_events": deleted_audit,
        "sample": sample,
    }
