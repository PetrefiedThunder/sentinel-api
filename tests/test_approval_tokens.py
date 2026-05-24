import pytest

from app.services.approval_tokens import (
    InvalidApprovalToken,
    create_decision_token,
    verify_decision_token,
)


def test_decision_token_round_trips_for_bound_action_and_decision():
    token = create_decision_token(
        "act_123",
        "approved",
        expires_in_seconds=300,
        now=1_000,
    )

    assert verify_decision_token(token, "act_123", now=1_100) == "approved"


def test_decision_token_rejects_wrong_action_id():
    token = create_decision_token(
        "act_123",
        "approved",
        expires_in_seconds=300,
        now=1_000,
    )

    with pytest.raises(InvalidApprovalToken):
        verify_decision_token(token, "act_999", now=1_100)


def test_decision_token_rejects_expired_token():
    token = create_decision_token(
        "act_123",
        "approved",
        expires_in_seconds=300,
        now=1_000,
    )

    with pytest.raises(InvalidApprovalToken):
        verify_decision_token(token, "act_123", now=1_301)

