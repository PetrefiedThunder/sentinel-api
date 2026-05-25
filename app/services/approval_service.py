from fastapi import HTTPException

from app.config import settings
from app.models import Approval
from app.services.notifications import dispatch_approval_notifications


def _resolve_approvers(caller_approvers: list, tenant) -> list:
    """If caller specified approvers, use them. Otherwise fall back first to
    the tenant's saved `default_approvers`, then to the global env-var
    `DEFAULT_APPROVERS`. Raises 400 if all three are empty."""
    if caller_approvers:
        return caller_approvers
    tenant_defaults = list(tenant.default_approvers or [])
    if tenant_defaults:
        return tenant_defaults
    global_defaults = settings.default_approvers_list
    if global_defaults:
        return global_defaults
    raise HTTPException(
        400,
        "approvers must be a non-empty list. Either pass `approvers` in the "
        "request, or set tenant default_approvers via PATCH /v1/tenants/me, "
        "or set DEFAULT_APPROVERS env on the server.",
    )


async def create_approval(db, tenant, payload, background_tasks=None):
    resolved_approvers = _resolve_approvers(payload.approvers, tenant)
    approval = Approval(
        tenant_id=tenant.id,
        function_name=payload.function_name,
        arguments=payload.arguments,
        risk_level=payload.risk_level,
        approvers=resolved_approvers,
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
