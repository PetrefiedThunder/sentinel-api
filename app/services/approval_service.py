import asyncio

from app.models import Approval
from app.services.notifications import dispatch_approval_notifications


async def create_approval(db, tenant, payload):
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
    asyncio.create_task(dispatch_approval_notifications(approval, tenant))
    return approval
