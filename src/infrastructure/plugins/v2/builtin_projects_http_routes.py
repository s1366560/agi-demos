"""V2-owned production contributions for the projects HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.application.schemas.project import (
    ProjectListResponse,
    ProjectResponse,
    ProjectStats,
)
from src.infrastructure.adapters.primary.web.routers.projects import (
    RecentSkillsResponse,
    TrendingResponse,
    add_project_member,
    create_project,
    delete_project,
    get_project,
    get_project_stats,
    get_recent_skills,
    get_trending_entities,
    list_project_members,
    list_projects,
    remove_project_member,
    update_project,
    update_project_member,
)

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
            endpoint=create_project,
            name="create_project",
            status_code=status.HTTP_201_CREATED,
            response_model=ProjectResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/",
            methods=("GET",),
            endpoint=list_projects,
            name="list_projects",
            response_model=ProjectListResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}",
            methods=("GET",),
            endpoint=get_project,
            name="get_project",
            response_model=ProjectResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}",
            methods=("PUT",),
            endpoint=update_project,
            name="update_project",
            response_model=ProjectResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}",
            methods=("DELETE",),
            endpoint=delete_project,
            name="delete_project",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members",
            methods=("POST",),
            endpoint=add_project_member,
            name="add_project_member",
            status_code=status.HTTP_201_CREATED,
            response_model=dict[str, Any],
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members/{user_id}",
            methods=("PATCH",),
            endpoint=update_project_member,
            name="update_project_member",
            response_model=dict,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members/{user_id}",
            methods=("DELETE",),
            endpoint=remove_project_member,
            name="remove_project_member",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/members",
            methods=("GET",),
            endpoint=list_project_members,
            name="list_project_members",
            response_model=dict[str, Any],
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/stats",
            methods=("GET",),
            endpoint=get_project_stats,
            name="get_project_stats",
            response_model=ProjectStats,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/trending",
            methods=("GET",),
            endpoint=get_trending_entities,
            name="get_trending_entities",
            response_model=TrendingResponse,
        ),
        _projects_route_v2(
            path="/api/v1/projects/{project_id}/recent-skills",
            methods=("GET",),
            endpoint=get_recent_skills,
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
    "builtin_projects_http_routes_definition_v2",
    "projects_route_definitions_v2",
]
