"""Project-scoped compatibility authority for pooled Agent instances."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import has_global_admin_access
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserProject
from src.infrastructure.audit.audit_log_service import get_audit_service
from src.infrastructure.i18n import gettext as _

from ..instance import AgentInstance
from ..manager import AgentPoolManager
from .router import (
    InstanceInfo,
    _build_instance_info,
    _get_pool_manager,
    _get_pool_manager_optional,
    _require_lifecycle_action,
)

logger = logging.getLogger(__name__)

_LIFECYCLE_ROLES = frozenset({"owner", "admin", "global_admin"})


@dataclass(frozen=True, slots=True)
class ProjectPoolAccess:
    """Exact authenticated project scope and objective membership role."""

    tenant_id: str
    project_id: str
    role: str
    actor_id: str | None = None

    @property
    def allowed_actions(self) -> list[str]:
        actions = ["view"]
        if self.role in _LIFECYCLE_ROLES:
            actions.extend(["pause", "resume", "terminate"])
        return actions


class ProjectPoolInstanceResponse(BaseModel):
    """Exact project pool-instance projection."""

    enabled: bool
    instance: InstanceInfo | None
    allowed_actions: list[str] = Field(default_factory=list)
    reason_code: str | None = None


class ProjectPoolOperationResponse(BaseModel):
    """Project-scoped lifecycle operation result."""

    success: bool
    action: str
    allowed_actions: list[str] = Field(default_factory=list)


async def resolve_project_pool_access(
    tenant_id: str,
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectPoolAccess:
    """Resolve exact project membership without default-tenant inference."""
    project_result = await db.execute(
        refresh_select_statement(
            select(Project.tenant_id, Project.owner_id).where(Project.id == project_id).limit(1)
        )
    )
    project_row = project_result.one_or_none()
    if project_row is None or str(project_row.tenant_id) != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Project not found"),
        )

    actor_id = str(current_user.id)
    if await has_global_admin_access(db, current_user):
        return ProjectPoolAccess(tenant_id, project_id, "global_admin", actor_id)

    membership_result = await db.execute(
        refresh_select_statement(
            select(UserProject.role)
            .where(
                UserProject.user_id == actor_id,
                UserProject.project_id == project_id,
            )
            .limit(1)
        )
    )
    role = membership_result.scalar_one_or_none()
    if role is None and str(project_row.owner_id) == actor_id:
        role = "owner"
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access required"),
        )
    return ProjectPoolAccess(tenant_id, project_id, str(role), actor_id)


def require_project_pool_lifecycle_access(
    access: ProjectPoolAccess = Depends(resolve_project_pool_access),
) -> ProjectPoolAccess:
    """Require project ownership or administration for shared actor mutation."""
    if access.role not in _LIFECYCLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project owner or admin access required"),
        )
    return access


def _require_matching_path(
    tenant_id: str,
    project_id: str,
    access: ProjectPoolAccess,
) -> None:
    if access.tenant_id != tenant_id or access.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Pool instance not found"),
        )


def _find_exact_instance(
    manager: AgentPoolManager,
    tenant_id: str,
    project_id: str,
    agent_mode: str,
) -> tuple[str, AgentInstance] | None:
    instance_key = f"{tenant_id}:{project_id}:{agent_mode}"
    instance = manager._instances.get(instance_key)
    if instance is None:
        return None
    if (
        str(instance.config.tenant_id) != tenant_id
        or str(instance.config.project_id) != project_id
        or str(instance.config.agent_mode) != agent_mode
    ):
        return None
    return instance_key, instance


async def _get_project_pool_instance(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    access: ProjectPoolAccess = Depends(resolve_project_pool_access),
    manager: AgentPoolManager | None = Depends(_get_pool_manager_optional),
) -> ProjectPoolInstanceResponse:
    _require_matching_path(tenant_id, project_id, access)

    from src.configuration.config import get_settings

    if not get_settings().agent_pool_enabled:
        return ProjectPoolInstanceResponse(
            enabled=False,
            instance=None,
            allowed_actions=access.allowed_actions,
            reason_code="agent_pool_disabled",
        )
    if manager is None:
        return ProjectPoolInstanceResponse(
            enabled=True,
            instance=None,
            allowed_actions=access.allowed_actions,
            reason_code="agent_pool_initializing",
        )

    found = _find_exact_instance(manager, tenant_id, project_id, agent_mode)
    return ProjectPoolInstanceResponse(
        enabled=True,
        instance=_build_instance_info(*found) if found else None,
        allowed_actions=access.allowed_actions,
        reason_code=None if found else "project_pool_instance_not_found",
    )


async def _audit_project_operation(
    *,
    action: str,
    instance_key: str,
    instance: AgentInstance,
    access: ProjectPoolAccess,
) -> None:
    await get_audit_service().log_event(
        action=f"runtime_pool.project_instance.{action}",
        resource_type="runtime_pool_instance",
        resource_id=instance_key,
        actor=access.actor_id,
        tenant_id=access.tenant_id,
        details={
            "scope": "project",
            "project_id": access.project_id,
            "agent_mode": str(instance.config.agent_mode),
            "result": "success",
        },
    )


async def _mutate_project_pool_instance(
    *,
    action: str,
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    access: ProjectPoolAccess,
    manager: AgentPoolManager,
) -> ProjectPoolOperationResponse:
    _require_matching_path(tenant_id, project_id, access)
    found = _find_exact_instance(manager, tenant_id, project_id, agent_mode)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Pool instance not found"),
        )
    instance_key, instance = found
    _require_lifecycle_action(instance, action)

    try:
        if action == "pause":
            await instance.pause()
        elif action == "resume":
            await instance.resume()
        else:
            await manager.terminate_instance(
                tenant_id,
                project_id,
                agent_mode,
                graceful=True,
            )
        await _audit_project_operation(
            action=action,
            instance_key=instance_key,
            instance=instance,
            access=access,
        )
    except Exception as exc:
        logger.error("Project pool lifecycle failed: error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_("Pool lifecycle operation failed"),
        ) from exc

    return ProjectPoolOperationResponse(
        success=True,
        action=action,
        allowed_actions=access.allowed_actions,
    )


async def _pause_project_pool_instance(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    access: ProjectPoolAccess = Depends(require_project_pool_lifecycle_access),
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> ProjectPoolOperationResponse:
    return await _mutate_project_pool_instance(
        action="pause",
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode=agent_mode,
        access=access,
        manager=manager,
    )


async def _resume_project_pool_instance(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    access: ProjectPoolAccess = Depends(require_project_pool_lifecycle_access),
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> ProjectPoolOperationResponse:
    return await _mutate_project_pool_instance(
        action="resume",
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode=agent_mode,
        access=access,
        manager=manager,
    )


async def _terminate_project_pool_instance(
    tenant_id: str,
    project_id: str,
    agent_mode: str,
    access: ProjectPoolAccess = Depends(require_project_pool_lifecycle_access),
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> ProjectPoolOperationResponse:
    return await _mutate_project_pool_instance(
        action="terminate",
        tenant_id=tenant_id,
        project_id=project_id,
        agent_mode=agent_mode,
        access=access,
        manager=manager,
    )


def create_project_pool_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/tenants/{tenant_id}/projects/{project_id}/pool",
        tags=["Project Agent Pool"],
    )
    router.get(
        "/instances/{agent_mode}",
        response_model=ProjectPoolInstanceResponse,
    )(_get_project_pool_instance)
    router.post(
        "/instances/{agent_mode}/pause",
        response_model=ProjectPoolOperationResponse,
    )(_pause_project_pool_instance)
    router.post(
        "/instances/{agent_mode}/resume",
        response_model=ProjectPoolOperationResponse,
    )(_resume_project_pool_instance)
    router.delete(
        "/instances/{agent_mode}",
        response_model=ProjectPoolOperationResponse,
    )(_terminate_project_pool_instance)
    return router
