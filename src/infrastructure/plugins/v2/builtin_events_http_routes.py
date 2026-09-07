"""V2-owned production contribution for the events HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.configuration.features import require_feature
from src.infrastructure.adapters.primary.web.event_log_application_authority_v2 import (
    event_log_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.events import (
    EventLogListResponse,
    get_event_service,
    get_selected_event_tenant,
    list_event_types,
    list_events,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

EVENTS_HTTP_ROUTES_ENTRY_V2 = "builtin-events-http-routes"
EVENTS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/events-routes"
EVENTS_HTTP_ROUTES_ROW_V2 = "events"
EVENTS_FEATURE_DEPENDENCY_V2 = require_feature("events")


def event_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``events`` inventory row."""
    prefix = "/api/v1/events"
    dependencies = (EVENTS_FEATURE_DEPENDENCY_V2,)
    return (
        RouteDefinitionV2(
            owner_entry_id=EVENTS_HTTP_ROUTES_ENTRY_V2,
            path=prefix,
            methods=("GET",),
            endpoint=list_events,
            name="list_events",
            dependencies=dependencies,
            tags=("events",),
            response_model=EventLogListResponse,
            replaces_builtin_row_id=EVENTS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=EVENTS_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/types",
            methods=("GET",),
            endpoint=list_event_types,
            name="list_event_types",
            dependencies=dependencies,
            tags=("events",),
            response_model=list[str],
            replaces_builtin_row_id=EVENTS_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_events_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register event-log query routes as one reversible V2 effect."""
    definitions = event_route_definitions_v2()

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

        await context.effect(setup, label=EVENTS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=EVENTS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(EVENTS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "EVENTS_FEATURE_DEPENDENCY_V2",
    "EVENTS_HTTP_ROUTES_ENTRY_V2",
    "EVENTS_HTTP_ROUTES_MODULE_V2",
    "EVENTS_HTTP_ROUTES_ROW_V2",
    "builtin_events_http_routes_definition_v2",
    "event_log_application_authority_dependency_v2",
    "event_route_definitions_v2",
    "get_event_service",
    "get_selected_event_tenant",
]
