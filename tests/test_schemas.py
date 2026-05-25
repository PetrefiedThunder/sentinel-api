import pytest
from pydantic import ValidationError

from app.schemas import ApprovalCreate


def test_approval_create_rejects_slack_approvers():
    with pytest.raises(ValidationError) as exc:
        ApprovalCreate(
            function_name="transfer_funds",
            arguments={"amount": 1000},
            risk_level="high",
            approvers=["slack://channel/C123"],
        )

    message = exc.value.errors()[0]["msg"]
    assert "Use email" in message
    assert "sms:" in message
    assert "slack://" not in message


def test_approval_create_accepts_sms_and_email_approvers():
    approval = ApprovalCreate(
        function_name="transfer_funds",
        arguments={"amount": 1000},
        risk_level="high",
        approvers=["sms:+15551234567", "mailto:ops@example.com"],
    )

    assert approval.approvers == ["sms:+15551234567", "mailto:ops@example.com"]
