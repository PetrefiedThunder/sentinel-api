"""Tests for optional Postgres read-replica wiring (app/db.py).

These assert the *wiring* — which engine/session a read resolves to — not live
replication. We point the "replica" at a throwaway URL and check that the
read engine/session are distinct objects targeting it when configured, and the
primary objects when not. The get_read_session dependency itself is exercised
against an in-memory SQLite session to prove it yields a usable session.

Module-level engine wiring in app/db.py reads settings at import time, so the
set/unset branches are exercised by reloading the module with the setting
patched. Every test restores the original setting and reloads back to the
unset baseline so the rest of the suite (which imports app.db, app.main and the
routers by reference) is unaffected.
"""

import importlib
from contextlib import suppress

from test_support import make_sqlite_session, run

import app.db as db
from app.config import settings
from app.db import _normalize_async_url


def _reload_db():
    importlib.reload(db)
    return db


def test_normalize_async_url_variants():
    # postgresql:// and postgres:// both get the asyncpg driver injected.
    assert _normalize_async_url("postgresql://u:p@h:5432/d") == (
        "postgresql+asyncpg://u:p@h:5432/d"
    )
    assert _normalize_async_url("postgres://u:p@h:5432/d") == ("postgresql+asyncpg://u:p@h:5432/d")
    # An already-async URL is passed through untouched.
    already = "postgresql+asyncpg://u:p@h:5432/d"
    assert _normalize_async_url(already) == already


def test_replica_unset_read_session_uses_primary():
    """READ_REPLICA_URL empty → read engine/session ARE the primary objects."""
    original = settings.READ_REPLICA_URL
    settings.READ_REPLICA_URL = ""
    try:
        _reload_db()
        assert db.read_engine is db.engine
        assert db.ReadSessionLocal is db.SessionLocal
    finally:
        settings.READ_REPLICA_URL = original
        _reload_db()


def test_replica_set_read_session_targets_replica():
    """READ_REPLICA_URL set → a distinct read engine pointed at the replica URL,
    with the asyncpg driver normalized in. Primary engine stays untouched."""
    original = settings.READ_REPLICA_URL
    settings.READ_REPLICA_URL = "postgresql://ro:ro@replica.internal:5432/sentinel"
    try:
        _reload_db()
        assert db.read_engine is not db.engine
        assert db.ReadSessionLocal is not db.SessionLocal
        assert db.read_engine.url.host == "replica.internal"
        assert db.read_engine.url.username == "ro"
        # plain postgresql:// was normalized to the async driver.
        assert db.read_engine.url.drivername == "postgresql+asyncpg"
        assert db.engine.url.host != "replica.internal"
    finally:
        settings.READ_REPLICA_URL = original
        _reload_db()


def test_get_read_session_yields_usable_session():
    """The get_read_session dependency yields a working AsyncSession.

    With the replica unset (default) it falls back to the primary engine; here
    we override the read sessionmaker with an in-memory SQLite one to prove the
    dependency yields a usable session and closes it cleanly.
    """
    engine, session, _tenant = run(make_sqlite_session())

    async def exercise():
        # Point the read sessionmaker at the sqlite engine, then drive the
        # actual get_read_session generator the same way FastAPI would.
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker

        db.ReadSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
        agen = db.get_read_session()
        s = await agen.__anext__()
        try:
            result = await s.execute(text("SELECT 1"))
            assert result.scalar() == 1
        finally:
            # Exhaust the generator so the `async with` cleanup runs.
            with suppress(StopAsyncIteration):
                await agen.__anext__()

    try:
        run(exercise())
    finally:
        run(session.close())
        run(engine.dispose())
        _reload_db()
