import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Approval, Tenant
from app.schemas import ApprovalCreate, DecisionRequest, TokenDecisionRequest
from app.services.approval_service import create_approval
from app.services.approval_tokens import InvalidApprovalToken, verify_decision_token
from app.services.audit_log import append_audit_event
from app.services.contacts import find_active_sms_contact, sms_approver_phone
from app.services.decision_bus import bus, notify_decision
from app.services.idempotency import run_with_idempotency
from app.services.pagination import paginate_stmt
from app.services.webhooks import dispatch_approval_webhook

router = APIRouter()


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def _serialize(a: Approval) -> dict:
    return {
        "action_id": a.id,
        "id": a.id,
        "tenant_id": a.tenant_id,
        "function_name": a.function_name,
        "arguments": a.arguments,
        "risk_level": a.risk_level,
        "approvers": a.approvers,
        "timeout_seconds": a.timeout_seconds,
        "decision": a.decision,
        "status": a.decision,
        "decided_by": a.decided_by,
        "decided_at": a.decided_at,
        "reason": a.reason,
        "created_at": a.created_at,
    }


@router.post("")
async def create(
    payload: ApprovalCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create an approval. Pass `Idempotency-Key: <opaque>` to make retries
    safe — the same key replays the original response without firing
    duplicate emails or creating duplicate rows."""

    async def _do_create() -> dict:
        for approver in payload.approvers:
            phone = sms_approver_phone(approver)
            if phone and not await find_active_sms_contact(db, tenant.id, phone):
                raise HTTPException(
                    400, "SMS approver requires active SMS consent contact"
                )
        approval = await create_approval(
            db, tenant, payload, background_tasks=background_tasks
        )
        return {
            "action_id": approval.id,
            "status": approval.decision,
            **_serialize(approval),
        }

    return await run_with_idempotency(
        db,
        tenant_id=tenant.id,
        idempotency_key=idempotency_key,
        method="POST",
        path="/v1/approvals",
        request_body=payload.model_dump(),
        handler=_do_create,
    )


@router.get("")
async def list_approvals(
    status: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    cursor: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """List approvals.

    Backward-compatible: with no `limit` and no `cursor`, returns the legacy
    top-200 bare array. With either present, returns the cursor-paginated
    envelope {data, has_more, next_cursor}.
    """
    base = select(Approval).where(Approval.tenant_id == tenant.id)
    if status:
        base = base.where(Approval.decision == status)

    if limit is None and cursor is None:
        # Legacy shape — don't break existing SDK clients
        stmt = base.order_by(Approval.created_at.desc(), Approval.id.desc()).limit(200)
        result = await db.execute(stmt)
        return [_serialize(a) for a in result.scalars().all()]

    page = await paginate_stmt(db, base, Approval, limit=limit or 50, cursor=cursor)
    return {
        "data": [_serialize(a) for a in page.items],
        "has_more": page.has_more,
        "next_cursor": page.next_cursor,
    }


@router.get("/{action_id}/wait")
async def wait_for_decision(
    action_id: str,
    timeout: float = Query(30, ge=1, le=300, description="Seconds to wait for a decision"),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Long-poll for a decision. Uses Postgres LISTEN/NOTIFY for sub-100ms
    detection, with a 100ms DB fallback poll to handle missed notifications.
    """
    approval = await db.get(Approval, action_id)
    if not approval or approval.tenant_id != tenant.id:
        raise HTTPException(404, "Not found")
    if approval.decision != "pending":
        return _serialize(approval)

    deadline = asyncio.get_event_loop().time() + timeout
    poll_interval = 0.1
    # Race: NOTIFY-wait against a poll loop. Whichever wakes first wins.
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            return _serialize(approval)
        wait_window = min(remaining, 5.0)  # cap each NOTIFY-wait at 5s
        notify_task = asyncio.create_task(bus.wait_for(action_id, wait_window))
        poll_task = asyncio.create_task(asyncio.sleep(poll_interval))
        done, pending = await asyncio.wait(
            {notify_task, poll_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        await db.refresh(approval)
        if approval.decision != "pending":
            return _serialize(approval)


@router.get("/{action_id}")
async def get_approval(
    action_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    approval = await db.get(Approval, action_id)
    if not approval or approval.tenant_id != tenant.id:
        raise HTTPException(404, "Not found")
    return _serialize(approval)


@router.post("/{action_id}/decision")
async def decide(
    action_id: str,
    payload: DecisionRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    approval = await db.get(Approval, action_id)
    if not approval or approval.tenant_id != tenant.id:
        raise HTTPException(404, "Not found")
    if approval.decision != "pending":
        raise HTTPException(400, f"Already {approval.decision}")
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")
    approval.decision = payload.decision
    approval.decided_by = payload.decided_by
    approval.decided_at = _utcnow()
    approval.reason = payload.reason
    await db.commit()
    await db.refresh(approval)
    await append_audit_event(
        db, tenant.id, approval.id, f"decision:{payload.decision}"
    )
    await notify_decision(db, approval.id)
    await dispatch_approval_webhook(db, approval)
    return _serialize(approval)


@router.post("/{action_id}/token-decision")
async def decide_with_token(
    action_id: str,
    payload: TokenDecisionRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        decision = verify_decision_token(payload.token, action_id)
    except (InvalidApprovalToken, ValueError):
        raise HTTPException(401, "Invalid or expired approval token") from None

    approval = await db.get(Approval, action_id)
    if not approval:
        raise HTTPException(404, "Not found")
    if approval.decision != "pending":
        raise HTTPException(400, f"Already {approval.decision}")

    approval.decision = decision
    approval.decided_by = "signed_link"
    approval.decided_at = _utcnow()
    approval.reason = "Signed approval link"
    await db.commit()
    await db.refresh(approval)
    await append_audit_event(
        db, approval.tenant_id, approval.id, f"decision:{decision}"
    )
    await notify_decision(db, approval.id)
    await dispatch_approval_webhook(db, approval)
    return _serialize(approval)
