"""Concurrency correctness for the `Idempotency-Key` layer.

Companion to tests/test_idempotency_replay.py (which covers the sequential
retry-after-response semantics). This file covers the CONCURRENT same-key race
closed by the claim-first design in `app.services.idempotency`:

Two requests with the same (tenant_id, idempotency_key) can both miss the
initial lookup. The winner CLAIMS the row (insert + flush) before running the
handler; the loser's flush loses on the primary-key constraint and replays the
winner's response instead of running a second handler. Net effect: the handler
runs at most once, at most one Approval is created, both callers get the same
stored response — no 500, no leaked IntegrityError, no duplicate Approval.

SQLite (the test engine) can't exhibit true thread concurrency, so we exercise
each branch deterministically: pre-seed the conflicting row, or force the
flush to collide, rather than racing real threads.
"""

import asyncio

import pytest
from sqlalchemy import func, select
from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.models import Approval, IdempotencyKey
from app.services.idempotency import _IN_PROGRESS, run_with_idempotency

PAYLOAD = {
    "function_name": "transfer_funds",
    "arguments": {"amount": 1000, "to": "acct_123"},
    "risk_level": "high",
    "approvers": ["mailto:cfo@example.com"],
    "timeout_seconds": 300,
}


@pytest.fixture
def no_notifications(monkeypatch):
    calls: list = []

    async def _count(approval, tenant, db=None):
        calls.append(approval.id)

    monkeypatch.setattr("app.services.approval_service.dispatch_approval_notifications", _count)
    return calls


def _count_approvals(session) -> int:
    return run(
        session.scalar(
            select(func.count()).select_from(Approval).where(Approval.tenant_id == TENANT_ID)
        )
    )


def _seed_winner_row(session, key: str, *, body: dict, status: int = 200, request_hash=None):
    """Insert a completed IdempotencyKey row to simulate a concurrent winner
    that already claimed the key AND stored its response."""
    from app.services.idempotency import _hash_body

    row = IdempotencyKey(
        tenant_id=TENANT_ID,
        idempotency_key=key,
        method="POST",
        path="/v1/approvals",
        request_hash=request_hash if request_hash is not None else _hash_body(PAYLOAD),
        response_status=status,
        response_body=body,
    )
    session.add(row)
    run(session.commit())
    return row


def test_concurrent_winner_present_replays_not_duplicate(no_notifications):
    """Simulate a concurrent winner: an IdempotencyKey row already exists with a
    stored response. A same-key request must REPLAY it — no 500, no second
    Approval, no second notification."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        # Winner already created its Approval and stored its response.
        winner_approval = Approval(
            tenant_id=TENANT_ID,
            function_name="transfer_funds",
            arguments={"amount": 1000, "to": "acct_123"},
            risk_level="high",
            approvers=["mailto:cfo@example.com"],
            timeout_seconds=300,
        )
        session.add(winner_approval)
        run(session.commit())
        run(session.refresh(winner_approval))
        winner_body = {"id": winner_approval.id, "action_id": winner_approval.id}
        _seed_winner_row(session, "race-key", body=winner_body)

        assert _count_approvals(session) == 1

        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "race-key"}
            )

        assert resp.status_code == 200
        # Replayed the winner's response verbatim.
        assert resp.json()["id"] == winner_approval.id
        # No duplicate Approval; handler never ran for the loser.
        assert _count_approvals(session) == 1
        assert len(no_notifications) == 0
    finally:
        run(session.close())
        run(engine.dispose())


def test_in_progress_winner_returns_degraded_409(no_notifications):
    """A claimed-but-not-yet-stored winner (response_status == _IN_PROGRESS).
    After the bounded poll the response is still unavailable, so the loser gets
    the documented degraded 409 — never a 500, never a duplicate Approval."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        from app.services.idempotency import _hash_body

        session.add(
            IdempotencyKey(
                tenant_id=TENANT_ID,
                idempotency_key="inflight-key",
                method="POST",
                path="/v1/approvals",
                request_hash=_hash_body(PAYLOAD),
                response_status=_IN_PROGRESS,
                response_body={},
            )
        )
        run(session.commit())

        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "inflight-key"}
            )

        assert resp.status_code == 409
        assert "in progress" in resp.json()["detail"].lower()
        # Loser created nothing.
        assert _count_approvals(session) == 0
        assert len(no_notifications) == 0
    finally:
        run(session.close())
        run(engine.dispose())


