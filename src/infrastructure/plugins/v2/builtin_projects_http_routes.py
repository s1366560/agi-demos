"""V2-owned production contributions for the projects HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectStats,
    ProjectUpdate,
)
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.adapters.primary.web.backend_store_authority_v2 import (
    BackendStoreAuthorityV2,
    backend_store_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graph_store,
)
from src.infrastructure.adapters.primary.web.project_tenant_authority_v2 import (
    ProjectTenantAuthorityV2,
    project_tenant_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.projects import (
    AddProjectMemberRequest,
    RecentSkillsResponse,
    TrendingResponse,
    add_project_member as _add_project_member,
    create_project as _create_project,
    delete_project as _delete_project,
    get_project as _get_project,
    get_project_stats as _get_project_stats,
    get_recent_skills as _get_recent_skills,
    get_trending_entities as _get_trending_entities,
    list_project_members as _list_project_members,
    list_projects as _list_projects,
    remove_project_member as _remove_project_member,
    update_project as _update_project,
    update_project_member as _update_project_member,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PROJECTS_HTTP_ROUTES_ENTRY_V2 = "builtin-projects-http-routes"
PROJECTS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/projects-routes"
PROJECTS_HTTP_ROUTES_ROW_V2 = "projects"


async def create_project_v2(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    backend_store: BackendStoreAuthorityV2 = Depends(backend_store_authority_dependency_v2),
) -> ProjectResponse:
    """Create a new project."""
    return await _create_project(project_data, current_user, backend_store)


async def list_projects_v2(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    visibility: Literal["all", "public", "private"] = Query(
        "all", description="Filter by project visibility"
    ),
    owner_id: str | None = Query(None, description="Filter by owner ID"),
    current_user: User = Depends(get_current_user),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
    project_tenant: ProjectTenantAuthorityV2 = Depends(project_tenant_authority_dependency_v2),
    backend_store: BackendStoreAuthorityV2 = Depends(backend_store_authority_dependency_v2),
) -> ProjectListResponse:
    """List projects for the current user."""
    return await _list_projects(
        tenant_id,
        page,
        page_size,
        search,
        visibility,
        owner_id,
        current_user,
        graph_store,
        project_tenant,
        backend_store,
    )


async def get_project_v2(
    project_id: str,
    tenant_id: str | None = Query(None, description="Expected tenant scope"),
    current_user: User = Depends(get_current_user),
    backend_store: BackendStoreAuthorityV2 = Depends(backend_store_authority_dependency_v2),
) -> ProjectResponse:
    """Get project by ID."""
    return await _get_project(project_id, tenant_id, current_user, backend_store)


async def update_project_v2(
    project_id: str,
    project_data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    backend_store: BackendStoreAuthorityV2 = Depends(backend_store_authority_dependency_v2),
) -> ProjectResponse:
    """Update project."""
    return await _update_project(project_id, project_data, current_user, backend_store)


async def delete_project_v2(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete project."""
    await _delete_project(project_id, current_user, db)


async def add_project_member_v2(
    project_id: str,
    body: AddProjectMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Add member to project."""
    return await _add_project_member(project_id, body, current_user, db)


async def update_project_member_v2(
    project_id: str,
    user_id: str,
    member_data: ProjectMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update project member role."""
    return await _update_project_member(project_id, user_id, member_data, current_user, db)


async def remove_project_member_v2(
    project_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove member from project."""
    await _remove_project_member(project_id, user_id, current_user, db)


async def list_project_members_v2(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List project members."""
    return await _list_project_members(project_id, current_user, db)


async def get_project_stats_v2(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> ProjectStats:
    """Get project statistics for the dashboard."""
    return await _get_project_stats(project_id, current_user, db, graph_store)


async def get_trending_entities_v2(
    project_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> TrendingResponse:
    """Get trending entities in a project's knowledge graph."""
    return await _get_trending_entities(project_id, limit, current_user, db, graph_store)


async def get_recent_skills_v2(
    project_id: str,
    limit: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecentSkillsResponse:
    """Get recently used skills/tools in a project."""
    return await _get_recent_skills(project_id, limit, current_user, db)


def _projects_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    status_code: int | None = None,
    response_model: object | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=PROJECTS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("projects",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=PROJECTS_HTTP_ROUTES_ROW_V2,
    )


def projects_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``projects`` inventory row."""
    return (
        _projects_route_v2(
            path="/api/v1/projects/",
            methods=("POST",),
            endpoint=create_project_v2,
            name="create_project",
            status_code=status.HTTP_201_CREATED,
            response_model=ProjectResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/",
            methods=("GET",),
            endpoint=list_projects_v2,
            name="list_projects",
            response_model=ProjectListResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}",
            methods=("GET",),
            endpoint=get_project_v2,
            name="get_project",
            response_model=ProjectResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}",
            methods=("PUT",),
            endpoint=update_project_v2,
            name="update_project",
            response_model=ProjectResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}",
            methods=("DELETE",),
            endpoint=delete_project_v2,
            name="delete_project",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members",
            methods=("POST",),
            endpoint=add_project_member_v2,
            name="add_project_member",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members/{user_id}",
            methods=("PATCH",),
            endpoint=update_project_member_v2,
            name="update_project_member",
            response_model=dict,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members/{user_id}",
            methods=("DELETE",),
            endpoint=remove_project_member_v2,
            name="remove_project_member",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members",
            methods=("GET",),
            endpoint=list_project_members_v2,
            name="list_project_members",
            response_model=dict[str, Any],
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/stats",
            methods=("GET",),
            endpoint=get_project_stats_v2,
            name="get_project_stats",
            response_model=ProjectStats,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/trending",
            methods=("GET",),
            endpoint=get_trending_entities_v2,
            name="get_trending_entities",
            response_model=TrendingResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/recent-skills",
            methods=("GET",),
            endpoint=get_recent_skills_v2,
            name="get_recent_skills",
            response_model=RecentSkillsResponse,
        ),
    )


def builtin_projects_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register projects routes as reversible effects of one V2 Fiber."""
    definitions = projects_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label="builtin-projects-http-routes")

    return PluginDefinitionV2(
        module_ref=PROJECTS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(PROJECTS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "PROJECTS_HTTP_ROUTES_ENTRY_V2",
    "PROJECTS_HTTP_ROUTES_MODULE_V2",
    "PROJECTS_HTTP_ROUTES_ROW_V2",
    "AddProjectMemberRequest",
    "RecentSkillsResponse",
    "TrendingResponse",
    "add_project_member_v2",
    "builtin_projects_http_routes_definition_v2",
    "create_project_v2",
    "delete_project_v2",
    "get_project_stats_v2",
    "get_project_v2",
    "get_recent_skills_v2",
    "get_trending_entities_v2",
    "list_project_members_v2",
    "list_projects_v2",
    "projects_route_definitions_v2",
    "remove_project_member_v2",
    "update_project_member_v2",
    "update_project_v2",
]
