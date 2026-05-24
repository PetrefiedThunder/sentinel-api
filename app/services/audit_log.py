import hashlib
import json
from sqlalchemy import select, desc
from app.models import AuditEvent


def _compute_hash(prev_hash, payload):
    serialized = json.dumps(payload, sort_keys=True, default=str)
    data = (prev_hash or "") + serialized
    return hashlib.sha256(data.encode()).hexdigest()


async def append_audit_event(db, tenant_id, action_id, execution_result, error=None):
    result = await db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(desc(AuditEvent.created_at))
        .limit(1)
    )
    prev = result.scalar_one_or_none()
    prev_hash = prev.event_hash if prev else None

    payload = {
        "action_id": action_id,
        "execution_result": execution_result,
        "error": error,
    }
    event_hash = _compute_hash(prev_hash, payload)

    event = AuditEvent(
        tenant_id=tenant_id,
        action_id=action_id,
        execution_result=execution_result,
        error=error,
        prev_hash=prev_hash,
        event_hash=event_hash,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event

