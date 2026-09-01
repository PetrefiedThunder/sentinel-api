"""Decision, optional nonce, and audit evidence must commit as one unit."""

import asyncio
import secrets
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import generate_api_key
from app.config import settings
from app.db import Base, get_db
from app.models import ApiKey, Approval, AuditEvent, ConsumedDecisionNonce, Tenant
from app.routers import approvals
from app.schemas import DecisionRequest, TokenDecisionRequest
from app.services.approval_tokens import create_decision_token
from app.services.audit_log import append_audit_event

TENANT_ID = "ten_decision_atomic"
ACTION_ID = "act_decision_atomic"


@pytest_asyncio.fixture
async def sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", secrets.token_hex(32))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'decisions.sqlite'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as seed:
        seed.add(
            Tenant(id=TENANT_ID, name="Decision test", email="atomic@example.invalid", mode="test")
        )
        await seed.flush()
        seed.add(Approval(id=ACTION_ID, tenant_id=TENANT_ID, function_name="transfer_funds"))
        await seed.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _decide(session, route, token):
    if route == "token":
        return await approvals.decide_with_token(
            ACTION_ID, TokenDecisionRequest(token=token), db=session
        )
    tenant = await session.get(Tenant, TENANT_ID)
    return await approvals.decide(
        ACTION_ID,
        DecisionRequest(decision="approved", decided_by="test_approver"),
        db=session,
        tenant=tenant,
    )


async def _state(sessions):
    async with sessions() as observer:
        approval = await observer.get(Approval, ACTION_ID)
        audits = await observer.scalar(select(func.count()).select_from(AuditEvent))
        nonces = await observer.scalar(select(func.count()).select_from(ConsumedDecisionNonce))
        return approval.decision, audits, nonces


@pytest.mark.parametrize("route", ["authenticated", "token"])
async def test_audit_failure_does_not_persist_decision(sessions, monkeypatch, route):
    """Baseline control: audit failure must not strand a terminal decision."""
    notifications = []

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit append failure")

    async def record_side_effect(*args):
        notifications.append("unexpected dispatch")

    monkeypatch.setattr(approvals, "append_audit_event", fail_audit)
    monkeypatch.setattr(approvals, "notify_decision", record_side_effect)
    monkeypatch.setattr(approvals, "dispatch_approval_webhook", record_side_effect)
    token = create_decision_token(ACTION_ID, "approved", expires_in_seconds=300)
    async with sessions() as failed:
        with pytest.raises(RuntimeError, match="injected audit append failure"):
            await _decide(failed, route, token)
        assert await _state(sessions) == ("pending", 0, 0)
        assert not failed.in_transaction()
        assert notifications == []


@pytest.fixture
def dispatches(sessions, monkeypatch):
    calls = []

    async def notify(db, action_id):
        assert action_id == ACTION_ID
        assert (await _state(sessions))[:2] == ("approved", 1)
        calls.append("notify")

    async def webhook(db, approval):
        assert approval.id == ACTION_ID
        assert (await _state(sessions))[:2] == ("approved", 1)
        calls.append("webhook")

    monkeypatch.setattr(approvals, "notify_decision", notify)
    monkeypatch.setattr(approvals, "dispatch_approval_webhook", webhook)
    return calls


@pytest.mark.parametrize("route", ["authenticated", "token"])
@pytest.mark.parametrize("failure", ["after_audit", "commit", "cancel"])
async def test_staged_decision_failure_rolls_back_and_retries(
    sessions, monkeypatch, dispatches, route, failure
):
    staged = asyncio.Event()
    release = asyncio.Event()
    token = create_decision_token(ACTION_ID, "approved", expires_in_seconds=300)

    async def append_then_fail(*args, **kwargs):
        await append_audit_event(*args, **kwargs)
        if failure == "cancel":
            staged.set()
            await release.wait()
        raise RuntimeError("injected failure after audit staging")

    async with sessions() as failed:

        async def fail_commit():
            assert await failed.scalar(select(func.count()).select_from(AuditEvent)) == 1
            raise RuntimeError("injected failure before commit")

        with monkeypatch.context() as patch:
            if failure == "commit":
                patch.setattr(failed, "commit", fail_commit)
            else:
                patch.setattr(approvals, "append_audit_event", append_then_fail)
            if failure == "cancel":
                task = asyncio.create_task(_decide(failed, route, token))
                try:
                    async with asyncio.timeout(5):
                        await staged.wait()
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        async with asyncio.timeout(5):
                            await task
                finally:
                    task.cancel()
                    async with asyncio.timeout(5):
                        await asyncio.gather(task, return_exceptions=True)
            else:
                with pytest.raises(RuntimeError, match="injected failure"):
                    await _decide(failed, route, token)
        assert await _state(sessions) == ("pending", 0, 0)
        assert not failed.in_transaction()
        assert dispatches == []

    async with sessions() as retry:
        response = await _decide(retry, route, token)
        assert response["decision"] == "approved"
    assert await _state(sessions) == ("approved", 1, int(route == "token"))
    assert dispatches == ["notify", "webhook"]
    async with sessions() as replay:
        with pytest.raises(HTTPException) as error:
            await _decide(replay, route, token)
        assert error.value.status_code == (409 if route == "token" else 400)
    assert dispatches == ["notify", "webhook"]


