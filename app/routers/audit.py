from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Approval, AuditEvent, Tenant
from app.schemas import AuditEventCreate
from app.services.audit_log import append_audit_event

router = APIRouter()


def _serialize(e: AuditEvent) -> dict:
    return {
        "id": e.id,
        "action_id": e.action_id,
        "execution_result": e.execution_result,
        "error": e.error,
        "prev_hash": e.prev_hash,
        "event_hash": e.event_hash,
        "created_at": e.created_at,
    }


@router.post("")
async def emit(
    payload: AuditEventCreate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    # Verify the action belongs to this tenant before recording an event for it
    approval = await db.get(Approval, payload.action_id)
    if not approval or approval.tenant_id != tenant.id:
        raise HTTPException(404, "Not found")
    event = await append_audit_event(
        db, tenant.id, payload.action_id, payload.execution_result, payload.error
    )
    return _serialize(event)


@router.get("")
async def list_events(
    action_id: str | None = Query(None, description="Filter to a single action_id"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    if action_id:
        stmt = stmt.where(AuditEvent.action_id == action_id)
    stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return [_serialize(e) for e in result.scalars().all()]
