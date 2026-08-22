"""V2-owned production contributions for the builtin system HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.system import (
    get_system_info as _get_system_info,
    list_features as _list_features,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SYSTEM_HTTP_ROUTES_ENTRY_V2 = "builtin-system-http-routes"
SYSTEM_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/system-routes"
SYSTEM_HTTP_ROUTES_ROW_V2 = "system"


async def list_system_features_v2(
    _current_user: Any = Depends(get_current_user),  # noqa: ANN401
) -> list[dict[str, Any]]:
    """Get list of all features and their enablement status."""
    return await _list_features(_current_user)


async def get_system_info_v2(
    _current_user: Any = Depends(get_current_user),  # noqa: ANN401
) -> dict[str, Any]:
    """Get system info including edition and features."""
    return await _get_system_info(_current_user)


def system_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``system`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=SYSTEM_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/system/features",
            methods=("GET",),
            endpoint=list_system_features_v2,
            name="list_features",
            tags=("System",),
            response_model=list[dict[str, Any]],
            replaces_builtin_row_id=SYSTEM_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=SYSTEM_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/system/info",
            methods=("GET",),
            endpoint=get_system_info_v2,
            name="get_system_info",
            tags=("System",),
            response_model=dict[str, Any],
            replaces_builtin_row_id=SYSTEM_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_system_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the system row as reversible route effects of one V2 Fiber."""
    definitions = system_route_definitions_v2()

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

        await context.effect(setup, label="builtin-system-http-routes")

    return PluginDefinitionV2(
        module_ref=SYSTEM_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SYSTEM_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SYSTEM_HTTP_ROUTES_ENTRY_V2",
    "SYSTEM_HTTP_ROUTES_MODULE_V2",
    "SYSTEM_HTTP_ROUTES_ROW_V2",
    "builtin_system_http_routes_definition_v2",
    "get_system_info_v2",
    "list_system_features_v2",
    "system_route_definitions_v2",
]
