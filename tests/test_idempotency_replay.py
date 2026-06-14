"""Replay protection for the `Idempotency-Key` HEADER on approval creation.

Distinct from token/nonce replay (tests/test_token_decision_replay.py), which
covers single-use signed *decision* links. This file covers the Stripe-style
`Idempotency-Key: <opaque>` header on `POST /v1/approvals`, handled by
`app.services.idempotency.run_with_idempotency`:

  - same key + same body  -> replay the stored response verbatim; handler is
                             NOT re-run, so no duplicate row and no second
                             notification fires.
  - same key + diff body  -> 409 Conflict.
  - different keys         -> independent resources.
  - no key                -> no idempotency guarantee (every POST creates a row).

Notifications are dispatched as a FastAPI BackgroundTask from
`create_approval`; we monkeypatch `dispatch_approval_notifications` with a
counter to (a) keep the suite hermetic and (b) assert that a replay does not
fire a second notification.

FIXED BUG (was: datetime serialization 500 on first keyed POST)
---------------------------------------------------------------
`run_with_idempotency` used to store the handler's raw response dict into the
`idempotency_keys.response_body` JSON column. For approval creation that dict
contains a `datetime` (`created_at`, via `_serialize`). No custom
`json_serializer` is configured on the engine (app/db.py), so SQLAlchemy used
`json.dumps`, which raised `TypeError: Object of type datetime is not JSON
serializable` on the INSERT — on the FIRST keyed POST, before any replay,
breaking the feature on both SQLite (tests) and prod Postgres/asyncpg.

Fixed in `app.services.idempotency` by encoding the response with
`fastapi.encoders.jsonable_encoder` before persisting (and returning the
encoded form, so the first response matches the replay byte-for-byte). These
tests therefore run as normal assertions.
"""

import pytest
from sqlalchemy import func, select
from test_support import TENANT_ID, client_for, make_sqlite_session, run

from app.models import Approval, IdempotencyKey, Tenant

# An email approver needs no SMS-consent contact, so creation succeeds cleanly.
PAYLOAD = {
    "function_name": "transfer_funds",
    "arguments": {"amount": 1000, "to": "acct_123"},
    "risk_level": "high",
    "approvers": ["mailto:cfo@example.com"],
    "timeout_seconds": 300,
}


@pytest.fixture
def no_notifications(monkeypatch):
    """Replace the notification dispatcher with a call counter.

    Returns a list whose length == number of times notifications were
    dispatched. The replay path must NOT append to it.
    """
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


def test_same_key_same_payload_replays_original_resource(no_notifications):
    """Same Idempotency-Key + same payload -> same id, no duplicate row."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "key-aaa"}
            )
            replay = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "key-aaa"}
            )

        assert first.status_code == 200
        assert replay.status_code == 200
        # Same resource returned verbatim.
        assert first.json()["id"] == replay.json()["id"]
        assert first.json()["action_id"] == replay.json()["action_id"]
        assert replay.json() == first.json()
        # Exactly one row persisted.
        assert _count_approvals(session) == 1
        # Replay did not re-run the handler -> only one notification dispatched.
        assert len(no_notifications) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_same_key_different_payload_conflicts(no_notifications):
    """Same key + DIFFERENT payload -> 409, original unchanged, no new row.

    Implemented behavior (app/services/idempotency.py): the body is hashed and
    a mismatch raises HTTPException(409, "...previously used with a different
    request body...").
    """
    engine, session, tenant = run(make_sqlite_session())
    try:
        other_payload = {**PAYLOAD, "arguments": {"amount": 9999, "to": "acct_999"}}
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "key-bbb"}
            )
            conflict = client.post(
                "/v1/approvals",
                json=other_payload,
                headers={"Idempotency-Key": "key-bbb"},
            )

        assert first.status_code == 200
        assert conflict.status_code == 409
        assert "different request body" in conflict.json()["detail"].lower()
        # The conflicting request created nothing.
        assert _count_approvals(session) == 1
        assert len(no_notifications) == 1
    finally:
        run(session.close())
        run(engine.dispose())


def test_different_keys_create_independent_resources(no_notifications):
    """Different keys, same payload -> two distinct resources."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "key-ccc"}
            )
            second = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "key-ddd"}
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] != second.json()["id"]
        assert _count_approvals(session) == 2
        assert len(no_notifications) == 2
    finally:
        run(session.close())
        run(engine.dispose())


def test_no_key_does_not_dedupe(no_notifications):
    """Without the header, identical POSTs each create a new resource.

    Confirms the guard `if not idempotency_key: return await handler()` — the
    feature is opt-in, so omitting the key gives no dedupe.
    """
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            first = client.post("/v1/approvals", json=PAYLOAD)
            second = client.post("/v1/approvals", json=PAYLOAD)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] != second.json()["id"]
        assert _count_approvals(session) == 2
        assert len(no_notifications) == 2
    finally:
        run(session.close())
        run(engine.dispose())


def test_same_key_persists_idempotency_row(no_notifications):
    """The first use records an IdempotencyKey row keyed by (tenant, key)
    with the response body it will replay."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "key-eee"}
            )

        assert first.status_code == 200
        row = run(session.get(IdempotencyKey, (TENANT_ID, "key-eee")))
        assert row is not None
        assert row.method == "POST"
        assert row.path == "/v1/approvals"
        assert len(row.request_hash) == 64  # sha256 hex
        assert row.response_body["id"] == first.json()["id"]
    finally:
        run(session.close())
        run(engine.dispose())


def test_same_key_scoped_per_tenant(no_notifications):
    """The idempotency key is scoped to (tenant_id, key). The same key used by
    a different tenant is independent — it creates a fresh resource rather than
    replaying another tenant's response (compound PK in migration 007)."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        # First tenant uses the key.
        with client_for(session, tenant) as client:
            first = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "shared-key"}
            )
        assert first.status_code == 200

        # Second tenant in the same DB reuses the identical key + payload.
        other = Tenant(id="ten_other", name="Other", email="other@example.com")
        session.add(other)
        run(session.commit())
        with client_for(session, other) as client:
            second = client.post(
                "/v1/approvals", json=PAYLOAD, headers={"Idempotency-Key": "shared-key"}
            )

        assert second.status_code == 200
        # Independent resource, not a replay of tenant one's response.
        assert second.json()["id"] != first.json()["id"]
        assert second.json()["tenant_id"] == "ten_other"
    finally:
        run(session.close())
        run(engine.dispose())
