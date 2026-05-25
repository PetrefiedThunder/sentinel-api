from app.models import Approval
from app.services.notifications import dispatch_approval_notifications


async def create_approval(db, tenant, payload, background_tasks=None):
    approval = Approval(
        tenant_id=tenant.id,
        function_name=payload.function_name,
        arguments=payload.arguments,
        risk_level=payload.risk_level,
        approvers=payload.approvers,
        timeout_seconds=payload.timeout_seconds,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    # Freeze a plain-data snapshot so background tasks don't touch a closed session.
    snapshot = type("ApprovalSnapshot", (), {
        "id": approval.id,
        "tenant_id": approval.tenant_id,
        "function_name": approval.function_name,
        "arguments": approval.arguments,
        "risk_level": approval.risk_level,
        "approvers": list(approval.approvers or []),
        "timeout_seconds": approval.timeout_seconds,
    })()
    if background_tasks is not None:
        background_tasks.add_task(dispatch_approval_notifications, snapshot, tenant)
    else:
        # Fallback for tests / callers without a request scope
        await dispatch_approval_notifications(snapshot, tenant)
    return approval
