"""Fail-closed handling for indeterminate Idempotency-Key outcomes.

The claim, approval row, and stored response must commit atomically. A crash
before that commit rolls all three back, so a retry can safely start fresh.

An already-committed ``response_status=0`` row is different: it can come from a
pre-atomicity deployment that committed the approval before storing its
response. Because the claim does not record the approval id, the server cannot
know whether replaying the handler would be the first execution or a duplicate.
Those stale claims therefore fail closed with 409 and never re-run the handler.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.config import settings
from app.models import Approval, IdempotencyKey, Tenant
from app.schemas import ApprovalCreate
from app.services.approval_service import create_approval
from app.services.idempotency import (
    _IN_PROGRESS,
    _hash_body,
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


def test_stale_in_progress_row_fails_closed(no_notifications):
    """A stale claim has an indeterminate outcome, so it must never re-run the
    write handler and risk a duplicate side effect."""
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

        assert resp.status_code == 409
        assert "indeterminate" in resp.json()["detail"].lower()
        assert _count_approvals(session) == 0
        assert len(no_notifications) == 0

        row = run(session.get(IdempotencyKey, (TENANT_ID, "stale-key")))
        run(session.refresh(row))
        assert row.response_status == _IN_PROGRESS
    finally:
        run(session.close())
        run(engine.dispose())


def test_stale_claim_with_committed_approval_does_not_duplicate(no_notifications):
    """Regression for the old post-commit crash window: if an approval may
    already exist, a stale claim fails closed instead of creating a second one."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        original = Approval(
            tenant_id=TENANT_ID,
            function_name=PAYLOAD["function_name"],
            arguments=PAYLOAD["arguments"],
            risk_level=PAYLOAD["risk_level"],
            approvers=PAYLOAD["approvers"],
            timeout_seconds=PAYLOAD["timeout_seconds"],
        )
        session.add(original)
        run(session.commit())
        _wedge_in_progress(
            session,
            "legacy-crash-key",
            age_seconds=settings.IDEMPOTENCY_INPROGRESS_TTL_SECONDS + 5,
        )

        with client_for(session, tenant) as client:
            resp = client.post(
                "/v1/approvals",
                json=PAYLOAD,
                headers={"Idempotency-Key": "legacy-crash-key"},
            )

        assert resp.status_code == 409
        assert "indeterminate" in resp.json()["detail"].lower()
        assert _count_approvals(session) == 1
        assert len(no_notifications) == 0
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


def test_stale_claim_body_mismatch_still_conflicts(no_notifications):
    """The body-hash guard runs BEFORE the staleness check: a stale in-progress
    row reused with a different payload is a 409 body-mismatch, never a retry
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


def test_crash_before_response_store_rolls_back_then_retry_succeeds(
    no_notifications, monkeypatch
):
    """Approval + claim + stored response are one transaction. A failure after
    the approval flush leaves no durable side effect; the retry creates one."""
    engine, session, tenant = run(make_sqlite_session())
    retry_session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        import app.services.idempotency as idem

        real_encoder = idem.jsonable_encoder

        def crash_after_handler(_response):
            raise RuntimeError("simulated process crash before final commit")

        monkeypatch.setattr(idem, "jsonable_encoder", crash_after_handler)
        with (
            pytest.raises(RuntimeError, match="simulated process crash"),
            client_for(session, tenant) as client,
        ):
            client.post(
                "/v1/approvals",
                json=PAYLOAD,
                headers={"Idempotency-Key": "atomic-crash-key"},
            )

        assert _count_approvals(session) == 0
        assert run(session.get(IdempotencyKey, (TENANT_ID, "atomic-crash-key"))) is None
        assert len(no_notifications) == 0

        # A real retry gets a fresh request/session, not the rolled-back ORM
        # identity map from the failed request.
        retry_tenant = run(retry_session.get(Tenant, TENANT_ID))
        monkeypatch.setattr(idem, "jsonable_encoder", real_encoder)
        with client_for(retry_session, retry_tenant) as client:
            retry = client.post(
                "/v1/approvals",
                json=PAYLOAD,
                headers={"Idempotency-Key": "atomic-crash-key"},
            )

        assert retry.status_code == 200
        assert _count_approvals(retry_session) == 1
        assert len(no_notifications) == 1
        row = run(retry_session.get(IdempotencyKey, (TENANT_ID, "atomic-crash-key")))
        assert row.response_status == 200
        assert row.response_body["id"] == retry.json()["id"]
    finally:
        run(retry_session.close())
        run(session.close())
        run(engine.dispose())


def test_create_approval_requires_background_tasks_before_writing(no_notifications):
    engine, session, tenant = run(make_sqlite_session())
    try:
        with pytest.raises(RuntimeError, match="requires request-scoped BackgroundTasks"):
            run(
                create_approval(
                    session,
                    tenant,
                    ApprovalCreate(**PAYLOAD),
                    background_tasks=None,
                )
            )
        assert _count_approvals(session) == 0
        assert len(no_notifications) == 0
    finally:
        run(session.close())
        run(engine.dispose())


def test_create_route_dispatches_notification_only_after_commit(no_notifications, monkeypatch):
    engine, session, tenant = run(make_sqlite_session())
    real_commit = session.commit
    commit_calls = 0

    async def observed_commit():
        nonlocal commit_calls
        commit_calls += 1
        assert len(no_notifications) == 0
        await real_commit()

    monkeypatch.setattr(session, "commit", observed_commit)
    try:
        with client_for(session, tenant) as client:
            response = client.post("/v1/approvals", json=PAYLOAD)

        assert response.status_code == 200
        assert commit_calls == 1
        assert _count_approvals(session) == 1
        assert len(no_notifications) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_unkeyed_success_commits_handler_write():
    """The wrapper owns the transaction even when idempotency is opt-out."""
    engine, session, _tenant = run(make_sqlite_session())
    verify_session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        async def handler():
            approval = Approval(tenant_id=TENANT_ID, function_name="unkeyed")
            session.add(approval)
            await session.flush()
            return {"id": approval.id}

        result = run(
            run_with_idempotency(
                session,
                tenant_id=TENANT_ID,
                idempotency_key=None,
                method="POST",
                path="/v1/approvals",
                request_body={},
                handler=handler,
            )
        )

        assert result["id"].startswith("act_")
        assert _count_approvals(verify_session) == 1
    finally:
        run(verify_session.close())
        run(session.close())
        run(engine.dispose())


def test_unkeyed_handler_failure_rolls_back():
    """A failed unkeyed handler cannot leave a partially persisted write."""
    engine, session, _tenant = run(make_sqlite_session())
    verify_session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        async def handler():
            session.add(Approval(tenant_id=TENANT_ID, function_name="must-rollback"))
            await session.flush()
            raise RuntimeError("handler failed")

        with pytest.raises(RuntimeError, match="handler failed"):
            run(
                run_with_idempotency(
                    session,
                    tenant_id=TENANT_ID,
                    idempotency_key=None,
                    method="POST",
                    path="/v1/approvals",
                    request_body={},
                    handler=handler,
                )
            )

        assert _count_approvals(verify_session) == 0
    finally:
        run(verify_session.close())
        run(session.close())
        run(engine.dispose())
