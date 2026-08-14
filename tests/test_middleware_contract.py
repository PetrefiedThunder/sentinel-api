"""Consumer contract: agent-middleware-api (PetrefiedThunder/agent-middleware-api).

agent-middleware-api's human-approval gate and permit-request flow call this
API (see its `app/services/human_approval.py` and `docs/human-approval-gate.md`)
and depend on the exact semantics pinned here. A change that fails one of
these tests is a BREAKING CHANGE for that consumer even though no code is
shared — coordinate before shipping it.

Pinned semantics:

1. `POST /v1/approvals` dedups on (tenant, `Idempotency-Key`): replaying the
   same key + body returns the original approval verbatim without re-running
   the handler (the middleware retries lost responses under a deterministic
   key and must get the same approval back, not a second human page).
2. Same key + different body -> 409 (the middleware treats this as fail-closed
   proof that a retry was tampered with).
3. Approvals have NO server-side expiry: a timed-out approval stays "pending"
   forever. The middleware enforces expiry locally from `timeout_seconds` and
   assumes this API never flips state on its own.
4. `timeout_seconds` accepts exactly 1..86400.
5. `GET /v1/approvals/{id}/wait` accepts `timeout` of exactly 1..300 seconds
   and returns the still-pending approval on timeout (not an error).

Deeper coverage of the idempotency machinery itself lives in
tests/test_idempotency_replay.py, test_idempotency_race.py, and
test_idempotency_ttl.py; this file is intentionally the thin, named contract.
"""

import datetime as dt

import pytest
from sqlalchemy import func, select, update
from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.models import Approval

PAYLOAD = {
    "function_name": "governed_invoke",
    "arguments": {"tool": "send_wire", "request_hash": "sha256:abc123"},
    "risk_level": "high",
    "approvers": ["mailto:approver@example.com"],
    "timeout_seconds": 300,
}


@pytest.fixture
def no_notifications(monkeypatch):
    """Silence + count notification dispatches (replays must not re-notify)."""
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


def test_replay_same_key_returns_original_approval(no_notifications):
    """Contract #1: middleware retry under the same deterministic key must get
    the original approval back — same id, one row, one human notification."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "mw-invoke-1"}
            )
            replay = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "mw-invoke-1"}
            )
        assert first.status_code == 200
        assert replay.json() == first.json()
        assert _count_approvals(session) == 1
        assert len(no_notifications) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_changed_body_under_same_key_conflicts(no_notifications):
    """Contract #2: a mutated request under an accepted key fails closed (409)."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        mutated = {**PAYLOAD, "arguments": {"tool": "send_wire", "request_hash": "sha256:EVIL"}}
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "mw-invoke-2"}
            )
            conflict = client.post(
                "/v1/approvals", json=mutated, headers={"Idempotency-Key": "mw-invoke-2"}
            )
        assert first.status_code == 200
        assert conflict.status_code == 409
        assert _count_approvals(session) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_timed_out_approval_stays_pending_server_side(no_notifications):
    """Contract #3: no server-side expiry. Long after timeout_seconds has
    elapsed, the approval still reads "pending" — the middleware owns expiry."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            created = client.post(
                "/v1/approvals",
                json={**PAYLOAD, "timeout_seconds": 1},
                headers={"Idempotency-Key": "mw-invoke-3"},
            )
            action_id = created.json()["action_id"]

            # Backdate creation two days — far beyond timeout_seconds=1.
            run(
                session.execute(
                    update(Approval)
                    .where(Approval.id == action_id)
                    .values(created_at=dt.datetime.utcnow() - dt.timedelta(days=2))
                )
            )
            run(session.commit())

            fetched = client.get(f"/v1/approvals/{action_id}")
            assert fetched.status_code == 200
            assert fetched.json()["decision"] == "pending"
            assert fetched.json()["status"] == "pending"
    finally:
        run(session.close())
        run(engine.dispose())


def test_timeout_seconds_bounds_are_1_to_86400(no_notifications):
    """Contract #4: the middleware clamps to these exact bounds before sending."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            for bad in (0, 86401):
                r = client.post("/v1/approvals", json={**PAYLOAD, "timeout_seconds": bad})
                assert r.status_code == 422, f"timeout_seconds={bad} should be rejected"
            for good in (1, 86400):
                r = client.post("/v1/approvals", json={**PAYLOAD, "timeout_seconds": good})
                assert r.status_code == 200, f"timeout_seconds={good} should be accepted"
    finally:
        run(session.close())
        run(engine.dispose())


def test_wait_timeout_bounds_and_pending_timeout_shape(no_notifications):
    """Contract #5: /wait accepts timeout 1..300; on timeout it returns the
    still-pending approval body (200), never an error the middleware would
    misread as Sentinel being down."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            created = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "mw-invoke-4"}
            )
            action_id = created.json()["action_id"]

            for bad in (0, 301):
                r = client.get(f"/v1/approvals/{action_id}/wait", params={"timeout": bad})
                assert r.status_code == 422, f"wait timeout={bad} should be rejected"

            waited = client.get(f"/v1/approvals/{action_id}/wait", params={"timeout": 1})
            assert waited.status_code == 200
            assert waited.json()["decision"] == "pending"
    finally:
        run(session.close())
        run(engine.dispose())
