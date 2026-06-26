"""ACP runner pool API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ACPRunnerPoolMode = Literal["kubernetes", "self_hosted"]


class ACPRunnerPoolCreate(BaseModel):
    pool_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$", alias="poolKey")
    name: str = Field(min_length=1, max_length=255)
    mode: ACPRunnerPoolMode = "self_hosted"
    enabled: bool = True
    labels: dict[str, str] = Field(default_factory=dict)
    capacity_policy: dict[str, Any] = Field(default_factory=dict, alias="capacityPolicy")
    scheduling_policy: dict[str, Any] = Field(default_factory=dict, alias="schedulingPolicy")


class ACPRunnerPoolUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mode: ACPRunnerPoolMode = "self_hosted"
    enabled: bool = True
    labels: dict[str, str] = Field(default_factory=dict)
    capacity_policy: dict[str, Any] = Field(default_factory=dict, alias="capacityPolicy")
    scheduling_policy: dict[str, Any] = Field(default_factory=dict, alias="schedulingPolicy")


class ACPRunnerPoolResponse(BaseModel):
    id: str
    tenant_id: str = Field(alias="tenantId")
    cluster_id: str = Field(alias="clusterId")
    pool_key: str = Field(alias="poolKey")
    name: str
    mode: str
    enabled: bool
    labels: dict[str, Any] = Field(default_factory=dict)
    capacity_policy: dict[str, Any] = Field(default_factory=dict, alias="capacityPolicy")
    scheduling_policy: dict[str, Any] = Field(default_factory=dict, alias="schedulingPolicy")
    runner_count: int = Field(default=0, alias="runnerCount")
    ready_runner_count: int = Field(default=0, alias="readyRunnerCount")
    active_session_count: int = Field(default=0, alias="activeSessionCount")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")


class ACPRunnerInstanceResponse(BaseModel):
    id: str
    tenant_id: str = Field(alias="tenantId")
    pool_id: str = Field(alias="poolId")
    runner_id: str = Field(alias="runnerId")
    status: str
    version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    current_sessions: int = Field(alias="currentSessions")
    max_sessions: int = Field(alias="maxSessions")
    last_heartbeat_at: datetime | None = Field(default=None, alias="lastHeartbeatAt")
    connection_id: str | None = Field(default=None, alias="connectionId")
    last_error: str | None = Field(default=None, alias="lastError")


class ACPRunnerTokenRequest(BaseModel):
    name: str | None = None
    expires_in_hours: int = Field(default=24, ge=1, le=24 * 30, alias="expiresInHours")


class ACPRunnerTokenResponse(BaseModel):
    token: str
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    connect_url: str = Field(alias="connectUrl")
    install_command: str = Field(alias="installCommand")