@pytest.mark.parametrize("commit", [True, False])
async def test_audit_helper_preserves_default_commit_and_supports_staging(sessions, commit):
    async with sessions() as session:
        if commit:
            event = await append_audit_event(session, TENANT_ID, ACTION_ID, "observed")
        else:
            event = await append_audit_event(
                session, TENANT_ID, ACTION_ID, "observed", commit=False
            )
        assert event.id and event.event_hash
        assert await _state(sessions) == ("pending", int(commit), 0)
        await session.rollback()
    assert await _state(sessions) == ("pending", int(commit), 0)


@pytest.mark.parametrize("route", ["authenticated", "token"])
async def test_audit_constraint_failure_is_not_a_token_replay(
    sessions, monkeypatch, dispatches, route
):
    async with sessions() as seed:
        existing = await append_audit_event(seed, TENANT_ID, ACTION_ID, "existing")
        existing_id = existing.id

    async def duplicate_audit(db, tenant_id, action_id, execution_result, *, commit):
        db.add(
            AuditEvent(
                id=existing_id,
                tenant_id=tenant_id,
                action_id=action_id,
                execution_result=execution_result,
                event_hash="will-not-persist",
            )
        )
        await db.flush()

    monkeypatch.setattr(approvals, "append_audit_event", duplicate_audit)
    token = create_decision_token(ACTION_ID, "approved", expires_in_seconds=300)
    async with sessions() as failed:
        with pytest.raises(IntegrityError):
            await _decide(failed, route, token)
        assert await _state(sessions) == ("pending", 1, 0)
        assert not failed.in_transaction()
        assert dispatches == []


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("initial_rollback", "integrity"),
        ("nonce_lookup", "integrity"),
        ("final_rollback", "integrity"),
        ("cancel_lookup", "cancelled"),
    ],
)
async def test_nonce_integrity_cleanup_preserves_original_error_or_cancellation(
    sessions, monkeypatch, dispatches, failure, expected
):
    original = IntegrityError("injected audit constraint", {}, RuntimeError("duplicate"))

    async def fail_audit(*args, **kwargs):
        raise original

    monkeypatch.setattr(approvals, "append_audit_event", fail_audit)
    token = create_decision_token(ACTION_ID, "approved", expires_in_seconds=300)
    async with sessions() as failed:
        real_rollback = failed.rollback
        real_lookup = approvals.is_nonce_consumed
        rollback_calls = 0
        lookup_calls = 0

        async def controlled_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            if failure == "initial_rollback" and rollback_calls == 1:
                raise RuntimeError("injected initial rollback failure")
            if failure == "final_rollback" and rollback_calls == 2:
                raise RuntimeError("injected final rollback failure")
            await real_rollback()

        async def controlled_lookup(db, nonce):
            nonlocal lookup_calls
            lookup_calls += 1
            if lookup_calls <= 2:
                return await real_lookup(db, nonce)
            if failure == "cancel_lookup":
                raise asyncio.CancelledError
            raise RuntimeError("injected nonce lookup failure")

        monkeypatch.setattr(failed, "rollback", controlled_rollback)
        if failure in {"nonce_lookup", "cancel_lookup"}:
            monkeypatch.setattr(approvals, "is_nonce_consumed", controlled_lookup)
        try:
            if expected == "cancelled":
                with pytest.raises(asyncio.CancelledError):
                    await _decide(failed, "token", token)
            else:
                with pytest.raises(IntegrityError) as caught:
                    await _decide(failed, "token", token)
                assert caught.value is original
        finally:
            monkeypatch.setattr(failed, "rollback", real_rollback)
            await real_rollback()
        assert await _state(sessions) == ("pending", 0, 0)
        assert dispatches == []


