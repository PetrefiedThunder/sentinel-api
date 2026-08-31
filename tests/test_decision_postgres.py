"""Real PostgreSQL decision/audit races; opt-in safety matches idempotency tests."""

import asyncio
import json

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_idempotency_postgres import TENANT_A, TENANT_B
from test_idempotency_postgres import pg_sessions as pg_sessions

from app.config import settings
from app.models import Approval, AuditEvent, ConsumedDecisionNonce, Tenant
from app.routers import approvals, audit
from app.schemas import DecisionRequest, TokenDecisionRequest
from app.services import audit_log
from app.services.approval_tokens import create_decision_token
from app.services.nonce_store import token_nonce

ACTION = "act_decision_postgres"
OTHER_ACTION = "act_decision_other"


@pytest_asyncio.fixture
async def decision_db(pg_sessions, monkeypatch):
    # Extend this test's unique, guarded schema; never alter shared tables.
    async with pg_sessions() as setup:
        connection = await setup.connection()
        await connection.run_sync(
            lambda sync: AuditEvent.metadata.create_all(
                sync, tables=[AuditEvent.__table__, ConsumedDecisionNonce.__table__]
            )
        )
        setup.add_all(
            Approval(id=action_id, tenant_id=TENANT_A, function_name="pg_decision")
            for action_id in (ACTION, OTHER_ACTION)
        )
        await setup.commit()
    monkeypatch.setattr(settings, "JWT_SECRET", "synthetic-postgres-decision-test-secret-32-bytes")
    calls = {"notify": [], "webhook": []}

    async def notified(_db, action_id):
        state = await _state(pg_sessions, action_id)
        assert state["decision"] in {"approved", "rejected"}
        assert state["audit"] == [f"decision:{state['decision']}"]
        calls["notify"].append(action_id)

    async def webhook(_db, approval):
        state = await _state(pg_sessions, approval.id)
        assert state["decision"] == approval.decision
        assert state["audit"] == [f"decision:{approval.decision}"]
        calls["webhook"].append(approval.id)

    monkeypatch.setattr(approvals, "notify_decision", notified)
    monkeypatch.setattr(approvals, "dispatch_approval_webhook", webhook)
    return pg_sessions, calls


def _token(decision="approved", action_id=ACTION):
    return create_decision_token(action_id, decision, expires_in_seconds=300)


async def _decide(session, kind, *, decision="approved", action_id=ACTION, token=None):
    if kind == "token":
        return await approvals.decide_with_token(
            action_id, TokenDecisionRequest(token=token or _token(decision, action_id)), session
        )
    tenant = await session.get(Tenant, TENANT_A)
    return await approvals.decide(
        action_id, DecisionRequest(decision=decision, decided_by="pg_verifier"), session, tenant
    )


async def _state(sessions, action_id=ACTION):
    async with sessions() as observer:
        row = await observer.get(Approval, action_id)
        events = await observer.scalars(
            select(AuditEvent.execution_result).where(
                AuditEvent.action_id == action_id,
                AuditEvent.execution_result.like("decision:%"),
            )
        )
        nonces = await observer.scalars(
            select(ConsumedDecisionNonce.nonce).where(ConsumedDecisionNonce.action_id == action_id)
        )
        return {
            "decision": row.decision,
            "decided_by": row.decided_by,
            "decided_at": row.decided_at,
            "audit": list(events),
            "nonces": list(nonces),
        }


async def _assert_pending(sessions):
    assert await _state(sessions) == {
        "decision": "pending",
        "decided_by": None,
        "decided_at": None,
        "audit": [],
        "nonces": [],
    }


async def _blocked(observer, owner_pid, waiter_pid, waiter):
    assert owner_pid != waiter_pid
    async with asyncio.timeout(4):
        while True:
            blockers = await observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter_pid}
            )
            if owner_pid in blockers:
                print(
                    json.dumps(
                        {"owner_pid": owner_pid, "blocked_pid": waiter_pid, "blockers": blockers}
                    )
                )
                return
            assert not waiter.done(), "contender completed without the required database lock"


