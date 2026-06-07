import hashlib
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ApiKey, Tenant


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    raw = f"sk_live_{secrets.token_hex(32)}"
    prefix = raw[:11]
    return raw, prefix, hash_key(raw)


async def get_current_tenant(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    raw_key = authorization.split(" ", 1)[1].strip()
    key_hash = hash_key(raw_key)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    tenant = await db.get(Tenant, api_key.tenant_id)
    if not tenant:
        raise HTTPException(status_code=401, detail="Tenant not found")
    # Stamp tenant_id on every subsequent log line in this request
    from app.logging_setup import bind_request_context
    bind_request_context(tenant_id=tenant.id, api_key_id=api_key.id)
    return tenant