@pytest.mark.parametrize("route", ["authenticated", "token"])
async def test_postcommit_dispatch_failure_keeps_decision_and_audit_together(
    sessions, monkeypatch, dispatches, route
):
    async def fail_notification(db, action_id):
        raise RuntimeError("injected postcommit dispatch failure")

    monkeypatch.setattr(approvals, "notify_decision", fail_notification)
    token = create_decision_token(ACTION_ID, "approved", expires_in_seconds=300)
    async with sessions() as failed:
        with pytest.raises(RuntimeError, match="injected postcommit dispatch failure"):
            await _decide(failed, route, token)
    expected = ("approved", 1, int(route == "token"))
    assert await _state(sessions) == expected
    async with sessions() as retry:
        with pytest.raises(HTTPException) as error:
            await _decide(retry, route, token)
        assert error.value.status_code == (409 if route == "token" else 400)
    assert await _state(sessions) == expected
    assert dispatches == []


@pytest_asyncio.fixture
async def api(sessions):
    # Exercise real HTTP dependency injection and API-key authentication. Only
    # get_db is replaced; no get_current_tenant override or app startup hooks.
    app = FastAPI()
    app.include_router(approvals.router, prefix="/v1/approvals")

    async def get_test_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = get_test_db
    keys = {}
    async with sessions() as seed:
        seed.add(Tenant(id="ten_other", name="Other", email="other@example.invalid", mode="test"))
        await seed.flush()
        for kind in ("valid", "revoked", "other_tenant"):
            raw, prefix, hashed = generate_api_key(mode="test")
            keys[kind] = raw
            seed.add(
                ApiKey(
                    tenant_id="ten_other" if kind == "other_tenant" else TENANT_ID,
                    key_hash=hashed,
                    prefix=prefix,
                    revoked_at=datetime.now(UTC).replace(tzinfo=None)
                    if kind == "revoked"
                    else None,
                )
            )
        await seed.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, keys


@pytest.mark.parametrize(
    ("case", "status"),
    [
        ("missing", 422),
        ("malformed", 401),
        ("unknown", 401),
        ("revoked", 401),
        ("other_tenant", 404),
        ("invalid_decision", 400),
        ("unknown_action", 404),
    ],
)
async def test_http_decision_rejects_unauthorized_or_invalid_requests(
    sessions, api, dispatches, case, status
):
    client, keys = api
    headers = {"Authorization": f"Bearer {keys.get(case, keys['valid'])}"}
    if case == "missing":
        headers = {}
    elif case == "malformed":
        headers = {"Authorization": "Basic invalid-test-value"}
    elif case == "unknown":
        headers = {"Authorization": "Bearer unknown-test-value"}
    action_id = "act_missing" if case == "unknown_action" else ACTION_ID
    response = await client.post(
        f"/v1/approvals/{action_id}/decision",
        headers=headers,
        json={
            "decision": "invalid" if case == "invalid_decision" else "approved",
            "decided_by": "test",
        },
    )
    assert response.status_code == status
    assert await _state(sessions) == ("pending", 0, 0)
    assert dispatches == []


@pytest.mark.parametrize("case", ["invalid", "expired", "wrong_action"])
async def test_http_token_decision_rejects_invalid_tokens(sessions, api, dispatches, case):
    client, _ = api
    token = (
        "invalid-test-token"
        if case == "invalid"
        else create_decision_token(
            "act_elsewhere" if case == "wrong_action" else ACTION_ID,
            "approved",
            expires_in_seconds=-60 if case == "expired" else 300,
        )
    )
    response = await client.post(f"/v1/approvals/{ACTION_ID}/token-decision", json={"token": token})
    assert response.status_code == 401
    assert await _state(sessions) == ("pending", 0, 0)
    assert dispatches == []


async def test_http_authenticated_decision_commits_audit_before_dispatch(sessions, api, dispatches):
    client, keys = api
    response = await client.post(
        f"/v1/approvals/{ACTION_ID}/decision",
        headers={"Authorization": f"Bearer {keys['valid']}"},
        json={"decision": "approved", "decided_by": "test"},
    )
    assert response.status_code == 200
    assert await _state(sessions) == ("approved", 1, 0)
    assert dispatches == ["notify", "webhook"]
