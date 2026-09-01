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

Concurrency (claim-first)
-------------------------
Two requests can arrive with the SAME (tenant_id, idempotency_key) close
enough that both miss the initial lookup. We close that race the same way the
decision-nonce path does (app/services/nonce_store.py): let the database's
primary-key constraint pick a single winner.

Before running the handler we CLAIM the (tenant, key) row — insert a row with
an in-progress marker and flush it. The flush either succeeds (we own the key,
proceed to run the handler exactly once) or raises IntegrityError (a concurrent
request already claimed it; we never run the handler, never create a duplicate
Approval — we replay the winner's stored response instead).

The winner claims, runs the handler, stores its real response, and commits all
handler writes plus the completed claim atomically. A crash before that commit
rolls everything back. A loser that arrives while the winner is running polls
briefly for the stored response and replays it. A committed in-progress claim
from an older deployment has an indeterminate outcome and fails closed with
409; re-running it could duplicate an already-committed side effect.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import IdempotencyKey


def _utcnow() -> datetime:
    """Naive UTC `now`, comparable to the naive `created_at` written by the
    model's `datetime.utcnow` default (mirrors app/services/contacts.py)."""
    return datetime.now(UTC).replace(tzinfo=None)


# Sentinel stored in `response_status` while the winner is still running its
# handler. A row in this state has been CLAIMED but its real response is not
# yet persisted. `response_status` is a valid HTTP status everywhere else, so 0
# (not a real HTTP status) unambiguously means "in progress".
_IN_PROGRESS = 0

# Bounded poll for a concurrent winner to publish its stored response before we
# give up and return the degraded 409. Total wait ≈ attempts * delay.
_POLL_ATTEMPTS = 5
_POLL_DELAY_SECONDS = 0.05


def _hash_body(body: Any) -> str:
    """Stable hash of the request body for replay-mismatch detection."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay(row: IdempotencyKey) -> Any:
    """Return the stored response. Preserve the original status code: for the
    default 200 case return the plain dict (so the first response and the
    replay are byte-for-byte identical under FastAPI's default encoding); for a
    non-200 status (e.g. 201) return a JSONResponse carrying that status."""
    body = row.response_body
    if row.response_status == 200:
        return body
    return JSONResponse(content=body, status_code=row.response_status)


async def _replay_existing(
    db: AsyncSession,
    *,
    tenant_id: str,
    idempotency_key: str,
    body_hash: str,
    row: IdempotencyKey,
) -> Any:
    """Handle a row we found via the initial lookup: enforce the body-hash
    match, then either replay the stored response or — if the winner is still
    in progress — poll briefly and replay, else return the degraded 409.

    A stale committed claim has an indeterminate outcome: an older deployment
    may have committed the handler's side effect before storing the response.
    It fails closed rather than re-running a potentially destructive write."""
    if row.request_hash != body_hash:
        raise HTTPException(
            409,
            "Idempotency-Key was previously used with a different request body. "
            "Pick a new key or send the original payload exactly.",
        )
    if row.response_status != _IN_PROGRESS:
        return _replay(row)

    cutoff = _utcnow() - timedelta(seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS)
    if row.created_at < cutoff:
        raise HTTPException(
            409,
            "The original request outcome is indeterminate. Automatic re-execution "
            "is disabled to prevent duplicate side effects; reconcile the original "
            "request before using a new Idempotency-Key.",
        )

    return await _poll_for_response(db, tenant_id=tenant_id, idempotency_key=idempotency_key)


async def _run_and_store(
    db: AsyncSession,
    *,
    claim: IdempotencyKey,
    handler: Callable[[], Awaitable[dict]],
    status_code: int,
) -> Any:
    """Own an in-progress claim, run the handler exactly once, persist the real
    response, and return it (encoded so the first response matches the replay).

    The handler must not commit independently: its writes and the completed
    claim are one unit of work. Any failure rolls the whole unit back."""
    try:
        response = await handler()

        # The handler's response may contain non-JSON-native values (e.g.
        # datetime in `created_at`/`decided_at`). Encode before storing it in
        # the JSON response_body column and return the same encoded form so the
        # first response is byte-for-byte identical to later replays.
        encoded = jsonable_encoder(response)

        claim.response_status = status_code
        claim.response_body = encoded
        db.add(claim)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise

    if status_code == 200:
        return encoded
    return JSONResponse(content=encoded, status_code=status_code)


async def _poll_for_response(db: AsyncSession, *, tenant_id: str, idempotency_key: str) -> Any:
    """Wait briefly for a concurrent winner to publish its stored response.

    Returns the replayed response once available, or raises 409 if the winner
    has not stored a response within the bounded window (degraded fallback)."""
    for _ in range(_POLL_ATTEMPTS):
        await asyncio.sleep(_POLL_DELAY_SECONDS)
        # Drop any cached copy so we observe another transaction's commit.
        db.expire_all()
        row = await db.get(IdempotencyKey, (tenant_id, idempotency_key))
        if row is not None and row.response_status != _IN_PROGRESS:
            return _replay(row)
    raise HTTPException(
        409,
        "A request with this Idempotency-Key is already in progress. Retry shortly.",
    )


async def run_with_idempotency(
    db: AsyncSession,
    *,
    tenant_id: str,
    idempotency_key: str | None,
    method: str,
    path: str,
    request_body: Any,
    handler: Callable[[], Awaitable[dict]],
    status_code: int = 200,
) -> Any:
    """Run `handler()` exactly once per (tenant, idempotency_key).

    If the key is None or empty, skip the claim dance but still own the write
    transaction: commit a successful handler or roll it back on failure.
    Customers who don't pass the header get no idempotency guarantee.

    `status_code` is the success status the endpoint would return on a fresh
    run (default 200); it is stored and replayed so e.g. a 201-returning
    endpoint replays as 201.
    """
    if not idempotency_key:
        try:
            response = await handler()
            await db.commit()
            return response
        except BaseException:
            await db.rollback()
            raise

    if len(idempotency_key) > 255:
        raise HTTPException(400, "Idempotency-Key max length is 255 characters")

    body_hash = _hash_body(request_body)

    existing = await db.get(IdempotencyKey, (tenant_id, idempotency_key))
    if existing is not None:
        return await _replay_existing(
            db,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
            row=existing,
        )

    # First time we've seen this key — CLAIM it before doing any work. Insert an
    # in-progress row and flush so the DB's primary-key constraint adjudicates
    # concurrent claimants. If the flush raises IntegrityError, another request
    # won the claim; we must NOT run the handler (that would create a duplicate
    # Approval) — roll back and replay the winner's response instead.
    claim = IdempotencyKey(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        method=method.upper(),
        path=path,
        request_hash=body_hash,
        response_status=_IN_PROGRESS,
        response_body={},
    )
    db.add(claim)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        row = await db.get(IdempotencyKey, (tenant_id, idempotency_key))
        if row is None:
            # The winner rolled back its claim (handler errored) without
            # leaving a row. Surface the standard in-progress/degraded path.
            return await _poll_for_response(
                db, tenant_id=tenant_id, idempotency_key=idempotency_key
            )
        return await _replay_existing(
            db,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            body_hash=body_hash,
            row=row,
        )

    # We own the claim. Run the handler exactly once and atomically commit its
    # writes together with the completed response record.
    return await _run_and_store(db, claim=claim, handler=handler, status_code=status_code)
