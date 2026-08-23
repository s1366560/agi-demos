"""V2-owned production contributions for the builtin admin DLQ HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.admin_dlq import (
    CleanupResponse,
    DiscardResponse,
    DLQListResponse,
    DLQMessageResponse,
    DLQStatsResponse,
    RetryResponse,
    cleanup_expired,
    cleanup_resolved,
    discard_message,
    discard_messages,
    get_message,
    get_stats,
    list_messages,
    retry_message,
    retry_messages,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ADMIN_DLQ_HTTP_ROUTES_ENTRY_V2 = "builtin-admin-dlq-http-routes"
ADMIN_DLQ_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/admin-dlq-routes"
ADMIN_DLQ_HTTP_ROUTES_ROW_V2 = "admin-dlq"
_ADMIN_DLQ_PREFIX_V2 = "/api/v1/admin/dlq"


def _admin_dlq_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=ADMIN_DLQ_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("admin", "dlq"),
        response_model=response_model,
        replaces_builtin_row_id=ADMIN_DLQ_HTTP_ROUTES_ROW_V2,
    )


def admin_dlq_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``admin-dlq`` inventory row."""
    messages = f"{_ADMIN_DLQ_PREFIX_V2}/messages"
    return (
        _admin_dlq_route_v2(
            path=messages,
            methods=("GET",),
            endpoint=list_messages,
            name="list_messages",
            response_model=DLQListResponse,
        ),
        _admin_dlq_route_v2(
            path=f"{messages}/{{message_id}}",
            methods=("GET",),
            endpoint=get_message,
            name="get_message",
            response_model=DLQMessageResponse,
        ),
        _admin_dlq_route_v2(
            path=f"{messages}/{{message_id}}/retry",
            methods=("POST",),
            endpoint=retry_message,
            name="retry_message",
            response_model=dict[str, Any],
        ),
        _admin_dlq_route_v2(
            path=f"{messages}/retry",
            methods=("POST",),
            endpoint=retry_messages,
            name="retry_messages",
            response_model=RetryResponse,
        ),
        _admin_dlq_route_v2(
            path=f"{messages}/{{message_id}}",
            methods=("DELETE",),
            endpoint=discard_message,
            name="discard_message",
            response_model=dict[str, Any],
        ),
        _admin_dlq_route_v2(
            path=f"{messages}/discard",
            methods=("POST",),
            endpoint=discard_messages,
            name="discard_messages",
            response_model=DiscardResponse,
        ),
        _admin_dlq_route_v2(
            path=f"{_ADMIN_DLQ_PREFIX_V2}/stats",
            methods=("GET",),
            endpoint=get_stats,
            name="get_stats",
            response_model=DLQStatsResponse,
        ),
        _admin_dlq_route_v2(
            path=f"{_ADMIN_DLQ_PREFIX_V2}/cleanup/expired",
            methods=("POST",),
            endpoint=cleanup_expired,
            name="cleanup_expired",
            response_model=CleanupResponse,
        ),
        _admin_dlq_route_v2(
            path=f"{_ADMIN_DLQ_PREFIX_V2}/cleanup/resolved",
            methods=("POST",),
            endpoint=cleanup_resolved,
            name="cleanup_resolved",
            response_model=CleanupResponse,
        ),
    )


def builtin_admin_dlq_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the admin DLQ row as reversible route effects of one V2 Fiber."""
    definitions = admin_dlq_route_definitions_v2()

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

        await context.effect(setup, label=ADMIN_DLQ_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=ADMIN_DLQ_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ADMIN_DLQ_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "ADMIN_DLQ_HTTP_ROUTES_ENTRY_V2",
    "ADMIN_DLQ_HTTP_ROUTES_MODULE_V2",
    "ADMIN_DLQ_HTTP_ROUTES_ROW_V2",
    "admin_dlq_route_definitions_v2",
    "builtin_admin_dlq_http_routes_definition_v2",
]
