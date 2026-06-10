"""Admin endpoints, gated by a header-based bearer token.

The token is set via the ADMIN_TOKEN env var on Railway. Endpoints here
are not exposed in the public OpenAPI schema (include_in_schema=False)
and should NEVER use the per-tenant API key auth — they operate across
tenants.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import ApiKey, Approval, AuditEvent, Tenant

router = APIRouter(include_in_schema=False)


def _check_admin(
    authorization: str | None = Header(default=None),
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


@router.post("/admin/rechain-audit", dependencies=[Depends(_check_admin)])
async def rechain_audit(dry_run: bool = True, db: AsyncSession = Depends(get_db)) -> dict:
    """ONE-TIME pre-GA repair: rebuild every tenant's audit chain in canonical
    (created_at, id) order.

    Why this exists: append_audit_event had a concurrency race (no per-tenant
    lock) that forked the chain under parallel appends. The race is fixed
    (advisory lock in audit_log.py); this endpoint heals the historical forks.
    All current data is pre-customer test data — rewriting hashes is
    acceptable exactly once, before any customer relies on the chain.

    THIS ENDPOINT MUST BE REMOVED after the one production run. A standing
    re-chain capability would contradict the tamper-evidence guarantee.
    """
    from app.services.audit_log import _compute_hash

    tenant_ids = (
        (await db.execute(select(AuditEvent.tenant_id).distinct())).scalars().all()
    )
    rewritten = 0
    per_tenant: dict[str, int] = {}
    for tid in tenant_ids:
        events = (
            (
                await db.execute(
                    select(AuditEvent)
                    .where(AuditEvent.tenant_id == tid)
                    .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )
        prev_hash = None
        for e in events:
            payload = {
                "action_id": e.action_id,
                "execution_result": e.execution_result,
                "error": e.error,
            }
            new_hash = _compute_hash(prev_hash, payload)
            if e.prev_hash != prev_hash or e.event_hash != new_hash:
                rewritten += 1
                per_tenant[tid] = per_tenant.get(tid, 0) + 1
                if not dry_run:
                    e.prev_hash = prev_hash
                    e.event_hash = new_hash
            # next link always chains off the canonical hash, in both modes,
            # so dry_run predicts exactly what execute will write
            prev_hash = new_hash
    if not dry_run:
        await db.commit()
    return {
        "dry_run": dry_run,
        "tenants_walked": len(tenant_ids),
        "events_rewritten": rewritten,
        "per_tenant": per_tenant,
    }
