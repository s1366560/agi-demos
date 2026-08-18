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
