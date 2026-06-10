from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models import Approval
from app.routers import approvals as approvals_router


class FakeDb:
    def __init__(self, approval):
        self.approval = approval
        self.committed = False
        self.refreshed = False

    async def get(self, model, key):
        if model is Approval and self.approval.id == key:
            return self.approval
        return None

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed = True


@pytest.fixture
def client_with_db():
    approval = Approval(
        id="act_123",
        tenant_id="ten_123",
        function_name="transfer_funds",
        arguments={"amount": 1000},
        risk_level="high",
        approvers=["sms:+15551234567"],
        timeout_seconds=300,
        decision="pending",
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db = FakeDb(approval)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app), approval, db
    finally:
        app.dependency_overrides.clear()


def test_signed_decision_link_approves_pending_action(client_with_db, monkeypatch):
    client, approval, db = client_with_db
    audit_events = []
    webhook_dispatches = []

    def verify_token(token, action_id):
        assert token == "signed_token"
        assert action_id == "act_123"
        return "approved"

    async def append_event(db_arg, tenant_id, action_id, execution_result):
        audit_events.append((tenant_id, action_id, execution_result))

    async def dispatch_webhook(db_arg, approval_arg):
        webhook_dispatches.append(approval_arg.id)

    monkeypatch.setattr(approvals_router, "verify_decision_token", verify_token, raising=False)
    monkeypatch.setattr(approvals_router, "append_audit_event", append_event)
    monkeypatch.setattr(approvals_router, "dispatch_approval_webhook", dispatch_webhook)

    response = client.post(
        "/v1/approvals/act_123/token-decision",
        json={"token": "signed_token"},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "approved"
    assert approval.decision == "approved"
    assert approval.decided_by == "signed_link"
    assert db.committed is True
    assert audit_events == [("ten_123", "act_123", "decision:approved")]
    assert webhook_dispatches == ["act_123"]


def test_signed_decision_link_rejects_invalid_token(client_with_db, monkeypatch):
    client, approval, db = client_with_db

    def verify_token(token, action_id):
        raise ValueError("bad token")

    monkeypatch.setattr(approvals_router, "verify_decision_token", verify_token, raising=False)

    response = client.post(
        "/v1/approvals/act_123/token-decision",
        json={"token": "bad"},
    )

    assert response.status_code == 401
    assert approval.decision == "pending"
    assert db.committed is False


def test_signed_decision_link_cannot_be_reused(client_with_db, monkeypatch):
    client, approval, db = client_with_db
    approval.decision = "approved"

    monkeypatch.setattr(
        approvals_router,
        "verify_decision_token",
        lambda token, action_id: "approved",
        raising=False,
    )

    response = client.post(
        "/v1/approvals/act_123/token-decision",
        json={"token": "signed_token"},
    )

    assert response.status_code == 400
    assert "Already approved" in response.json()["detail"]
    assert db.committed is False
