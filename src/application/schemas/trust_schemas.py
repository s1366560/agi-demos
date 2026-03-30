from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TrustPolicyCreate(BaseModel):
    workspace_id: str
    agent_instance_id: str
    action_type: str
    grant_type: str  # "once" | "always"


class TrustPolicyResponse(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    agent_instance_id: str
    action_type: str
    granted_by: str
    grant_type: str
    created_at: datetime
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}


class TrustPolicyListResponse(BaseModel):
    items: list[TrustPolicyResponse]


class TrustCheckResponse(BaseModel):
    trusted: bool


class ApprovalRequestCreate(BaseModel):
    workspace_id: str
    agent_instance_id: str
    action_type: str
    proposal: dict[str, Any] = {}
    context_summary: str | None = None


class ApprovalResolveRequest(BaseModel):
    decision: str  # "allow_once" | "allow_always" | "deny"


class DecisionRecordResponse(BaseModel):
    id: str
    tenant_id: str
    workspace_id: str
    agent_instance_id: str
    decision_type: str
    context_summary: str | None = None
    proposal: dict[str, Any] = {}
    outcome: str
    reviewer_id: str | None = None
    review_type: str | None = None
    review_comment: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    model_config = {"from_attributes": True}


class DecisionRecordListResponse(BaseModel):
    items: list[DecisionRecordResponse]
