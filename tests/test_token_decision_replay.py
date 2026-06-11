"""Replay protection for signed decision links.

A decision token is single-use: the first successful POST to
/token-decision records the decision and persists the token's nonce
(SHA-256 of the token) in `consumed_decision_nonces`. Any later request
with the same token is rejected with 409 — checked against the database,
so the protection survives process restarts and is independent of the
approval's current state.
"""

import pytest
from test_support import client_for, make_sqlite_session, run

from app.config import settings
from app.models import Approval, ConsumedDecisionNonce
from app.services.approval_tokens import create_decision_token
from app.services.nonce_store import token_nonce


@pytest.fixture(autouse=True)
def strong_jwt_secret(monkeypatch):
    monkeypatch.setattr(
        settings,
        "JWT_SECRET",
        "test-secret-with-at-least-32-bytes-of-entropy",
    )


def _make_pending_approval(session, tenant) -> Approval:
    approval = Approval(
        tenant_id=tenant.id,
        function_name="transfer_funds",
        arguments={"amount": 1000},
        approvers=["email:cfo@example.com"],
    )
    session.add(approval)
    run(session.commit())
    return approval


def test_token_decision_succeeds_once_and_records_nonce():
    engine, session, tenant = run(make_sqlite_session())
    try:
        approval = _make_pending_approval(session, tenant)
        token = create_decision_token(approval.id, "approved", expires_in_seconds=300)

        with client_for(session, tenant) as client:
            response = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": token},
            )

        assert response.status_code == 200
        assert response.json()["decision"] == "approved"
        assert response.json()["decided_by"] == "signed_link"

        nonce_row = run(session.get(ConsumedDecisionNonce, token_nonce(token)))
        assert nonce_row is not None
        assert nonce_row.action_id == approval.id
    finally:
        run(session.close())
        run(engine.dispose())


def test_token_decision_replay_is_rejected():
    engine, session, tenant = run(make_sqlite_session())
    try:
        approval = _make_pending_approval(session, tenant)
        token = create_decision_token(approval.id, "approved", expires_in_seconds=300)

        with client_for(session, tenant) as client:
            first = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": token},
            )
            replay = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": token},
            )

        assert first.status_code == 200
        assert replay.status_code == 409
        assert "already used" in replay.json()["detail"].lower()

        # Decision unchanged by the replay attempt.
        run(session.refresh(approval))
        assert approval.decision == "approved"
    finally:
        run(session.close())
        run(engine.dispose())


def test_replay_rejected_even_if_approval_state_changes():
    """The nonce check is independent of approval state — even if the
    approval somehow returned to 'pending', a consumed token stays dead."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        approval = _make_pending_approval(session, tenant)
        token = create_decision_token(approval.id, "approved", expires_in_seconds=300)

        with client_for(session, tenant) as client:
            first = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": token},
            )
            assert first.status_code == 200

            # Simulate state drift (e.g. manual reset) — the nonce store
            # must still block the replay.
            approval.decision = "pending"
            run(session.commit())

            replay = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": token},
            )

        assert replay.status_code == 409
        run(session.refresh(approval))
        assert approval.decision == "pending"
    finally:
        run(session.close())
        run(engine.dispose())


def test_distinct_token_still_usable_after_other_token_consumed():
    """Consuming the approve token must not poison the reject token —
    only the exact token that was used is blocked."""
    engine, session, tenant = run(make_sqlite_session())
    try:
        approval = _make_pending_approval(session, tenant)
        approve_token = create_decision_token(approval.id, "approved", expires_in_seconds=300)
        reject_token = create_decision_token(approval.id, "rejected", expires_in_seconds=600)

        with client_for(session, tenant) as client:
            first = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": approve_token},
            )
            second = client.post(
                f"/v1/approvals/{approval.id}/token-decision",
                json={"token": reject_token},
            )

        assert first.status_code == 200
        # Blocked by approval state (already approved), not by nonce reuse.
        assert second.status_code == 400
        assert "Already approved" in second.json()["detail"]
    finally:
        run(session.close())
        run(engine.dispose())
