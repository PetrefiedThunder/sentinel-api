from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Approval, Tenant
from app.schemas import ApprovalCreate, DecisionRequest, TokenDecisionRequest
from app.services.approval_service import create_approval
from app.services.approval_tokens import InvalidApprovalToken, verify_decision_token
from app.services.audit_log import append_audit_event

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
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    approval = await create_approval(db, tenant, payload)
    return {"action_id": approval.id, "status": approval.decision, **_serialize(approval)}


@router.get("")
async def list_approvals(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    stmt = select(Approval).where(Approval.tenant_id == tenant.id)
    if status:
        stmt = stmt.where(Approval.decision == status)
    stmt = stmt.order_by(Approval.created_at.desc()).limit(200)
    result = await db.execute(stmt)
    return [_serialize(a) for a in result.scalars().all()]


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
        raise HTTPException(401, "Invalid or expired approval token")

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
    return _serialize(approval)
