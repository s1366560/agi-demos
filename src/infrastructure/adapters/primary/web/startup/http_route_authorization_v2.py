"""Scoped authorization dependencies shared by legacy and staged v2 HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.plugins import HttpAuthorizationMode
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserProject
from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
    PlatformPluginGovernanceRepository,
)
from src.infrastructure.i18n import gettext as _

type AuthDependencyV2 = Callable[..., Any]
type TenantAccessV2 = Callable[..., Any]
type GovernanceRepositoryFactoryV2 = Callable[[AsyncSession], Any]


def build_route_authorization_dependency_v2(
    *,
    plugin_id: str,
    permission: str,
    authorization: str,
    path: str,
    tenant_access: TenantAccessV2 = require_tenant_access,
    repository_factory: GovernanceRepositoryFactoryV2 = PlatformPluginGovernanceRepository,
) -> AuthDependencyV2:
    """Build one exact permission and tenant/project scoped FastAPI dependency."""
    mode = HttpAuthorizationMode(authorization)
    required_scope = (
        "tenant_id" if mode is not HttpAuthorizationMode.PROJECT_MEMBER else "project_id"
    )
    if f"{{{required_scope}}}" not in path:
        raise ValueError(f"plugin route {path} must expose {{{required_scope}}} for authorization")

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> str:
        scope_id = str(request.path_params[required_scope])
        if mode is HttpAuthorizationMode.PROJECT_MEMBER:
            tenant_id = await _project_tenant_id(db, scope_id, current_user.id)
        else:
            tenant_id = scope_id
        await tenant_access(
            db,
            current_user,
            tenant_id,
            require_admin=mode is HttpAuthorizationMode.TENANT_ADMIN,
        )
        granted = await repository_factory(db).permission_is_granted(
            plugin_id=plugin_id,
            permission=permission,
            scope_type="project" if mode is HttpAuthorizationMode.PROJECT_MEMBER else "tenant",
            scope_id=scope_id,
        )
        if not granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_("Plugin route permission is required"),
            )
        return scope_id

    return dependency


async def _project_tenant_id(db: AsyncSession, project_id: str, user_id: str) -> str:
    result = await db.execute(
        refresh_select_statement(
            select(Project.tenant_id)
            .join(UserProject, UserProject.project_id == Project.id)
            .where(Project.id == project_id, UserProject.user_id == user_id)
        )
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access required"),
        )
    return str(tenant_id)


__all__ = ["AuthDependencyV2", "build_route_authorization_dependency_v2"]
