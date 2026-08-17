"""Schemas for platform plugin control-plane transport."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlatformPluginSnapshotResponse(BaseModel):
    version: int
    profile_id: str
    digest: str
    payload: dict[str, Any]


class PlatformPluginApplyStateRequest(BaseModel):
    data_plane_id: str = Field(min_length=1)
    snapshot_digest: str = Field(min_length=64, max_length=64)
    requested_version: int = Field(ge=1)
    applied_version: int = Field(ge=1)
    status: Literal["ack", "nack"]
    error_message: str | None = Field(default=None, max_length=8192)


class PlatformPluginApplyStateResponse(BaseModel):
    data_plane_id: str
    snapshot_digest: str
    requested_version: int
    applied_version: int
    status: Literal["ack", "nack"]
