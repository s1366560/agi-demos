"""V2-owned production contributions for the builtin observability HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.observability import (
    discover_nodes,
    get_alerts,
    get_message_heatmap,
    get_message_metrics,
    get_message_trace,
    get_node_card,
    get_node_metrics,
    get_queue_stats,
    list_circuit_breakers,
    list_dead_letters,
    list_events,
    list_node_types,
    post_node_message,
    reconstruct_message,
    retry_dead_letter,
    update_node_card,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

OBSERVABILITY_HTTP_ROUTES_ENTRY_V2 = "builtin-observability-http-routes"
OBSERVABILITY_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/observability-routes"
OBSERVABILITY_HTTP_ROUTES_ROW_V2 = "observability"
_OBSERVABILITY_PREFIX_V2 = "/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/observability"


def _observability_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=OBSERVABILITY_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("observability",),
        response_model=response_model,
        replaces_builtin_row_id=OBSERVABILITY_HTTP_ROUTES_ROW_V2,
    )


def observability_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``observability`` inventory row."""
    prefix = _OBSERVABILITY_PREFIX_V2
    mapping: tuple[tuple[str, tuple[str, ...], Callable[..., Any], str, object | None], ...] = (
        (
            f"{prefix}/messages/trace/{{trace_id}}",
            ("GET",),
            get_message_trace,
            "get_message_trace",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/metrics",
            ("GET",),
            get_message_metrics,
            "get_message_metrics",
            dict[str, Any],
        ),
        (
            f"{prefix}/messages/metrics/nodes/{{node_id}}",
            ("GET",),
            get_node_metrics,
            "get_node_metrics",
            dict[str, Any],
        ),
        (
            f"{prefix}/messages/heatmap",
            ("GET",),
            get_message_heatmap,
            "get_message_heatmap",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/dead-letters",
            ("GET",),
            list_dead_letters,
            "list_dead_letters",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/dead-letters/{{dead_letter_id}}/retry",
            ("POST",),
            retry_dead_letter,
            "retry_dead_letter",
            dict[str, Any],
        ),
        (
            f"{prefix}/messages/circuit-breakers",
            ("GET",),
            list_circuit_breakers,
            "list_circuit_breakers",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/events",
            ("GET",),
            list_events,
            "list_events",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/messages/{{message_id}}/reconstruct",
            ("GET",),
            reconstruct_message,
            "reconstruct_message",
            dict[str, Any],
        ),
        (
            f"{prefix}/messages/queue-stats",
            ("GET",),
            get_queue_stats,
            "get_queue_stats",
            dict[str, Any],
        ),
        (
            f"{prefix}/nodes/{{node_id}}/card",
            ("GET",),
            get_node_card,
            "get_node_card",
            dict[str, Any],
        ),
        (
            f"{prefix}/nodes/discover",
            ("GET",),
            discover_nodes,
            "discover_nodes",
            list[dict[str, Any]],
        ),
        (
            f"{prefix}/nodes/{{node_id}}/card",
            ("PUT",),
            update_node_card,
            "update_node_card",
            dict[str, Any],
        ),
        (
            f"{prefix}/nodes/{{node_id}}/messages",
            ("POST",),
            post_node_message,
            "post_node_message",
            dict[str, Any],
        ),
        (
            f"{prefix}/nodes/types",
            ("GET",),
            list_node_types,
            "list_node_types",
            list[dict[str, str]],
        ),
        (
            f"{prefix}/messages/alerts",
            ("GET",),
            get_alerts,
            "get_alerts",
            dict[str, Any],
        ),
    )
    return tuple(
        _observability_route_v2(
            path=path,
            methods=methods,
            endpoint=endpoint,
            name=name,
            response_model=response_model,
        )
        for path, methods, endpoint, name, response_model in mapping
    )


def builtin_observability_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register observability routes as reversible effects of one V2 Fiber."""
    definitions = observability_route_definitions_v2()

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

        await context.effect(setup, label=OBSERVABILITY_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=OBSERVABILITY_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(OBSERVABILITY_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "OBSERVABILITY_HTTP_ROUTES_ENTRY_V2",
    "OBSERVABILITY_HTTP_ROUTES_MODULE_V2",
    "OBSERVABILITY_HTTP_ROUTES_ROW_V2",
    "builtin_observability_http_routes_definition_v2",
    "observability_route_definitions_v2",
]
