from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Tenant
from app.schemas import AuditEventCreate
from app.services.audit_log import append_audit_event

router = APIRouter()


@router.post("")
async def emit(
    payload: AuditEventCreate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    event = await append_audit_event(
        db, tenant.id, payload.action_id, payload.execution_result, payload.error
    )
    return {
        "id": event.id,
        "action_id": event.action_id,
        "execution_result": event.execution_result,
        "error": event.error,
        "prev_hash": event.prev_hash,
        "event_hash": event.event_hash,
        "created_at": event.created_at,
    }
