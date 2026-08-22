"""V2-owned production contribution for the background-tasks HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.background_task_application_authority_v2 import (
    background_task_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.background_tasks import list_tasks

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

BACKGROUND_TASKS_HTTP_ROUTES_ENTRY_V2 = "builtin-background-tasks-http-routes"
BACKGROUND_TASKS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/background-tasks-routes"
BACKGROUND_TASKS_HTTP_ROUTES_ROW_V2 = "background-tasks"


def background_task_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``background-tasks`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=BACKGROUND_TASKS_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/tasks/",
            methods=("GET",),
            endpoint=list_tasks,
            name="list_tasks",
            tags=("tasks",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=BACKGROUND_TASKS_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_background_tasks_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the background task list route as one reversible V2 effect."""
    definitions = background_task_route_definitions_v2()

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

        await context.effect(setup, label=BACKGROUND_TASKS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=BACKGROUND_TASKS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(BACKGROUND_TASKS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "BACKGROUND_TASKS_HTTP_ROUTES_ENTRY_V2",
    "BACKGROUND_TASKS_HTTP_ROUTES_MODULE_V2",
    "BACKGROUND_TASKS_HTTP_ROUTES_ROW_V2",
    "background_task_application_authority_dependency_v2",
    "background_task_route_definitions_v2",
    "builtin_background_tasks_http_routes_definition_v2",
    "get_current_user",
]
