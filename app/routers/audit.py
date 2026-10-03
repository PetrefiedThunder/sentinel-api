import csv
import io
import json
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Approval, AuditEvent, Tenant
from app.schemas import AuditEventCreate

# _compute_hash is the canonical hash used when events are appended
# (see app/services/audit_log.py) — verification must replicate it exactly.
from app.services.audit_log import _compute_hash, append_audit_event
from app.services.pagination import paginate_stmt
from app.services.tsa import TSAError, timestamp_audit_event

router = APIRouter()
logger = structlog.get_logger(__name__)


def _serialize(e: AuditEvent) -> dict:
    return {
        "id": e.id,
        "action_id": e.action_id,
        "execution_result": e.execution_result,
        "error": e.error,
        "prev_hash": e.prev_hash,
        "event_hash": e.event_hash,
        "tsa_timestamp": e.tsa_timestamp,
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
    # Best-effort RFC 3161 timestamping: a no-op unless TSA_URL is configured,
    # and a TSA outage must never fail the audit write itself.
    try:
        await timestamp_audit_event(db, event)
    except TSAError:
        logger.warning("tsa_timestamp_failed", event_id=event.id, exc_info=True)
    return _serialize(event)


@router.get("")
async def list_events(
    action_id: str | None = Query(None, description="Filter to a single action_id"),
    limit: int | None = Query(None, ge=1, le=500),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """List audit events.

    Backward-compatible: no limit + no cursor → legacy top-100 bare array.
    Either present → cursor-paginated envelope {data, has_more, next_cursor}.
    """
    base = select(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    if action_id:
        base = base.where(AuditEvent.action_id == action_id)

    if limit is None and cursor is None:
        stmt = base.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(100)
        result = await db.execute(stmt)
        return [_serialize(e) for e in result.scalars().all()]

    page = await paginate_stmt(db, base, AuditEvent, limit=limit or 100, cursor=cursor)
    return {
        "data": [_serialize(e) for e in page.items],
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
    }


@router.get("/verify")
async def verify_chain(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Walk the tenant's full audit hash chain and prove tamper-evidence.

    Recomputes each event's hash from its stored payload (same computation as
    app/services/audit_log.py) and checks the prev_hash linkage. Read-only.
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant.id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    valid = True
    first_invalid_event_id = None
    prev_event_hash = None

    for e in events:
        # Same payload shape append_audit_event hashes at write time.
        payload = {
            "action_id": e.action_id,
            "execution_result": e.execution_result,
            "error": e.error,
        }
        expected_hash = _compute_hash(e.prev_hash, payload)
        if e.event_hash != expected_hash or e.prev_hash != prev_event_hash:
            valid = False
            first_invalid_event_id = e.id
            break
        prev_event_hash = e.event_hash

    return {
        "valid": valid,
        "events_checked": len(events),
        "first_invalid_event_id": first_invalid_event_id,
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get(".csv")
async def export_csv(
    action_id: str | None = Query(None, description="Filter to a single action_id"),
    limit: int = Query(10_000, ge=1, le=100_000),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Stream audit events as CSV for offline analysis / compliance reviews.

    Customers ask for this constantly during procurement — they want to ingest
    the audit log into their own SIEM. Keep the column set stable; downstream
    parsers depend on the header row.
    """
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant.id)
    if action_id:
        stmt = stmt.where(AuditEvent.action_id == action_id)
    stmt = stmt.order_by(AuditEvent.created_at.asc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "action_id",
                "created_at_utc",
                "execution_result_json",
                "error",
                "prev_hash",
                "event_hash",
            ]
        )
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        for e in rows:
            error = e.error or ""
            # Escape only the CSV presentation; stored evidence and JSON stay exact.
            if error.lstrip().startswith(("=", "+", "-", "@")) or error.startswith(("\t", "\r", "\n")):
                error = "'" + error
            writer.writerow(
                [
                    e.id,
                    e.action_id,
                    e.created_at.isoformat() if e.created_at else "",
                    json.dumps(e.execution_result, default=str) if e.execution_result is not None else "",
                    error,
                    e.prev_hash or "",
                    e.event_hash or "",
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="audit-{tenant.id}.csv"',
        },
    )
