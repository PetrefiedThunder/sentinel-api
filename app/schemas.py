from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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


class AuditEventCreate(BaseModel):
    action_id: str
    execution_result: str
    error: str | None = None
