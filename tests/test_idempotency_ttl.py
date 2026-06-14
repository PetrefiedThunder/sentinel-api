"""Stale in-progress claim recovery (TTL takeover) for the Idempotency-Key layer.

Companion to tests/test_idempotency_race.py (the concurrent claim-first race)
and tests/test_idempotency_replay.py (sequential retry-after-response). This
file covers the abandoned-claim edge closed by the staleness TTL in
`app.services.idempotency`:

The claim-first design reserves an IdempotencyKey row with response_status=0
(_IN_PROGRESS) before running the handler, then stores the real response. If the
process CRASHES between claiming and storing, the row would otherwise sit
in-progress forever — every retry of that key polls, times out, and gets the
degraded 409 permanently (one bricked key).

The fix: when a retry encounters an in-progress row whose `created_at` is older
than IDEMPOTENCY_INPROGRESS_TTL_SECONDS, the prior claim is treated as abandoned
and the retry TAKES IT OVER — re-runs the handler and stores the real response,
exactly as if the key were fresh. A fresh in-progress row (within the TTL) still
follows the degraded poll/409 path so a genuinely-running winner is never
clobbered. The takeover is a single-winner conditional UPDATE.

SQLite (the test engine) can't exhibit true thread concurrency, so we wedge a
stale row deterministically and drive each branch directly.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.config import settings
from app.models import Approval, IdempotencyKey
from app.services.idempotency import (
    _IN_PROGRESS,
    _hash_body,
    _try_takeover_stale_claim,
    _utcnow,
    run_with_idempotency,
)

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


def _wedge_in_progress(session, key: str, *, age_seconds: float, request_hash=None):
    """Insert an in-progress IdempotencyKey row whose created_at is `age_seconds`
    in the past — simulating a claim whose owner has not yet stored a response."""
    row = IdempotencyKey(
        tenant_id=TENANT_ID,
        idempotency_key=key,
        method="POST",
        path="/v1/approvals",
        request_hash=request_hash if request_hash is not None else _hash_body(PAYLOAD),
        response_status=_IN_PROGRESS,
        response_body={},
        created_at=_utcnow() - timedelta(seconds=age_seconds),
    )
    session.add(row)
    run(session.commit())
    return row


def test_stale_in_progress_row_recovers_via_handler(no_notifications):
    """A wedged STALE in-progress row (created_at older than the TTL) must
    RECOVER: the next same-key request runs the handler, returns the real
    response (NOT a 409), and the row ends with the real status/body."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(
            session,
            "stale-key",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )

        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "stale-key"}
            )

        assert resp.status_code == 200
        # Real response, not the degraded 409.
        body = resp.json()
        assert "id" in body and body["id"].startswith("act_")
        # The handler actually ran: exactly one Approval and one notification.
        assert _count_approvals(session) == 1
        assert len(no_notifications) == 1

        # The wedged row now carries the real response, no longer in-progress.
        run(session.commit())
        row = run(session.get(IdempotencyKey, (TENANT_ID, "stale-key")))
        run(session.refresh(row))
        assert row.response_status == 200
        assert row.response_body["id"] == body["id"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_fresh_in_progress_row_still_degrades_409(no_notifications):
    """A FRESH in-progress row (created_at = now, well within the TTL) is a
    genuinely-running winner: the retry must NOT take over. It polls briefly and
    returns the degraded 409, creating nothing."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(session, "fresh-key", age_seconds=0)

        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "fresh-key"}
            )

        assert resp.status_code == 409
        assert "in progress" in resp.json()["detail"].lower()
        # No premature takeover: nothing created, row still in-progress.
        assert _count_approvals(session) == 0
        assert len(no_notifications) == 0
        row = run(session.get(IdempotencyKey, (TENANT_ID, "fresh-key")))
        run(session.refresh(row))
        assert row.response_status == _IN_PROGRESS
    finally:
        run(session.close())
        run(engine.dispose())


def test_takeover_is_single_winner(no_notifications):
    """The WHERE-guarded conditional UPDATE is single-winner: the first takeover
    of a stale row affects exactly 1 row (and bumps created_at past the cutoff);
    a second concurrent takeover with the same cutoff affects 0 rows."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(
            session,
            "contended-key",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )
        cutoff = _utcnow() - timedelta(seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS)

        first = run(
            _try_takeover_stale_claim(
                session, tenant_id=TENANT_ID, idempotency_key="contended-key", cutoff=cutoff
            )
        )
        run(session.commit())
        second = run(
            _try_takeover_stale_claim(
                session, tenant_id=TENANT_ID, idempotency_key="contended-key", cutoff=cutoff
            )
        )

        assert first is True
        assert second is False
    finally:
        run(session.close())
        run(engine.dispose())


