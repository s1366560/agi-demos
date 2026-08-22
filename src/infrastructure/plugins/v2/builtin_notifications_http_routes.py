"""V2-owned production contributions for the notifications HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.notification_application_authority_v2 import (
    notification_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.notifications import (
    create_notification,
    delete_notification,
    list_notifications,
    mark_all_read,
    mark_notification_read,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

NOTIFICATIONS_HTTP_ROUTES_ENTRY_V2 = "builtin-notifications-http-routes"
NOTIFICATIONS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/notifications-routes"
NOTIFICATIONS_HTTP_ROUTES_ROW_V2 = "notifications"


def _notification_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=NOTIFICATIONS_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("notifications",),
        response_model=dict[str, Any],
        replaces_builtin_row_id=NOTIFICATIONS_HTTP_ROUTES_ROW_V2,
    )


def notification_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``notifications`` inventory row."""
    prefix = "/api/v1/notifications"
    return (
        _notification_route_v2(
            path=f"{prefix}/",
            methods=("GET",),
            endpoint=list_notifications,
            name="list_notifications",
        ),
        _notification_route_v2(
            path=f"{prefix}/{{notification_id}}/read",
            methods=("PUT",),
            endpoint=mark_notification_read,
            name="mark_notification_read",
        ),
        _notification_route_v2(
            path=f"{prefix}/read-all",
            methods=("PUT",),
            endpoint=mark_all_read,
            name="mark_all_read",
        ),
        _notification_route_v2(
            path=f"{prefix}/{{notification_id}}",
            methods=("DELETE",),
            endpoint=delete_notification,
            name="delete_notification",
        ),
        _notification_route_v2(
            path=f"{prefix}/create",
            methods=("POST",),
            endpoint=create_notification,
            name="create_notification",
        ),
    )


def builtin_notifications_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register notification routes as reversible effects of one V2 Fiber."""
    definitions = notification_route_definitions_v2()

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

        await context.effect(setup, label=NOTIFICATIONS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=NOTIFICATIONS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(NOTIFICATIONS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "NOTIFICATIONS_HTTP_ROUTES_ENTRY_V2",
    "NOTIFICATIONS_HTTP_ROUTES_MODULE_V2",
    "NOTIFICATIONS_HTTP_ROUTES_ROW_V2",
    "builtin_notifications_http_routes_definition_v2",
    "get_current_user",
    "notification_application_authority_dependency_v2",
    "notification_route_definitions_v2",
]
