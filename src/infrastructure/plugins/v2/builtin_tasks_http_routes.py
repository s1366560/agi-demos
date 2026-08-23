"""V2-owned production contributions for the builtin tasks HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sse_starlette.sse import EventSourceResponse
from starlette.responses import Response

from src.infrastructure.adapters.primary.web.routers.tasks import (
    QueueDepthPoint,
    RecentTasksResponse,
    RetryPendingResponse,
    TaskLogResponse,
    TaskStatsResponse,
    cancel_task_endpoint,
    get_queue_depth,
    get_recent_tasks,
    get_status_breakdown,
    get_task_stats,
    get_task_status,
    retry_pending_tasks_endpoint,
    retry_task_endpoint,
    stop_task_endpoint,
    stream_task_status,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TASKS_HTTP_ROUTES_ENTRY_V2 = "builtin-tasks-http-routes"
TASKS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/tasks-routes"
TASKS_HTTP_ROUTES_ROW_V2 = "tasks"
_TASKS_PREFIX_V2 = "/api/v1/tasks"


def _task_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    response_class: type[Response] | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=TASKS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("tasks",),
        response_model=response_model,
        response_class=response_class,
        replaces_builtin_row_id=TASKS_HTTP_ROUTES_ROW_V2,
    )


def task_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``tasks`` inventory row."""
    prefix = _TASKS_PREFIX_V2
    mapping: tuple[
        tuple[
            str,
            tuple[str, ...],
            Callable[..., Any],
            str,
            object | None,
            type[Response] | None,
        ],
        ...,
    ] = (
        (f"{prefix}/stats", ("GET",), get_task_stats, "get_task_stats", TaskStatsResponse, None),
        (
            f"{prefix}/queue-depth",
            ("GET",),
            get_queue_depth,
            "get_queue_depth",
            list[QueueDepthPoint],
            None,
        ),
        (
            f"{prefix}/recent",
            ("GET",),
            get_recent_tasks,
            "get_recent_tasks",
            RecentTasksResponse,
            None,
        ),
        (
            f"{prefix}/status-breakdown",
            ("GET",),
            get_status_breakdown,
            "get_status_breakdown",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/retry-pending",
            ("POST",),
            retry_pending_tasks_endpoint,
            "retry_pending_tasks_endpoint",
            RetryPendingResponse,
            None,
        ),
        (
            f"{prefix}/{{task_id}}/retry",
            ("POST",),
            retry_task_endpoint,
            "retry_task_endpoint",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{task_id}}/stop",
            ("POST",),
            stop_task_endpoint,
            "stop_task_endpoint",
            dict[str, Any],
            None,
        ),
        (
            f"{prefix}/{{task_id}}/stream",
            ("GET",),
            stream_task_status,
            "stream_task_status",
            None,
            EventSourceResponse,
        ),
        (
            f"{prefix}/{{task_id}}",
            ("GET",),
            get_task_status,
            "get_task_status",
            TaskLogResponse,
            None,
        ),
        (
            f"{prefix}/{{task_id}}/cancel",
            ("POST",),
            cancel_task_endpoint,
            "cancel_task_endpoint",
            Any,
            None,
        ),
    )
    return tuple(
        _task_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
            response_class=response_class,
        )
        for path, methods, endpoint, name, response_model, response_class in mapping
    )


def builtin_tasks_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register task routes as reversible effects of one V2 Fiber."""
    definitions = task_route_definitions_v2()

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

        await context.effect(setup, label=TASKS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=TASKS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TASKS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TASKS_HTTP_ROUTES_ENTRY_V2",
    "TASKS_HTTP_ROUTES_MODULE_V2",
    "TASKS_HTTP_ROUTES_ROW_V2",
    "builtin_tasks_http_routes_definition_v2",
    "task_route_definitions_v2",
]