async def _settle(*tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    async with asyncio.timeout(6):
        await asyncio.gather(*tasks, return_exceptions=True)


async def _chain_valid(sessions, expected):
    async with sessions() as observer:
        tenant = await observer.get(Tenant, TENANT_A)
        result = await audit.verify_chain(observer, tenant)
        assert result["valid"] is True and result["events_checked"] == expected


@pytest.mark.parametrize(
    ("winner_kind", "loser_kind", "identical_token"),
    [
        ("api", "api", False),
        ("token", "token", False),
        ("api", "token", False),
        ("token", "api", False),
        ("token", "token", True),
    ],
)
async def test_conflicting_decisions_have_one_winner(
    decision_db, monkeypatch, winner_kind, loser_kind, identical_token
):
    sessions, calls = decision_db
    entered, release = asyncio.Event(), asyncio.Event()
    real_append = approvals.append_audit_event
    winning_token = _token()
    losing_token = winning_token if identical_token else _token("rejected")
    async with sessions() as winner, sessions() as loser, sessions() as observer:
        # Retain stale ORM objects so locking must also refresh cached state.
        stale = [await session.get(Approval, ACTION) for session in (winner, loser)]
        winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
        loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))

        async def hold_winner(db, *args, **kwargs):
            if db is winner:
                entered.set()
                await release.wait()
            return await real_append(db, *args, **kwargs)

        monkeypatch.setattr(approvals, "append_audit_event", hold_winner)
        first = asyncio.create_task(_decide(winner, winner_kind, token=winning_token))
        tasks = [first]
        try:
            async with asyncio.timeout(4):
                await entered.wait()
            await _assert_pending(sessions)
            second = asyncio.create_task(
                _decide(loser, loser_kind, decision="rejected", token=losing_token)
            )
            tasks.append(second)
            await _blocked(observer, winner_pid, loser_pid, second)
            release.set()
            async with asyncio.timeout(6):
                results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            release.set()
            await _settle(*tasks)
        assert results[0]["decision"] == "approved"
        assert isinstance(results[1], HTTPException)
        assert results[1].status_code == (409 if identical_token else 400)
        assert stale[1] is not None  # Keep the preloaded object alive through the losing request.
    state = await _state(sessions)
    assert state["decision"] == "approved" and state["audit"] == ["decision:approved"]
    assert state["nonces"] == ([token_nonce(winning_token)] if winner_kind == "token" else [])
    assert calls == {"notify": [ACTION], "webhook": [ACTION]}
    await _chain_valid(sessions, 1)


async def test_different_actions_serialize_one_tenant_audit_chain(decision_db, monkeypatch):
    sessions, calls = decision_db
    entered, release = asyncio.Event(), asyncio.Event()
    real_append = approvals.append_audit_event
    async with sessions() as first_db, sessions() as second_db, sessions() as observer:
        first_pid = await first_db.scalar(text("SELECT pg_backend_pid()"))
        second_pid = await second_db.scalar(text("SELECT pg_backend_pid()"))

        async def hold_after_append(db, *args, **kwargs):
            event = await real_append(db, *args, **kwargs)
            if db is first_db:
                entered.set()
                await release.wait()
            return event

        monkeypatch.setattr(approvals, "append_audit_event", hold_after_append)
        first = asyncio.create_task(_decide(first_db, "api"))
        tasks = [first]
        try:
            async with asyncio.timeout(4):
                await entered.wait()
            second = asyncio.create_task(_decide(second_db, "token", action_id=OTHER_ACTION))
            tasks.append(second)
            await _blocked(observer, first_pid, second_pid, second)
            release.set()
            async with asyncio.timeout(6):
                results = await asyncio.gather(*tasks)
        finally:
            release.set()
            await _settle(*tasks)
    assert [row["decision"] for row in results] == ["approved", "approved"]
    for dispatched_actions in calls.values():
        assert sorted(dispatched_actions) == sorted([ACTION, OTHER_ACTION])
    await _chain_valid(sessions, 2)


async def test_standalone_audit_does_not_deadlock_decision_row_lock(decision_db):
    """FOR UPDATE would invert advisory/FK-keyshare locks and deadlock here."""
    sessions, calls = decision_db
    async with sessions() as standalone, sessions() as decider, sessions() as observer:
        owner_pid = await standalone.scalar(text("SELECT pg_backend_pid()"))
        decider_pid = await decider.scalar(text("SELECT pg_backend_pid()"))
        await standalone.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:tid))"), {"tid": TENANT_A}
        )
        decision = asyncio.create_task(_decide(decider, "api"))
        tasks = [decision]
        try:
            await _blocked(observer, owner_pid, decider_pid, decision)
            # Real default-commit helper inserts an FK referencing the locked
            # approval while this connection still owns the tenant advisory lock.
            append = asyncio.create_task(
                audit_log.append_audit_event(standalone, TENANT_A, ACTION, "execution:observed")
            )
            tasks.append(append)
            async with asyncio.timeout(6):
                result, event = await asyncio.gather(*tasks)
        finally:
            await _settle(*tasks)
    assert result["decision"] == "approved" and event.execution_result == "execution:observed"
    assert calls == {"notify": [ACTION], "webhook": [ACTION]}
    await _chain_valid(sessions, 2)