def test_claim_flush_conflict_replays(no_notifications):
    """Drive the claim-first IntegrityError branch directly: the winner's row
    exists, but we hide it from the INITIAL lookup so the loser proceeds to
    claim. The claim flush then collides on the primary key, and the loser
    replays the winner's stored response instead of running the handler."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        winner_body = {"id": "act_winner", "action_id": "act_winner"}
        _seed_winner_row(session, "collide-key", body=winner_body)

        handler_calls = {"n": 0}

        async def handler():
            handler_calls["n"] += 1
            return {"id": "act_loser"}

        # Hide the existing row from the FIRST db.get only, forcing the claim
        # path; the flush then hits the real PK conflict.
        real_get = session.get
        state = {"first": True}

        async def fake_get(model, pk):
            if model is IdempotencyKey and state["first"]:
                state["first"] = False
                return None
            return await real_get(model, pk)

        session.get = fake_get  # type: ignore[method-assign]
        try:
            result = run(
                run_with_idempotency(
                    session,
                    tenant_id=TENANT_ID,
                    idempotency_key="collide-key",
                    method="POST",
                    path="/v1/approvals",
                    request_body=PAYLOAD,
                    handler=handler,
                )
            )
        finally:
            session.get = real_get  # type: ignore[method-assign]

        # Loser replayed the winner's body and never ran its handler.
        assert result == winner_body
        assert handler_calls["n"] == 0
    finally:
        run(session.close())
        run(engine.dispose())


def test_status_code_stored_and_replayed_201(no_notifications):
    """A 201-returning endpoint stores and replays 201, not a hardcoded 200.

    First run: run_with_idempotency(status_code=201) persists status 201 and
    returns a 201 JSONResponse. Replay (a pre-existing 201 row) also yields a
    201 with the same body."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        from starlette.responses import JSONResponse as _JSONResponse

        async def handler():
            return {"id": "act_created", "ok": True}

        first = run(
            run_with_idempotency(
                session,
                tenant_id=TENANT_ID,
                idempotency_key="created-key",
                method="POST",
                path="/v1/approvals",
                request_body=PAYLOAD,
                handler=handler,
                status_code=201,
            )
        )
        assert isinstance(first, _JSONResponse)
        assert first.status_code == 201

        row = run(session.get(IdempotencyKey, (TENANT_ID, "created-key")))
        assert row.response_status == 201
        assert row.response_body["id"] == "act_created"

        # Replay: should also be a 201 JSONResponse with the same body.
        replay = run(
            run_with_idempotency(
                session,
                tenant_id=TENANT_ID,
                idempotency_key="created-key",
                method="POST",
                path="/v1/approvals",
                request_body=PAYLOAD,
                handler=handler,
                status_code=201,
            )
        )
        assert isinstance(replay, _JSONResponse)
        assert replay.status_code == 201
    finally:
        run(session.close())
        run(engine.dispose())


def test_overlength_key_rejected(no_notifications):
    """Keys longer than 255 chars are rejected before any DB work."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals",
                json=PAYLOAD,
                headers={"Idempotency-Key": "x" * 256},
            )
        assert resp.status_code == 400
        assert "max length" in resp.json()["detail"].lower()
        assert _count_approvals(session) == 0
    finally:
        run(session.close())
        run(engine.dispose())


def test_claim_conflict_with_no_persisted_row_degrades(no_notifications):
    """Defensive branch: the claim flush collides, but on re-fetch no row is
    found (the winner rolled its claim back after erroring). We fall through to
    the bounded poll, which then returns the degraded 409 rather than 500."""
    engine, session, tenant = run(make_sqlite_session())
    try:

        async def handler():
            return {"id": "act_loser"}

        # First db.get -> None (forces claim path). flush() -> raise a
        # simulated IntegrityError. Re-fetch after rollback -> None. Poll -> None
        # every tick -> degraded 409.
        from sqlalchemy.exc import IntegrityError as _IntegrityError

        real_flush = session.flush

        async def boom_flush(*a, **k):
            raise _IntegrityError("simulated", None, Exception("dup"))

        real_get = session.get

        async def always_missing_get(model, pk):
            if model is IdempotencyKey:
                return None
            return await real_get(model, pk)

        real_rollback = session.rollback

        async def noop_rollback():
            await real_rollback()

        session.flush = boom_flush  # type: ignore[method-assign]
        session.get = always_missing_get  # type: ignore[method-assign]
        session.rollback = noop_rollback  # type: ignore[method-assign]
        try:
            with pytest.raises(Exception) as exc:
                run(
                    run_with_idempotency(
                        session,
                        tenant_id=TENANT_ID,
                        idempotency_key="ghost-key",
                        method="POST",
                        path="/v1/approvals",
                        request_body=PAYLOAD,
                        handler=handler,
                    )
                )
            assert getattr(exc.value, "status_code", None) == 409
        finally:
            session.flush = real_flush  # type: ignore[method-assign]
            session.get = real_get  # type: ignore[method-assign]
            session.rollback = real_rollback  # type: ignore[method-assign]
    finally:
        run(session.close())
        run(engine.dispose())


def test_poll_replays_once_winner_publishes(no_notifications):
    """The in-progress poll loop resolves: a winner row that starts in-progress
    and is updated to its real response mid-poll is replayed (not 409).

    We monkeypatch the poll's sleep to flip the row from in-progress to stored
    on the first tick, deterministically exercising the resolve branch."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        from app.services import idempotency as idem
        from app.services.idempotency import _hash_body

        session.add(
            IdempotencyKey(
                tenant_id=TENANT_ID,
                idempotency_key="resolving-key",
                method="POST",
                path="/v1/approvals",
                request_hash=_hash_body(PAYLOAD),
                response_status=_IN_PROGRESS,
                response_body={},
            )
        )
        run(session.commit())

        flipped = {"done": False}
        real_sleep = asyncio.sleep

        async def flipping_sleep(_seconds):
            await real_sleep(0)
            if not flipped["done"]:
                row = await session.get(IdempotencyKey, (TENANT_ID, "resolving-key"))
                row.response_status = 200
                row.response_body = {"id": "act_resolved"}
                session.add(row)
                await session.commit()
                flipped["done"] = True

        orig = idem.asyncio.sleep
        idem.asyncio.sleep = flipping_sleep  # type: ignore[assignment]
        try:
            result = run(
                run_with_idempotency(
                    session,
                    tenant_id=TENANT_ID,
                    idempotency_key="resolving-key",
                    method="POST",
                    path="/v1/approvals",
                    request_body=PAYLOAD,
                    handler=lambda: (_ for _ in ()).throw(
                        AssertionError("handler must not run on replay")
                    ),
                )
            )
        finally:
            idem.asyncio.sleep = orig  # type: ignore[assignment]

        assert result == {"id": "act_resolved"}
    finally:
        run(session.close())
        run(engine.dispose())
