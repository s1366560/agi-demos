"""V2-owned production contributions for the builtin project My Work HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.activity_read_state import (
    ActivityReadStateResponse,
    UpdateActivityReadStateRequest,
)
from src.application.schemas.project_my_work import ProjectMyWorkResponse
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.project_my_work import (
    get_activity_read_state as _get_activity_read_state,
    list_project_my_work as _list_project_my_work,
    put_activity_read_state as _put_activity_read_state,
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

PROJECT_MY_WORK_HTTP_ROUTES_ENTRY_V2 = "builtin-project-my-work-http-routes"
PROJECT_MY_WORK_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/project-my-work-routes"
PROJECT_MY_WORK_HTTP_ROUTES_ROW_V2 = "project-my-work"


async def list_project_my_work_v2(
    project_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectMyWorkResponse:
    """List current persisted execution authorities visible to the caller."""
    return await _list_project_my_work(project_id, request, current_user, db)


async def get_activity_read_state_v2(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityReadStateResponse:
    """Return the caller's server-authoritative Activity receipts."""
    return await _get_activity_read_state(project_id, current_user, db)


async def put_activity_read_state_v2(
    project_id: str,
    body: UpdateActivityReadStateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ActivityReadStateResponse:
    """Merge offline receipts by explicit entry revision and read time."""
    return await _put_activity_read_state(project_id, body, request, current_user, db)


def project_my_work_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``project-my-work`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=PROJECT_MY_WORK_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/projects/{project_id}/my-work",
            methods=("GET",),
            endpoint=list_project_my_work_v2,
            name="list_project_my_work",
            tags=("project-my-work",),
            response_model=ProjectMyWorkResponse,
            replaces_builtin_row_id=PROJECT_MY_WORK_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=PROJECT_MY_WORK_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/projects/{project_id}/activity/read-state",
            methods=("GET",),
            endpoint=get_activity_read_state_v2,
            name="get_activity_read_state",
            tags=("project-my-work",),
            response_model=ActivityReadStateResponse,
            replaces_builtin_row_id=PROJECT_MY_WORK_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=PROJECT_MY_WORK_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/projects/{project_id}/activity/read-state",
            methods=("PUT",),
            endpoint=put_activity_read_state_v2,
            name="put_activity_read_state",
            tags=("project-my-work",),
            response_model=ActivityReadStateResponse,
            replaces_builtin_row_id=PROJECT_MY_WORK_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_project_my_work_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the project My Work row as reversible route effects of one V2 Fiber."""
    definitions = project_my_work_route_definitions_v2()

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

        await context.effect(setup, label="builtin-project-my-work-http-routes")

    return PluginDefinitionV2(
        module_ref=PROJECT_MY_WORK_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(PROJECT_MY_WORK_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "PROJECT_MY_WORK_HTTP_ROUTES_ENTRY_V2",
    "PROJECT_MY_WORK_HTTP_ROUTES_MODULE_V2",
    "PROJECT_MY_WORK_HTTP_ROUTES_ROW_V2",
    "builtin_project_my_work_http_routes_definition_v2",
    "get_activity_read_state_v2",
    "list_project_my_work_v2",
    "project_my_work_route_definitions_v2",
    "put_activity_read_state_v2",
]
