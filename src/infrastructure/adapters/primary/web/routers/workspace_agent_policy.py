"""Unified Workspace agent policy endpoints."""

from __future__ import annotations

import json
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    UserProject,
    WorkspaceAgentPolicyModel,
    WorkspaceMemberModel,
    WorkspaceModel,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.persistence.llm_providers_models import LLMProvider, TenantProviderMapping

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
    tenant_id: str
    project_id: str
    workspace_id: str
    revision: int
    roles: dict[str, RouteTarget | None]
    fallbacks: list[RouteTarget]
    reasoning_effort: ReasoningEffort
    permission_mode: PermissionMode
    capability_version: str
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
    db: AsyncSession = Depends(get_db),
) -> WorkspaceAgentPolicyResponse:
    workspace = await _require_workspace_access(
        db, current_user, tenant_id, project_id, workspace_id, require_manager=False
    )
    policy = await db.get(WorkspaceAgentPolicyModel, workspace_id)
    return await _policy_response(db, workspace, policy)


@router.patch("/agent-policy", response_model=WorkspaceAgentPolicyResponse)
async def patch_workspace_agent_policy(
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    body: WorkspaceAgentPolicyPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceAgentPolicyResponse:
    workspace = await _require_workspace_access(
        db, current_user, tenant_id, project_id, workspace_id, require_manager=True
    )
    await _validate_route(db, tenant_id, body.route)
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceAgentPolicyModel)
            .where(WorkspaceAgentPolicyModel.workspace_id == workspace_id)
            .with_for_update()
        )
    )
    policy = result.scalar_one_or_none()
    actual_revision = policy.revision if policy else 0
    if actual_revision != body.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Workspace policy revision conflict"),
        )
    roles = _default_roles() if policy is None else dict(policy.roles_json)
    if not roles.get("default"):
        roles["default"] = body.route.model_dump()
    roles["default" if body.capability_mode == "work" else "coding"] = body.route.model_dump()
    if policy is None:
        policy = WorkspaceAgentPolicyModel(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            project_id=project_id,
            revision=1,
            roles_json=roles,
            fallbacks_json=[],
            reasoning_effort=body.reasoning_effort,
            permission_mode=body.permission_mode,
            updated_by=current_user.id,
        )
        db.add(policy)
    else:
        policy.revision += 1
        policy.roles_json = roles
        policy.reasoning_effort = body.reasoning_effort
        policy.permission_mode = body.permission_mode
        policy.updated_by = current_user.id
    await db.commit()
    await db.refresh(policy)
    return await _policy_response(db, workspace, policy)


@legacy_router.get("/routing-policy", response_model=WorkspaceAgentPolicyResponse)
async def get_legacy_workspace_routing_policy(
    project_id: str = Query(...),
    workspace_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceAgentPolicyResponse:
    workspace = await _workspace_by_project(db, project_id, workspace_id)
    await _require_workspace_access(
        db,
        current_user,
        workspace.tenant_id,
        project_id,
        workspace_id,
        require_manager=False,
    )
    return await _policy_response(
        db,
        workspace,
        await db.get(WorkspaceAgentPolicyModel, workspace_id),
    )


@legacy_router.put("/routing-policy", response_model=WorkspaceAgentPolicyResponse)
async def put_legacy_workspace_routing_policy(
    body: LegacyRoutingPolicyMutation,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceAgentPolicyResponse:
    workspace = await _workspace_by_project(db, body.project_id, body.workspace_id)
    await _require_workspace_access(
        db,
        current_user,
        workspace.tenant_id,
        body.project_id,
        body.workspace_id,
        require_manager=True,
    )
    if body.roles.get("default") is None:
        raise HTTPException(status_code=400, detail=_("Default model route is required"))
    for route in [*body.roles.values(), *body.fallbacks]:
        if route is not None:
            await _validate_route(db, workspace.tenant_id, route)
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceAgentPolicyModel)
            .where(WorkspaceAgentPolicyModel.workspace_id == body.workspace_id)
            .with_for_update()
        )
    )
    policy = result.scalar_one_or_none()
    actual_revision = policy.revision if policy else 0
    if actual_revision != body.expected_revision:
        raise HTTPException(status_code=409, detail=_("Workspace policy revision conflict"))
    role_names: tuple[Literal["default", "fast", "coding", "vision"], ...] = (
        "default",
        "fast",
        "coding",
        "vision",
    )
    roles: dict[str, dict[str, str] | None] = {}
    for role in role_names:
        target = body.roles.get(role)
        roles[role] = target.model_dump() if target is not None else None
    fallbacks = [route.model_dump() for route in body.fallbacks]
    if policy is None:
        policy = WorkspaceAgentPolicyModel(
            workspace_id=body.workspace_id,
            tenant_id=workspace.tenant_id,
            project_id=body.project_id,
            revision=1,
            roles_json=roles,
            fallbacks_json=fallbacks,
            reasoning_effort="medium",
            permission_mode="ask",
            updated_by=current_user.id,
        )
        db.add(policy)
    else:
        policy.revision += 1
        policy.roles_json = roles
        policy.fallbacks_json = fallbacks
        policy.updated_by = current_user.id
    await db.commit()
    await db.refresh(policy)
    return await _policy_response(db, workspace, policy)