@pytest.mark.parametrize("kind", ["api", "token"])
@pytest.mark.parametrize("fault", ["hash_error", "audit_constraint"])
async def test_audit_failure_rolls_back_decision_nonce_and_allows_retry(
    decision_db, monkeypatch, kind, fault
):
    sessions, calls = decision_db
    token = _token()

    def broken_hash(*_args):
        if fault == "hash_error":
            raise RuntimeError("injected audit hash failure")
        return None  # Real NOT NULL failure when the AuditEvent is flushed.

    async with sessions() as failed:
        with monkeypatch.context() as patch:
            patch.setattr(audit_log, "_compute_hash", broken_hash)
            with pytest.raises(RuntimeError if fault == "hash_error" else IntegrityError):
                await _decide(failed, kind, token=token)
        await _assert_pending(sessions)
        assert calls == {"notify": [], "webhook": []}
    async with sessions() as retry:
        assert (await _decide(retry, kind, token=token))["decision"] == "approved"
    state = await _state(sessions)
    assert state["audit"] == ["decision:approved"]
    assert state["nonces"] == ([token_nonce(token)] if kind == "token" else [])
    assert calls == {"notify": [ACTION], "webhook": [ACTION]}


@pytest.mark.parametrize("kind", ["api", "token"])
async def test_cancellation_after_audit_flush_rolls_back(decision_db, monkeypatch, kind):
    sessions, calls = decision_db
    entered, pause = asyncio.Event(), asyncio.Event()
    real_append = approvals.append_audit_event
    token = _token()

    async def pause_after_audit(*args, **kwargs):
        event = await real_append(*args, **kwargs)
        entered.set()
        await pause.wait()
        return event

    async with sessions() as failed:
        with monkeypatch.context() as patch:
            patch.setattr(approvals, "append_audit_event", pause_after_audit)
            task = asyncio.create_task(_decide(failed, kind, token=token))
            try:
                async with asyncio.timeout(4):
                    await entered.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    async with asyncio.timeout(6):
                        await task
            finally:
                await _settle(task)
        await _assert_pending(sessions)
        assert calls == {"notify": [], "webhook": []}
    async with sessions() as retry:
        assert (await _decide(retry, kind, token=token))["decision"] == "approved"
    assert calls == {"notify": [ACTION], "webhook": [ACTION]}


@pytest.mark.parametrize("kind", ["api", "token"])
async def test_cached_pending_approval_cannot_overwrite_committed_decision(decision_db, kind):
    sessions, calls = decision_db
    async with sessions() as stale_db, sessions() as winner:
        stale = await stale_db.get(Approval, ACTION)
        assert stale.decision == "pending"
        await _decide(winner, "api")
        with pytest.raises(HTTPException) as error:
            await _decide(stale_db, kind, decision="rejected")
        assert error.value.status_code == 400
    state = await _state(sessions)
    assert state["decision"] == "approved" and state["audit"] == ["decision:approved"]
    assert not state["nonces"]
    assert calls == {"notify": [ACTION], "webhook": [ACTION]}


async def test_cross_tenant_decision_rejected_even_with_cached_approval(decision_db):
    sessions, calls = decision_db
    async with sessions() as outsider:
        cached = await outsider.get(Approval, ACTION)
        assert cached.tenant_id == TENANT_A
        wrong_tenant = await outsider.get(Tenant, TENANT_B)
        with pytest.raises(HTTPException) as error:
            await approvals.decide(
                ACTION,
                DecisionRequest(decision="approved", decided_by="outsider"),
                outsider,
                wrong_tenant,
            )
        assert error.value.status_code == 404
    await _assert_pending(sessions)
    assert calls == {"notify": [], "webhook": []}


@pytest.mark.parametrize("kind", ["api", "token"])
async def test_error_after_successful_commit_keeps_complete_evidence(
    decision_db, monkeypatch, kind
):
    """Application fault after known successful commit, not lost network ACK."""
    sessions, calls = decision_db
    token = _token()
    async with sessions() as failed:
        real_commit = failed.commit

        async def commit_then_fail():
            await real_commit()
            raise RuntimeError("injected application error after successful commit")

        with monkeypatch.context() as patch:
            patch.setattr(failed, "commit", commit_then_fail)
            with pytest.raises(RuntimeError, match="after successful commit"):
                await _decide(failed, kind, token=token)
    state = await _state(sessions)
    assert state["decision"] == "approved" and state["audit"] == ["decision:approved"]
    assert state["nonces"] == ([token_nonce(token)] if kind == "token" else [])
    async with sessions() as retry:
        with pytest.raises(HTTPException) as error:
            await _decide(retry, kind, token=token)
        assert error.value.status_code == (409 if kind == "token" else 400)
    assert calls == {"notify": [], "webhook": []}