def test_stale_takeover_preserves_status_code_201(no_notifications):
    """Takeover honors the endpoint's success status: recovering a stale claim
    with status_code=201 stores and returns 201, not a hardcoded 200."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(
            session,
            "stale-201",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )

        async def handler():
            return {"id": "act_recovered", "ok": True}

        from starlette.responses import JSONResponse as _JSONResponse

        result = run(
            run_with_idempotency(
                session,
                tenant_id=TENANT_ID,
                idempotency_key="stale-201",
                method="POST",
                path="/v1/approvals",
                request_body=PAYLOAD,
                handler=handler,
                status_code=201,
            )
        )

        assert isinstance(result, _JSONResponse)
        assert result.status_code == 201
        row = run(session.get(IdempotencyKey, (TENANT_ID, "stale-201")))
        run(session.refresh(row))
        assert row.response_status == 201
        assert row.response_body["id"] == "act_recovered"
    finally:
        run(session.close())
        run(engine.dispose())


def test_stale_takeover_returns_plain_dict_on_200(no_notifications):
    """Takeover with the default status_code (200) returns the plain encoded
    dict (not a JSONResponse) so the recovered response is byte-for-byte
    identical to a later replay — same contract as a fresh 200 claim."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(
            session,
            "stale-200",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )

        async def handler():
            return {"id": "act_recovered_200", "ok": True}

        result = run(
            run_with_idempotency(
                session,
                tenant_id=TENANT_ID,
                idempotency_key="stale-200",
                method="POST",
                path="/v1/approvals",
                request_body=PAYLOAD,
                handler=handler,
            )
        )

        # Plain dict on the 200 path (not a JSONResponse).
        assert result == {"id": "act_recovered_200", "ok": True}
        row = run(session.get(IdempotencyKey, (TENANT_ID, "stale-200")))
        run(session.refresh(row))
        assert row.response_status == 200
        assert row.response_body["id"] == "act_recovered_200"
    finally:
        run(session.close())
        run(engine.dispose())


def test_stale_takeover_body_mismatch_still_conflicts(no_notifications):
    """The body-hash guard runs BEFORE the staleness check: a stale in-progress
    row reused with a different payload is a 409 body-mismatch, never a takeover
    that silently re-runs with the new body."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(
            session,
            "stale-mismatch",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )
        other_payload = {**PAYLOAD, "arguments": {"amount": 9999, "to": "acct_999"}}

        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals",
                json=other_payload,
                headers={"Idempotency-Key": "stale-mismatch"},
            )

        assert resp.status_code == 409
        assert "different request body" in resp.json()["detail"].lower()
        assert _count_approvals(session) == 0
        assert len(no_notifications) == 0
    finally:
        run(session.close())
        run(engine.dispose())


def test_lost_takeover_falls_back_to_poll(no_notifications):
    """If this request loses the takeover race (the conditional UPDATE matches 0
    rows because a concurrent retry already re-claimed the stale row), it must
    fall back to the poll/replay path rather than running the handler."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        _wedge_in_progress(
            session,
            "lost-key",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )

        handler_calls = {"n": 0}

        async def handler():
            handler_calls["n"] += 1
            return {"id": "act_should_not_run"}

        # Force the takeover to lose (simulating a concurrent winner that already
        # re-claimed), so we fall through to poll -> degraded 409.
        import app.services.idempotency as idem

        async def lose(*a, **k):
            return False

        orig = idem._try_takeover_stale_claim
        idem._try_takeover_stale_claim = lose  # type: ignore[assignment]
        try:
            with pytest.raises(Exception) as exc:
                run(
                    run_with_idempotency(
                        session,
                        tenant_id=TENANT_ID,
                        idempotency_key="lost-key",
                        method="POST",
                        path="/v1/approvals",
                        request_body=PAYLOAD,
                        handler=handler,
                    )
                )
            assert getattr(exc.value, "status_code", None) == 409
        finally:
            idem._try_takeover_stale_claim = orig  # type: ignore[assignment]

        # Loser never ran the handler.
        assert handler_calls["n"] == 0
    finally:
        run(session.close())
        run(engine.dispose())