async def _workspace_by_project(
    db: AsyncSession,
    project_id: str,
    workspace_id: str,
) -> WorkspaceModel:
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceModel).where(
                WorkspaceModel.id == workspace_id,
                WorkspaceModel.project_id == project_id,
                WorkspaceModel.is_archived.is_(False),
            )
        )
    )
    workspace = cast(WorkspaceModel | None, result.scalar_one_or_none())
    if workspace is None:
        raise HTTPException(status_code=404, detail=_("Workspace not found"))
    return workspace


async def _require_workspace_access(
    db: AsyncSession,
    current_user: User,
    tenant_id: str,
    project_id: str,
    workspace_id: str,
    *,
    require_manager: bool,
) -> WorkspaceModel:
    result = await db.execute(
        refresh_select_statement(
            select(WorkspaceModel).where(
                WorkspaceModel.id == workspace_id,
                WorkspaceModel.tenant_id == tenant_id,
                WorkspaceModel.project_id == project_id,
                WorkspaceModel.is_archived.is_(False),
            )
        )
    )
    workspace = cast(WorkspaceModel | None, result.scalar_one_or_none())
    if workspace is None:
        raise HTTPException(status_code=404, detail=_("Workspace not found"))
    if workspace.created_by == current_user.id:
        return workspace
    workspace_access = await db.execute(
        refresh_select_statement(
            select(WorkspaceMemberModel.role).where(
                WorkspaceMemberModel.workspace_id == workspace_id,
                WorkspaceMemberModel.user_id == current_user.id,
            )
        )
    )
    project_access = await db.execute(
        refresh_select_statement(
            select(UserProject.role).where(
                UserProject.project_id == project_id,
                UserProject.user_id == current_user.id,
            )
        )
    )
    workspace_role = workspace_access.scalar_one_or_none()
    project_role = project_access.scalar_one_or_none()
    if workspace_role is None and project_role is None:
        raise HTTPException(status_code=403, detail=_("Access denied"))
    if (
        require_manager
        and workspace_role not in {"manager", "owner"}
        and project_role not in {"admin", "owner"}
    ):
        raise HTTPException(status_code=403, detail=_("Access denied"))
    return workspace


async def _validate_route(db: AsyncSession, tenant_id: str, route: RouteTarget) -> None:
    try:
        provider_id = UUID(route.provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_("Invalid provider route")) from exc
    result = await db.execute(
        refresh_select_statement(
            select(LLMProvider)
            .join(TenantProviderMapping, TenantProviderMapping.provider_id == LLMProvider.id)
            .where(
                TenantProviderMapping.tenant_id == tenant_id,
                TenantProviderMapping.operation_type == "llm",
                LLMProvider.id == provider_id,
                LLMProvider.operation_type == "llm",
                LLMProvider.is_active.is_(True),
                LLMProvider.is_enabled.is_(True),
            )
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None or route.model_id not in _provider_models(provider):
        raise HTTPException(status_code=400, detail=_("Invalid provider route"))


def _provider_models(provider: LLMProvider) -> set[str]:
    models = {provider.llm_model} if provider.llm_model else set()
    if provider.allowed_models:
        try:
            values = json.loads(provider.allowed_models)
        except json.JSONDecodeError:
            values = []
        if isinstance(values, list):
            models.update(str(value) for value in values if value)
    models.update(provider.secondary_models or [])
    return models


async def _policy_response(
    db: AsyncSession,
    workspace: WorkspaceModel,
    policy: WorkspaceAgentPolicyModel | None,
) -> WorkspaceAgentPolicyResponse:
    if policy is None:
        roles = _default_roles()
        default_route = await _default_route(db, workspace.tenant_id)
        roles["default"] = default_route.model_dump() if default_route else None
        roles["coding"] = default_route.model_dump() if default_route else None
        return WorkspaceAgentPolicyResponse.model_validate(
            {
                "tenant_id": workspace.tenant_id,
                "project_id": workspace.project_id,
                "workspace_id": workspace.id,
                "revision": 0,
                "roles": roles,
                "fallbacks": [],
                "reasoning_effort": "medium",
                "permission_mode": "ask",
                "capability_version": CAPABILITY_VERSION,
                "updated_at": (workspace.updated_at or workspace.created_at).isoformat(),
            }
        )
    return WorkspaceAgentPolicyResponse.model_validate(
        {
            "tenant_id": policy.tenant_id,
            "project_id": policy.project_id,
            "workspace_id": policy.workspace_id,
            "revision": policy.revision,
            "roles": policy.roles_json,
            "fallbacks": policy.fallbacks_json,
            "reasoning_effort": policy.reasoning_effort,
            "permission_mode": policy.permission_mode,
            "capability_version": CAPABILITY_VERSION,
            "updated_at": policy.updated_at.isoformat(),
        }
    )


async def _default_route(db: AsyncSession, tenant_id: str) -> RouteTarget | None:
    result = await db.execute(
        refresh_select_statement(
            select(LLMProvider)
            .join(TenantProviderMapping, TenantProviderMapping.provider_id == LLMProvider.id)
            .where(
                TenantProviderMapping.tenant_id == tenant_id,
                TenantProviderMapping.operation_type == "llm",
                LLMProvider.operation_type == "llm",
                LLMProvider.is_active.is_(True),
                LLMProvider.is_enabled.is_(True),
            )
            .order_by(TenantProviderMapping.priority, LLMProvider.created_at)
            .limit(1)
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None or not provider.llm_model:
        return None
    return RouteTarget(provider_id=str(provider.id), model_id=provider.llm_model)


def _default_roles() -> dict[str, dict[str, str] | None]:
    return {"default": None, "fast": None, "coding": None, "vision": None}
