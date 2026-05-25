from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


class TenantSignup(BaseModel):
    name: str
    email: str


class TenantSignupResponse(BaseModel):
    tenant_id: str
    api_key: str


class ApprovalCreate(BaseModel):
    function_name: str
    arguments: dict[str, Any] = {}
    risk_level: str = "medium"
    approvers: list[str] = []
    timeout_seconds: int = 300

    @field_validator("approvers")
    @classmethod
    def _non_empty_approvers(cls, v: list[str]) -> list[str]:
        if not v or not any(isinstance(x, str) and x.strip() for x in v):
            raise ValueError(
                "approvers must be a non-empty list. "
                "Use email (e.g. 'alice@acme.com'), 'slack://channel/C123', or 'sms:+15551234567'."
            )
        return v

    @field_validator("risk_level")
    @classmethod
    def _valid_risk(cls, v: str) -> str:
        if v not in VALID_RISK_LEVELS:
            raise ValueError(f"risk_level must be one of {sorted(VALID_RISK_LEVELS)}")
        return v

    @field_validator("timeout_seconds")
    @classmethod
    def _positive_timeout(cls, v: int) -> int:
        if v < 1 or v > 86400:
            raise ValueError("timeout_seconds must be between 1 and 86400")
        return v


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    function_name: str
    arguments: dict[str, Any] | None = None
    risk_level: str
    approvers: list[str] | None = None
    timeout_seconds: int
    decision: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None
    created_at: datetime


class DecisionRequest(BaseModel):
    decision: str
    decided_by: str
    reason: str | None = None


class TokenDecisionRequest(BaseModel):
    token: str


class AuditEventCreate(BaseModel):
    action_id: str
    execution_result: str
    error: str | None = None
