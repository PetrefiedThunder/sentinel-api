from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key, get_current_tenant
from app.db import get_db
from app.models import ApiKey, Tenant
from app.schemas import TenantSettingsUpdate, TenantSignup, _is_supported_approver
from app.services.onboarding import (
    InvalidOnboardingToken,
    send_recovery_email,
    send_welcome_email,
    verify_token,
)

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
async def signup(
    payload: TenantSignup,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
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
    await db.refresh(tenant)

    # Fire-and-forget welcome+verify email — never blocks signup.
    background.add_task(send_welcome_email, tenant, raw)

    return {"tenant_id": tenant.id, "api_key": raw}


# ── Email verification ────────────────────────────────────────────────
class VerifyPayload(BaseModel):
    token: str


@router.post("/verify-email")
async def verify_email(payload: VerifyPayload, db: AsyncSession = Depends(get_db)):
    try:
        tenant_id = verify_token(payload.token, expected_purpose="verify")
    except InvalidOnboardingToken as e:
        raise HTTPException(400, f"Invalid or expired verification link: {e}") from e
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "Workspace not found")
    if tenant.email_verified_at is None:
        tenant.email_verified_at = datetime.utcnow()
        await db.commit()
    return {
        "tenant_id": tenant.id,
        "email": tenant.email,
        "email_verified_at": tenant.email_verified_at,
    }


# ── API key recovery (magic-link, rotates key) ────────────────────────
class RecoverRequest(BaseModel):
    email: str


@router.post("/recover/request")
async def recover_request(
    payload: RecoverRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Step 1: user enters email → we email them a magic link.

    We always return 204, regardless of whether the email matches a real
    tenant, so this endpoint cannot be used to enumerate accounts.
    """
    email = (payload.email or "").strip().lower()
    if "@" not in email:
        # never reveal whether email exists — always pretend success
        return {"ok": True}
    result = await db.execute(select(Tenant).where(Tenant.email == email))
    tenant = result.scalar_one_or_none()
    if tenant is not None:
        background.add_task(send_recovery_email, tenant)
    return {"ok": True}


class RecoverExchange(BaseModel):
    token: str


@router.post("/recover/exchange")
async def recover_exchange(
    payload: RecoverExchange, db: AsyncSession = Depends(get_db)
):
    """Step 2: dashboard POSTs the token from the magic link. We revoke all
    existing keys and issue a brand-new one. The new key is returned ONCE."""
    try:
        tenant_id = verify_token(payload.token, expected_purpose="recover")
    except InvalidOnboardingToken as e:
        raise HTTPException(400, f"Invalid or expired recovery link: {e}") from e

    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(404, "Workspace not found")

    # revoke every active key on this tenant
    now = datetime.utcnow()
    existing = await db.execute(
        select(ApiKey).where(ApiKey.tenant_id == tenant.id, ApiKey.revoked_at.is_(None))
    )
    for k in existing.scalars():
        k.revoked_at = now

    # issue a new key
    raw, prefix, key_hash = generate_api_key()
    db.add(
        ApiKey(
            tenant_id=tenant.id, key_hash=key_hash, prefix=prefix, name="recovery"
        )
    )
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
