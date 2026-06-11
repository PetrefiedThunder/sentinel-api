"""Server-side nonce tracking for signed decision tokens.

A decision token is single-use: once it successfully records a decision,
the SHA-256 hash of the token is persisted in `consumed_decision_nonces`
(same transaction as the decision itself). Any later request presenting
the same token is rejected, even across process restarts and even if the
approval's state were ever reset — the store is the database, not memory.

We deliberately hash the presented token rather than embedding a nonce in
the token payload: it requires no token-format change (in-flight links
keep working) and the raw token is never written to the database.
"""

from __future__ import annotations

import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ConsumedDecisionNonce


def token_nonce(token: str) -> str:
    """Stable server-side identifier for a presented token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def is_nonce_consumed(db: AsyncSession, nonce: str) -> bool:
    return await db.get(ConsumedDecisionNonce, nonce) is not None


def mark_nonce_consumed(db: AsyncSession, nonce: str, action_id: str) -> None:
    """Stage the consumed-nonce row. The caller commits it in the same
    transaction as the decision, so the two can never diverge. A concurrent
    consumer of the same token loses on the primary-key constraint."""
    db.add(ConsumedDecisionNonce(nonce=nonce, action_id=action_id))
