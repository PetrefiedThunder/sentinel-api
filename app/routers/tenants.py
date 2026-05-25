from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key, get_current_tenant
from app.db import get_db
from app.models import ApiKey, Tenant
from app.schemas import TenantSettingsUpdate, TenantSignup, _is_supported_approver

router = APIRouter()

BLOCKED_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}


@router.post("/signup")
async def signup(payload: TenantSignup, db: AsyncSession = Depends(get_db)):
    if "@" not in payload.email:
        raise HTTPException(400, "Invalid email")
    domain = payload.email.split("@")[-1].lower()
    if domain in BLOCKED_DOMAINS:
        raise HTTPException(
            400, "Work email required (personal email domains not allowed)"
        )
    existing = await db.execute(select(Tenant).where(Tenant.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")
    tenant = Tenant(name=payload.name, email=payload.email)
    db.add(tenant)
    await db.flush()
    raw, prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        tenant_id=tenant.id, key_hash=key_hash, prefix=prefix, name="default"
    )
    db.add(api_key)
    await db.commit()
    return {"tenant_id": tenant.id, "api_key": raw}


def _serialize_tenant(t: Tenant) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "email": t.email,
        "default_approvers": t.default_approvers or [],
        "created_at": t.created_at,
    }


@router.get("/me")
async def get_me(tenant: Tenant = Depends(get_current_tenant)):
    """Current tenant settings (default approvers, name, email)."""
    return _serialize_tenant(tenant)


@router.patch("/me")
async def update_me(
    payload: TenantSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Update mutable settings on the current tenant (currently: default_approvers)."""
    if payload.default_approvers is not None:
        normalized = [a.strip() for a in payload.default_approvers if isinstance(a, str) and a.strip()]
        for a in normalized:
            if not _is_supported_approver(a):
                raise HTTPException(
                    400,
                    f"Invalid approver '{a}'. Use email, 'mailto:...', or 'sms:+1...'."
                )
        tenant.default_approvers = normalized
    await db.commit()
    await db.refresh(tenant)
    return _serialize_tenant(tenant)
