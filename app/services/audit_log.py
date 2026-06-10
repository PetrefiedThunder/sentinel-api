import hashlib
import json

from sqlalchemy import desc, select, text

from app.models import AuditEvent


def _compute_hash(prev_hash, payload):
    serialized = json.dumps(payload, sort_keys=True, default=str)
    data = (prev_hash or "") + serialized
    return hashlib.sha256(data.encode()).hexdigest()


async def append_audit_event(db, tenant_id, action_id, execution_result, error=None):
    # Serialize concurrent appends per tenant. Without this, two simultaneous
    # appends both read the same "previous" event and fork the chain — found
    # in production by GET /v1/audit-events/verify on 2026-06-10 (two forks
    # left by the 5-way-concurrent approval test). The Postgres advisory lock
    # is held until the surrounding transaction commits; sqlite (tests) is
    # single-writer so the lock is unnecessary there.
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:tid))"),
            {"tid": tenant_id},
        )

    result = await db.execute(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant_id)
        # id tiebreak matters: verify walks (created_at asc, id asc), so the
        # chain head must be the max of that same ordering.
        .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id))
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
