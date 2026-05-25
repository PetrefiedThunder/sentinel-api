"""In-process pub/sub for approval decisions, backed by Postgres LISTEN/NOTIFY.

Goal: when a decision is recorded, every `/wait` request for that action_id
wakes up immediately instead of polling the DB.

One dedicated asyncpg connection per process holds a LISTEN on the
`approval_decisions` channel. Each `/wait` request registers an asyncio.Event
keyed by action_id, awaits it, and unregisters on exit. The NOTIFY handler
sets the Event for the matching action_id (if any waiter is registered).

If the listener connection is unavailable (e.g. local dev with sqlite), the
broker degrades to a no-op and `/wait` falls back to its 100ms DB poll.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "approval_decisions"


def _asyncpg_dsn() -> str:
    """Convert SQLAlchemy's `postgresql+asyncpg://...` URL into a plain DSN."""
    url = settings.DATABASE_URL
    return re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)


class DecisionBus:
    def __init__(self) -> None:
        self._waiters: dict[str, set[asyncio.Event]] = {}
        self._lock = asyncio.Lock()
        self._conn: Optional[asyncpg.Connection] = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        try:
            self._conn = await asyncpg.connect(dsn=_asyncpg_dsn(), timeout=10)
            await self._conn.add_listener(CHANNEL, self._on_notify)
            self._started = True
            logger.info("DecisionBus listening on Postgres channel %r", CHANNEL)
        except Exception as e:
            # Degrade gracefully — /wait will fall back to polling
            logger.warning("DecisionBus could not start LISTEN: %s", e)

    async def stop(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.remove_listener(CHANNEL, self._on_notify)
            except Exception:
                pass
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._started = False

    def _on_notify(self, _conn, _pid, _channel, payload) -> None:
        """asyncpg invokes this synchronously from its read loop."""
        action_id = (payload or "").strip()
        if not action_id:
            return
        events = self._waiters.get(action_id)
        if not events:
            return
        for ev in list(events):
            ev.set()

    async def wait_for(self, action_id: str, timeout: float) -> bool:
        """Block until a NOTIFY arrives for `action_id` or timeout. Returns True
        if a notify was received, False on timeout."""
        ev = asyncio.Event()
        async with self._lock:
            self._waiters.setdefault(action_id, set()).add(ev)
        try:
            try:
                await asyncio.wait_for(ev.wait(), timeout=timeout)
                return True
            except asyncio.TimeoutError:
                return False
        finally:
            async with self._lock:
                bucket = self._waiters.get(action_id)
                if bucket is not None:
                    bucket.discard(ev)
                    if not bucket:
                        self._waiters.pop(action_id, None)


bus = DecisionBus()


async def notify_decision(db, action_id: str) -> None:
    """Send a NOTIFY on the channel. Best-effort; safe to call after commit."""
    from sqlalchemy import text
    try:
        await db.execute(text("SELECT pg_notify(:c, :p)"), {"c": CHANNEL, "p": action_id})
        await db.commit()
    except Exception as e:
        logger.warning("pg_notify failed for %s: %s", action_id, e)
