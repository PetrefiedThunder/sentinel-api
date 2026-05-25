from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tenant
from app.db import get_db
from app.models import Tenant
from app.schemas import ApproverContactCreate
from app.services.contacts import (
    create_or_reactivate_sms_contact,
    list_contacts,
    revoke_contact,
    serialize_contact,
)

router = APIRouter()


@router.post("")
async def create_contact(
    payload: ApproverContactCreate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    if not payload.consent_attested:
        raise HTTPException(400, "SMS consent must be explicitly attested")
    contact = await create_or_reactivate_sms_contact(
        db,
        tenant.id,
        payload.phone_number,
        payload.display_name,
        payload.consent_source,
        payload.consent_note,
    )
    return serialize_contact(contact)


@router.get("")
async def list_approver_contacts(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    return [serialize_contact(contact) for contact in await list_contacts(db, tenant.id)]


@router.delete("/{contact_id}")
async def delete_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    contact = await revoke_contact(db, tenant.id, contact_id)
    if not contact:
        raise HTTPException(404, "Not found")
    return serialize_contact(contact)
