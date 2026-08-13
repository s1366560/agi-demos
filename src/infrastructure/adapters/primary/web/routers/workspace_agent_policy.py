"""Public Workspace policy contracts implemented by Avernet Workspace Core."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.workspace_authority import (
    workspace_core_unavailable_error,
)

CAPABILITY_VERSION = "workspace-agent-policy-v1"
ReasoningEffort = Literal["low", "medium", "high"]
PermissionMode = Literal["ask", "automatic", "full_access"]
CapabilityMode = Literal["work", "code"]

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
    tags=["workspace-agent-policy"],
)
legacy_router = APIRouter(prefix="/api/v1/llm-providers", tags=["workspace-agent-policy"])


class RouteTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    model_id: str


class WorkspaceAgentPolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int
    capability_mode: CapabilityMode
    route: RouteTarget
    reasoning_effort: ReasoningEffort
    permission_mode: PermissionMode


class WorkspaceAgentPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    project_id: str
    workspace_id: str
    revision: int
    roles: dict[str, RouteTarget | None]
    fallbacks: list[RouteTarget]
    reasoning_effort: ReasoningEffort
    permission_mode: PermissionMode
    capability_version: Literal["workspace-agent-policy-v1"]
    updated_at: str


class LegacyRoutingPolicyMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    workspace_id: str
    expected_revision: int
    roles: dict[Literal["default", "fast", "coding", "vision"], RouteTarget | None]
    fallbacks: list[RouteTarget]


@router.get("/agent-policy", response_model=WorkspaceAgentPolicyResponse)
async def get_workspace_agent_policy(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    current_user: User = Depends(get_current_user),
) -> WorkspaceAgentPolicyResponse:
    """Define the proxy contract; direct Python execution is unavailable."""
    del tenant_id, project_id, workspace_id, current_user
    raise workspace_core_unavailable_error()


@router.patch("/agent-policy", response_model=WorkspaceAgentPolicyResponse)
async def patch_workspace_agent_policy(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    body: WorkspaceAgentPolicyPatch,
    current_user: User = Depends(get_current_user),
) -> WorkspaceAgentPolicyResponse:
    """Define the proxy contract; direct Python execution is unavailable."""
    del tenant_id, project_id, workspace_id, body, current_user
    raise workspace_core_unavailable_error()


@legacy_router.get("/routing-policy", response_model=WorkspaceAgentPolicyResponse)
async def get_legacy_workspace_routing_policy(
    project_id: str = Query(...),
    workspace_id: str = Query(...),
    current_user: User = Depends(get_current_user),
) -> WorkspaceAgentPolicyResponse:
    """Preserve the compatibility path exclusively as a Core proxy contract."""
    del project_id, workspace_id, current_user
    raise workspace_core_unavailable_error()


@legacy_router.put("/routing-policy", response_model=WorkspaceAgentPolicyResponse)
async def put_legacy_workspace_routing_policy(
    body: LegacyRoutingPolicyMutation,
    current_user: User = Depends(get_current_user),
) -> WorkspaceAgentPolicyResponse:
    """Preserve the compatibility path exclusively as a Core proxy contract."""
    del body, current_user
    raise workspace_core_unavailable_error()
