"""Schemas for platform plugin control-plane transport."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PlatformPluginDistributionResponseV2(BaseModel):
    schema_version: Literal[2] = 2
    descriptor: dict[str, Any]
    snapshot: dict[str, Any]
    envelope: dict[str, Any]


class PlatformPluginApplyStateResponseV2(BaseModel):
    schema_version: Literal[2] = 2
    data_plane_id: str
    nonce: str
    receipt: dict[str, Any]


class PlatformPluginDataPlaneCredentialIssueRequestV2(BaseModel):
    data_plane_id: str
    expires_at: datetime | None = None


class PlatformPluginDataPlaneCredentialRotateRequestV2(BaseModel):
    expires_at: datetime | None = None


class PlatformPluginDataPlaneCredentialResponseV2(BaseModel):
    schema_version: Literal[2] = 2
    credential_id: str
    data_plane_id: str
    key_prefix: str
    created_by_user_id: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by_user_id: str | None
    rotated_from_id: str | None


class PlatformPluginDataPlaneCredentialIssuedResponseV2(
    PlatformPluginDataPlaneCredentialResponseV2
):
    secret: str = Field(repr=False)


class PlatformPluginDataPlaneReadinessResponseV2(BaseModel):
    data_plane_id: str
    status: Literal["ack", "nack"] | None
    requested_version: int | None
    requested_digest: str | None
    applied_version: int | None
    applied_digest: str | None
    error_code: str | None
    error_message: str | None


class PlatformPluginPublicationReadinessResponseV2(BaseModel):
    schema_version: Literal[2] = 2
    publication_id: str
    profile_id: str
    generation: int
    requested_version: int
    snapshot_digest: str
    nonce: str
    republished_from_nonce: str | None
    required_data_plane_ids: list[str]
    ack_deadline_at: datetime
    status: Literal["reconciling", "ready", "degraded"]
    ready_at: datetime | None
    data_planes: list[PlatformPluginDataPlaneReadinessResponseV2]


class PlatformPluginDesiredBundleSetResponseV2(BaseModel):
    schema_version: Literal[2] = 2
    record_id: str
    scope: dict[str, str]
    desired_bundle_set: dict[str, Any]
    actor_id: str | None
    created_at: datetime


class PlatformPluginRouteAuthorityBindingResponseV2(BaseModel):
    method: str
    path: str
    source_plugin_id: str
    target_entry_id: str
    target_plugin_ref: str
    target_module_ref: str


class PlatformPluginRouteAuthorityReadinessResponseV2(BaseModel):
    schema_version: Literal[2] = 2
    profile_id: str
    generation: int
    snapshot_digest: str
    ready: bool
    required_route_count: int
    bound_route_count: int
    bindings: list[PlatformPluginRouteAuthorityBindingResponseV2]
    reasons: list[str]
