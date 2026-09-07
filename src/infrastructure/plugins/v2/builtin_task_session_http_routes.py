"""V2-owned production contributions for the builtin task-session HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.workspace_core_task_sessions import (
    avernet_task_session_capabilities,
    create_avernet_task_session,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TASK_SESSION_HTTP_ROUTES_ENTRY_V2 = "builtin-task-session-http-routes"
TASK_SESSION_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/task-session-routes"
TASK_SESSION_HTTP_ROUTES_ROW_V2 = "task-session"
_TASK_SESSION_PREFIX_V2 = "/api/v1/tenants/{tenant_id}/projects/{project_id}/task-sessions"


def _task_session_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TASK_SESSION_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("task-sessions",),
        response_model=response_model,
        replaces_builtin_row_id=TASK_SESSION_HTTP_ROUTES_ROW_V2,
    )


def task_session_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``task-session`` inventory row."""
    return (
        _task_session_route_v2(
            path=f"{_TASK_SESSION_PREFIX_V2}/capabilities",
            methods=("GET",),
            endpoint=avernet_task_session_capabilities,
            name="avernet_task_session_capabilities",
            response_model=dict[str, Any],
        ),
        _task_session_route_v2(
            path=_TASK_SESSION_PREFIX_V2,
            methods=("POST",),
            endpoint=create_avernet_task_session,
            name="create_avernet_task_session",
            response_model=None,
        ),
    )


def builtin_task_session_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register task-session routes as reversible effects of one V2 Fiber."""
    definitions = task_session_route_definitions_v2()

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

        await context.effect(setup, label=TASK_SESSION_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=TASK_SESSION_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TASK_SESSION_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TASK_SESSION_HTTP_ROUTES_ENTRY_V2",
    "TASK_SESSION_HTTP_ROUTES_MODULE_V2",
    "TASK_SESSION_HTTP_ROUTES_ROW_V2",
    "builtin_task_session_http_routes_definition_v2",
    "task_session_route_definitions_v2",
]
