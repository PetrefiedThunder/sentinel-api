"""Opt-in transaction tests against a disposable, local PostgreSQL database.

See docs/idempotency-verification.md. These tests never use DATABASE_URL,
never execute notification background tasks, and never reset existing tables.
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.models import Approval, IdempotencyKey, Tenant
from app.routers import approvals
from app.schemas import ApprovalCreate
from app.services import idempotency

TEST_DATABASE_ENV = "SENTINEL_IDEMPOTENCY_TEST_DATABASE_URL"
SCHEMA_OPT_IN_ENV = "SENTINEL_IDEMPOTENCY_TEST_ALLOW_SCHEMA_CREATE"
TENANT_A = "ten_postgres_a"
TENANT_B = "ten_postgres_b"
PAYLOAD = {
    "function_name": "transfer_funds",
    "arguments": {"amount": 1000, "to": "acct_test"},
    "risk_level": "high",
    "approvers": ["mailto:approver@example.invalid"],
    "timeout_seconds": 300,
}


def _isolated_database_url():
    raw = os.environ.get(TEST_DATABASE_ENV)
    if not raw:
        pytest.skip(f"set {TEST_DATABASE_ENV} to opt into disposable PostgreSQL tests")
    if os.environ.get(SCHEMA_OPT_IN_ENV) != "1":
        pytest.fail(f"{SCHEMA_OPT_IN_ENV}=1 is required before creating test schemas")
    url = make_url(raw)
    if url.drivername != "postgresql+asyncpg":
        pytest.fail("the test database must use postgresql+asyncpg")
    if not url.database or not url.database.startswith("sentinel_idempotency_test_"):
        pytest.fail("refusing a database without the sentinel_idempotency_test_ prefix")
    if set(url.query) - {"host", "port"}:
        pytest.fail("only host and port query parameters are allowed in the test DSN")
    host = url.query.get("host", url.host)
    if not isinstance(host, str):
        pytest.fail("one explicit local test database host is required")
    # Dedicated local sockets are used by the verification harness; TCP is also
    # available for developers who explicitly provision a disposable local DB.
    local_socket = (
        Path(host).is_absolute()
        and str(Path(host).resolve()).startswith("/private/tmp/sentinel-qms-pg-")
    ) or (Path(host).is_absolute() and host.startswith("/tmp/sentinel-qms-pg-"))
    if host not in {"localhost", "127.0.0.1", "::1"} and not local_socket:
        pytest.fail("refusing a non-local or unrecognized PostgreSQL test destination")
    return url


@pytest_asyncio.fixture
async def pg_sessions():
    url = _isolated_database_url()
    schema = f"idempotency_test_{uuid4().hex}"
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "statement_timeout": "5000",
                "lock_timeout": "5000",
                "application_name": "sentinel-idempotency-verification",
            }
        },
    )
    created = False
    try:
        async with engine.begin() as conn:
            actual = await conn.scalar(text("SELECT current_database()"))
            assert actual == url.database, "connected database differs from the guarded DSN"
            await conn.execute(CreateSchema(schema))
            await conn.run_sync(
                lambda sync: Tenant.metadata.create_all(
                    sync,
                    tables=[Tenant.__table__, Approval.__table__, IdempotencyKey.__table__],
                )
            )
        created = True
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as seed:
            seed.add_all(
                [
                    Tenant(
                        id=TENANT_A, name="PG test A", email="pg-a@example.invalid", mode="test"
                    ),
                    Tenant(
                        id=TENANT_B, name="PG test B", email="pg-b@example.invalid", mode="test"
                    ),
                ]
            )
            await seed.commit()
        yield sessions
    finally:
        if created:
            async with engine.begin() as conn:
                await conn.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def _request(session, *, key="postgres-key", body=None, tenant_id=TENANT_A, tasks=None):
    tenant = await session.get(Tenant, tenant_id)
    assert tenant is not None
    return await approvals.create(
        payload=ApprovalCreate(**(body if body is not None else PAYLOAD)),
        background_tasks=tasks if tasks is not None else BackgroundTasks(),
        db=session,
        tenant=tenant,
        idempotency_key=key,
    )


async def _stored_counts(sessions, tenant_id=TENANT_A):
    # A fresh connection observes durable state, not the writer's identity map
    # or its own uncommitted rows. The failed writer is deliberately still open.
    async with sessions() as observer:
        return tuple(
            [
                await observer.scalar(
                    select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
                )
                for model in (Approval, IdempotencyKey)
            ]
        )


async def _assert_stored_response(sessions, response, tenant_id=TENANT_A):
    async with sessions() as observer:
        approval = await observer.get(Approval, response["id"])
        claim = await observer.get(IdempotencyKey, (tenant_id, "postgres-key"))
        assert approval is not None and approval.tenant_id == tenant_id
        assert claim is not None and claim.response_status == 200
        assert claim.response_body == response


async def _wait_for_database_block(observer, *, winner_pid, loser_pid):
    # Query PostgreSQL's lock manager rather than assuming overlap from elapsed
    # time. Each query yields to the request tasks; there are no timing sleeps.
    async with asyncio.timeout(4):
        while not await observer.scalar(
            text("SELECT :winner = ANY(pg_blocking_pids(:loser))"),
            {"winner": winner_pid, "loser": loser_pid},
        ):
            pass


@pytest.mark.parametrize("outcome", ["replay", "body_conflict", "winner_rollback"])
async def test_separate_connections_contend_on_same_key(pg_sessions, monkeypatch, outcome):
    entered = asyncio.Event()
    release = asyncio.Event()
    handler_calls = []
    real_create = approvals.create_approval

    async def controlled_create(db, tenant, payload, background_tasks=None):
        handler_calls.append(db)
        if len(handler_calls) == 1:
            entered.set()
            await release.wait()
            if outcome == "winner_rollback":
                raise RuntimeError("injected winner failure before approval creation")
        return await real_create(db, tenant, payload, background_tasks=background_tasks)

    monkeypatch.setattr(approvals, "create_approval", controlled_create)
    async with pg_sessions() as winner, pg_sessions() as loser, pg_sessions() as observer:
        winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
        loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))
        observer_pid = await observer.scalar(text("SELECT pg_backend_pid()"))
        assert len({winner_pid, loser_pid, observer_pid}) == 3
        first = asyncio.create_task(_request(winner))
        second = None
        try:
            async with asyncio.timeout(4):
                await entered.wait()
            other_body = (
                {**PAYLOAD, "arguments": {"amount": 9999}}
                if outcome == "body_conflict"
                else PAYLOAD
            )
            second = asyncio.create_task(_request(loser, body=other_body))
            await _wait_for_database_block(observer, winner_pid=winner_pid, loser_pid=loser_pid)
            assert len(handler_calls) == 1
            assert not second.done()
            release.set()
            async with asyncio.timeout(6):
                results = await asyncio.gather(first, second, return_exceptions=True)
        finally:
            release.set()
            requests = [task for task in (first, second) if task is not None]
            for task in requests:
                if not task.done():
                    task.cancel()
            async with asyncio.timeout(6):
                await asyncio.gather(*requests, return_exceptions=True)

        if outcome == "winner_rollback":
            assert isinstance(results[0], RuntimeError)
            assert "injected winner failure" in str(results[0])
            assert isinstance(results[1], dict)
            assert handler_calls == [winner, loser]
            response = results[1]
        elif outcome == "body_conflict":
            assert isinstance(results[0], dict)
            assert isinstance(results[1], HTTPException)
            assert results[1].status_code == 409
            assert "different request body" in results[1].detail
            assert handler_calls == [winner]
            response = results[0]
        else:
            assert isinstance(results[0], dict)
            assert results[0] == results[1]
            assert handler_calls == [winner]
            response = results[0]
        assert await _stored_counts(pg_sessions) == (1, 1)
        await _assert_stored_response(pg_sessions, response)
        async with pg_sessions() as retry:
            assert await _request(retry) == response
        assert len(handler_calls) == (2 if outcome == "winner_rollback" else 1)


async def test_response_serialization_failure_rolls_back_real_approval(pg_sessions, monkeypatch):
    """Decisive negative control: origin/main commits Approval before encoding."""
    tasks = BackgroundTasks()

    def fail_encoding(_response):
        raise RuntimeError("injected response serialization failure")

    async with pg_sessions() as failed:
        with monkeypatch.context() as patch:
            patch.setattr(idempotency, "jsonable_encoder", fail_encoding)
            with pytest.raises(RuntimeError, match="injected response serialization failure"):
                await _request(failed, tasks=tasks)
        assert len(tasks.tasks) == 1, "production create_approval did not reach task scheduling"
        assert await _stored_counts(pg_sessions) == (0, 0)
        assert not failed.in_transaction(), "rollback must happen before request-session cleanup"
        async with pg_sessions() as retry:
            response = await _request(retry)
        assert await _stored_counts(pg_sessions) == (1, 1)
        await _assert_stored_response(pg_sessions, response)


async def test_precommit_failure_rolls_back_real_approval(pg_sessions, monkeypatch):
    """Inject a failure before COMMIT reaches PostgreSQL, not an ambiguous ACK loss."""
    async with pg_sessions() as failed:
        tasks = BackgroundTasks()

        async def fail_commit():
            assert len(tasks.tasks) == 1
            raise RuntimeError("injected failure before commit")

        with monkeypatch.context() as patch:
            patch.setattr(failed, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="injected failure before commit"):
                await _request(failed, tasks=tasks)
        assert await _stored_counts(pg_sessions) == (0, 0)
        assert not failed.in_transaction()
        async with pg_sessions() as retry:
            response = await _request(retry)
        assert await _stored_counts(pg_sessions) == (1, 1)
        await _assert_stored_response(pg_sessions, response)


async def test_cancellation_after_approval_flush_rolls_back(pg_sessions, monkeypatch):
    created = asyncio.Event()
    pause = asyncio.Event()
    real_create = approvals.create_approval

    async def pause_after_create(db, tenant, payload, background_tasks=None):
        approval = await real_create(db, tenant, payload, background_tasks=background_tasks)
        created.set()
        await pause.wait()
        return approval

    async with pg_sessions() as failed:
        with monkeypatch.context() as patch:
            patch.setattr(approvals, "create_approval", pause_after_create)
            request = asyncio.create_task(_request(failed))
            try:
                async with asyncio.timeout(4):
                    await created.wait()
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    async with asyncio.timeout(6):
                        await request
            finally:
                request.cancel()
                async with asyncio.timeout(6):
                    await asyncio.gather(request, return_exceptions=True)
        assert await _stored_counts(pg_sessions) == (0, 0)
        assert not failed.in_transaction()
        async with pg_sessions() as retry:
            response = await _request(retry)
        assert await _stored_counts(pg_sessions) == (1, 1)
        await _assert_stored_response(pg_sessions, response)


async def test_same_key_is_isolated_by_tenant(pg_sessions):
    other_body = {**PAYLOAD, "arguments": {"amount": 2}}
    async with pg_sessions() as first, pg_sessions() as second:
        one = await _request(first, tenant_id=TENANT_A)
        two = await _request(second, tenant_id=TENANT_B, body=other_body)
    assert one["id"] != two["id"]
    assert one["tenant_id"] == TENANT_A and two["tenant_id"] == TENANT_B
    assert two["arguments"] == {"amount": 2}
    for tenant_id, body, response in ((TENANT_A, PAYLOAD, one), (TENANT_B, other_body, two)):
        assert await _stored_counts(pg_sessions, tenant_id) == (1, 1)
        await _assert_stored_response(pg_sessions, response, tenant_id)
        async with pg_sessions() as retry:
            assert await _request(retry, tenant_id=tenant_id, body=body) == response


async def test_oversized_key_is_rejected_without_writes(pg_sessions):
    tasks = BackgroundTasks()
    async with pg_sessions() as session:
        with pytest.raises(HTTPException) as error:
            await _request(session, key="x" * 256, tasks=tasks)
        assert error.value.status_code == 400
        assert not tasks.tasks
        assert await _stored_counts(pg_sessions) == (0, 0)
