from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key
from app.db import get_db
from app.models import ApiKey, Tenant
from app.schemas import TenantSignup

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
