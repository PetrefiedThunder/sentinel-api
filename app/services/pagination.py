"""Cursor pagination — Stripe-style opaque cursors over (created_at, id).

Encodes the last-seen row's (created_at, id) into a base64-url token. Decoding
filters strictly before that point, so pagination is stable even when new rows
are inserted between page fetches (no offset drift, no duplicates).

Usage in a router:

    from app.services.pagination import decode_cursor, encode_cursor, paginate_stmt

    page = await paginate_stmt(db, base_stmt, Model, limit=limit, cursor=cursor)
    return {"data": [serialize(x) for x in page.items],
            "has_more": page.has_more,
            "next_cursor": page.next_cursor}
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession


def encode_cursor(created_at: datetime, row_id: str) -> str:
    payload = {"c": created_at.isoformat(), "i": row_id}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        payload = json.loads(raw)
        return datetime.fromisoformat(payload["c"]), str(payload["i"])
    except Exception as e:  # noqa: BLE001 — any malformed cursor is a 400
        raise HTTPException(400, "Invalid pagination cursor") from e


@dataclass
class Page:
    items: list[Any]
    has_more: bool
    next_cursor: str | None


async def paginate_stmt(
    db: AsyncSession,
    base_stmt,
    model,
    *,
    limit: int,
    cursor: str | None,
) -> Page:
    """Apply descending (created_at, id) keyset pagination to `base_stmt`.

    `model` must have `.created_at` and `.id` columns. We fetch limit+1 rows
    to detect has_more without a second COUNT query.
    """
    stmt = base_stmt
    if cursor:
        c_created, c_id = decode_cursor(cursor)
        # Strictly "older than" the cursor in (created_at desc, id desc) order
        stmt = stmt.where(
            or_(
                model.created_at < c_created,
                and_(model.created_at == c_created, model.id < c_id),
            )
        )
    stmt = stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)

    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page(items=items, has_more=has_more, next_cursor=next_cursor)
