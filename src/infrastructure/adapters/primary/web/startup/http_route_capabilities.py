"""Approval-gated declarative plugin HTTP route assembly."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
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
from src.infrastructure.plugins.http_routes import (
    HttpRouteCapabilityAppAssembler,
    HttpRouteCapabilityRow,
    HttpRouteMountError,
    HttpRouteMountService,
)

logger = logging.getLogger(__name__)
AuthDependency = Callable[..., Any]


def _registry_inventory(
    registry_routes: Mapping[str, Sequence[Any]],
) -> tuple[dict[tuple[str, str], Any], dict[tuple[str, str], str]]:
    handlers: dict[tuple[str, str], Any] = {}
    handler_owners: dict[tuple[str, str], str] = {}
    for _plugin_id, routes in registry_routes.items():
        for route in routes:
            key = str(route.method).upper(), str(route.path)
            existing_owner = handler_owners.get(key)
            if existing_owner is not None and existing_owner != str(route.plugin_name):
                raise HttpRouteMountError(f"multiple plugins registered route {key[0]} {key[1]}")
            handlers[key] = route.handler
            handler_owners[key] = str(route.plugin_name)
    return handlers, handler_owners


def _desired_route_rows(
    desired_rows: Sequence[Any],
    handler_owners: Mapping[tuple[str, str], str],
) -> list[HttpRouteCapabilityRow]:
    rows: list[HttpRouteCapabilityRow] = []
    for row in desired_rows:
        if not bool(row.enabled):
            continue
        key = str(row.method).upper(), str(row.path)
        if handler_owners.get(key) != str(row.plugin_id):
            raise HttpRouteMountError(
                f"route {key[0]} {key[1]} handler is not owned by {row.plugin_id}"
            )
        rows.append(
            HttpRouteCapabilityRow(
                plugin_id=str(row.plugin_id),
                method=key[0],
                path=key[1],
                permission=str(row.permission),
                authorization_mode=str(row.authorization_mode),
            )
        )
    return rows


def _route_auth_dependencies(
    rows: Sequence[HttpRouteCapabilityRow],
) -> dict[tuple[str, str], AuthDependency]:
    dependencies: dict[tuple[str, str], AuthDependency] = {}
    for row in rows:
        dependencies[(row.method.upper(), row.path)] = _authorization_dependency(
            plugin_id=row.plugin_id,
            permission=row.permission,
            authorization=row.authorization_mode,
            path=row.path,
        )
    return dependencies


def build_http_route_capability_assembler(
    app: FastAPI,
    *,
    registry_routes: Mapping[str, Sequence[Any]],
    desired_rows: Sequence[Any],
) -> HttpRouteCapabilityAppAssembler:
    """Build one declarative route assembler without mounting its routes."""
    _handlers, handler_owners = _registry_inventory(registry_routes)
    rows = _desired_route_rows(desired_rows, handler_owners)
    return HttpRouteCapabilityAppAssembler(
        HttpRouteMountService(app),
        _fallback_authorization_dependencies(),
        _route_auth_dependencies(rows),
    )


def _fallback_authorization_dependencies() -> Mapping[HttpAuthorizationMode, AuthDependency]:
    async def denied() -> None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Plugin route authorization is invalid"),
        )

    return {
        HttpAuthorizationMode.TENANT_MEMBER: denied,
        HttpAuthorizationMode.PROJECT_MEMBER: denied,
        HttpAuthorizationMode.TENANT_ADMIN: denied,
    }


def _authorization_dependency(
    *,
    plugin_id: str,
    permission: str,
    authorization: str,
    path: str,
) -> AuthDependency:
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
        await require_tenant_access(
            db,
            current_user,
            tenant_id,
            require_admin=mode is HttpAuthorizationMode.TENANT_ADMIN,
        )
        granted = await PlatformPluginGovernanceRepository(db).permission_is_granted(
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


async def reconcile_http_route_capabilities(
    app: FastAPI,
    *,
    desired_rows: Sequence[Any],
) -> tuple[int, int]:
    """Mount/unmount plugin routes to exactly match persisted desired state."""
    from src.infrastructure.agent.plugins.registry import get_plugin_registry

    assembler = getattr(app.state, "platform_plugin_http_routes", None)
    if not isinstance(assembler, HttpRouteCapabilityAppAssembler):
        raise HttpRouteMountError("platform plugin HTTP routes are not installed")

    registry_routes = get_plugin_registry().list_http_routes()
    handlers, handler_owners = _registry_inventory(registry_routes)
    rows = _desired_route_rows(desired_rows, handler_owners)
    assembler.replace_route_auth_dependencies(_route_auth_dependencies(rows))
    return assembler.reconcile(rows, handlers)


async def install_http_route_capabilities(
    app: FastAPI,
    *,
    session_factory: Callable[[], Any],
) -> HttpRouteCapabilityAppAssembler | None:
    """Mount desired plugin routes only in V2 mode; fail loudly on drift."""
    from src.configuration.config import get_settings

    if not get_settings().platform_plugin_http_route_v2:
        return None
    from src.infrastructure.agent.plugins.registry import get_plugin_registry

    registry_routes = get_plugin_registry().list_http_routes()
    async with session_factory() as session:
        rows = await PlatformPluginGovernanceRepository(session).list_http_routes()
    assembler = build_http_route_capability_assembler(
        app,
        registry_routes=registry_routes,
        desired_rows=rows,
    )
    handlers, _handler_owners = _registry_inventory(registry_routes)
    desired = _desired_route_rows(rows, _handler_owners)
    added, removed = assembler.reconcile(desired, handlers)
    logger.info("Mounted platform plugin HTTP routes added=%d removed=%d", added, removed)
    return assembler
