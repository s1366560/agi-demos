"""Schemas for platform plugin control-plane transport."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlatformPluginSnapshotResponse(BaseModel):
    version: int
    nonce: str
    profile_id: str
    digest: str
    payload: dict[str, Any]


class PlatformPluginApplyStateRequest(BaseModel):
    data_plane_id: str = Field(min_length=1)
    snapshot_digest: str = Field(min_length=64, max_length=64)
    requested_version: int = Field(ge=1)
    applied_version: int = Field(ge=0)
    status: Literal["ack", "nack"]
    error_message: str | None = Field(default=None, max_length=8192)


class PlatformPluginApplyStateResponse(BaseModel):
    data_plane_id: str
    snapshot_digest: str
    requested_version: int
    applied_version: int
    status: Literal["ack", "nack"]


class PlatformPluginShadowRolloutEventResponse(BaseModel):
    capability: str
    event_name: str
    hook_name: str
    scope_type: str
    scope_id: str
    equal: bool
    legacy_payload: dict[str, Any]
    typed_payload: dict[str, Any]
    occurred_at: datetime


class PlatformPluginShadowRolloutSummaryResponse(BaseModel):
    capability: str
    event_name: str
    total_count: int
    equal_count: int
    diff_count: int
    equal: bool
    last_occurred_at: datetime


class PlatformPluginShadowRolloutResponse(BaseModel):
    summary: list[PlatformPluginShadowRolloutSummaryResponse]
    events: list[PlatformPluginShadowRolloutEventResponse]


class PlatformPluginShadowRolloutCapabilityReadinessResponse(BaseModel):
    capability: str
    ready: bool
    total_count: int
    equal_count: int
    diff_count: int
    distinct_scope_count: int
    observed_event_count: int
    required_event_count: int
    last_occurred_at: datetime | None
    reasons: list[str]


class PlatformPluginShadowRolloutReadinessResponse(BaseModel):
    ready: bool
    checked_at: datetime
    minimum_samples_per_event: int
    minimum_distinct_scopes: int
    maximum_evidence_age_seconds: int
    capabilities: list[PlatformPluginShadowRolloutCapabilityReadinessResponse]
    reasons: list[str]


class PlatformPluginRollbackDrillDataPlaneResponse(BaseModel):
    data_plane_id: str
    ready: bool
    last_recorded_at: datetime | None
    reasons: list[str]


class PlatformPluginRollbackDrillReadinessResponse(BaseModel):
    ready: bool
    checked_at: datetime
    minimum_distinct_data_planes: int
    maximum_evidence_age_seconds: int
    data_planes: list[PlatformPluginRollbackDrillDataPlaneResponse]
    reasons: list[str]


class PlatformPluginCutoverReadinessResponse(BaseModel):
    ready: bool
    checked_at: datetime
    shadow: PlatformPluginShadowRolloutReadinessResponse
    rollback_drill: PlatformPluginRollbackDrillReadinessResponse
    approval: PlatformPluginCutoverApprovalResponse | None = None
    operator_approved: bool = False
    reasons: list[str]


class PlatformPluginCutoverApprovalResponse(BaseModel):
    capability: str
    approved_by: str
    approved_at: datetime
    expires_at: datetime
    evidence: dict[str, Any]


class PlatformPluginCutoverApprovalRequest(BaseModel):
    valid_for_seconds: int = Field(default=7 * 24 * 60 * 60, ge=3_600, le=30 * 24 * 60 * 60)


class PlatformPluginCutoverRevocationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=8192)


class PlatformPluginCutoverRevocationResponse(BaseModel):
    capability: str
    revoked: bool
    revoked_at: datetime
    reason: str
