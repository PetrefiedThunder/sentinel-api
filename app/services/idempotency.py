"""Idempotency-Key support — Stripe-style replay protection for writes.

Customer sends `Idempotency-Key: <opaque>` header on POST. If we've seen
that (tenant_id, idempotency_key) before:

  - Same request body  → return the stored response verbatim (200/201, no
                          DB writes, no notifications fired)
  - Different body     → 409 Conflict ("key was used with different payload")

If we haven't seen it: the handler runs normally and we record the response
to play back next time.

Why: networks retry. Without idempotency, an SDK that retries a flaky POST
can create two approval rows, fire two emails, and wedge the agent's
wait_for_decision() loop. With it, the second POST returns the original
approval's id and nothing else happens.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyKey


def _hash_body(body: Any) -> str:
    """Stable hash of the request body for replay-mismatch detection."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def run_with_idempotency(
    db: AsyncSession,
    *,
    tenant_id: str,
    idempotency_key: Optional[str],
    method: str,
    path: str,
    request_body: Any,
    handler: Callable[[], Awaitable[dict]],
) -> dict:
    """Run `handler()` exactly once per (tenant, idempotency_key).

    If the key is None or empty, skip the dance entirely and call the handler.
    Customers who don't pass the header get no idempotency guarantee.
    """
    if not idempotency_key:
        return await handler()

    if len(idempotency_key) > 255:
        raise HTTPException(400, "Idempotency-Key max length is 255 characters")

    body_hash = _hash_body(request_body)

    existing = await db.get(IdempotencyKey, (tenant_id, idempotency_key))
    if existing is not None:
        if existing.request_hash != body_hash:
            raise HTTPException(
                409,
                "Idempotency-Key was previously used with a different request body. "
                "Pick a new key or send the original payload exactly.",
            )
        # Replay — return the stored response. The handler is NOT called.
        return existing.response_body  # type: ignore[return-value]

    # First time we see this key. Run the handler, persist the result.
    response = await handler()

    db.add(
        IdempotencyKey(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            method=method.upper(),
            path=path,
            request_hash=body_hash,
            response_status=200,
            response_body=response,
        )
    )
    await db.commit()
    return response
