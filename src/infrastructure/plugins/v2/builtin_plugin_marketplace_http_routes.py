"""V2-owned production contributions for the builtin plugin marketplace HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi.routing import APIRoute

from src.application.schemas.plugin_marketplace import (
    MarketplacePackageApprovalResponse,
    MarketplacePackageCatalogEntry,
    MarketplacePackageDetailResponse,
    MarketplacePackageResponse,
    MarketplacePackageRevocationResponse,
    MarketplacePackageUninstallResponse,
)
from src.infrastructure.adapters.primary.web.routers.plugin_marketplace import (
    approve_package,
    get_package,
    install_package,
    list_packages,
    revoke_package,
    uninstall_package,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

PLUGIN_MARKETPLACE_HTTP_ROUTES_ENTRY_V2 = "builtin-plugin-marketplace-http-routes"
PLUGIN_MARKETPLACE_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/plugin-marketplace-routes"
PLUGIN_MARKETPLACE_HTTP_ROUTES_ROW_V2 = "plugin-marketplace"
_PLUGIN_MARKETPLACE_PREFIX_V2 = "/api/v1/plugin-marketplace/packages"


def _plugin_marketplace_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=PLUGIN_MARKETPLACE_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("Plugin Marketplace",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=PLUGIN_MARKETPLACE_HTTP_ROUTES_ROW_V2,
    )


def plugin_marketplace_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``plugin-marketplace`` inventory row."""
    prefix = _PLUGIN_MARKETPLACE_PREFIX_V2
    from src.infrastructure.adapters.primary.web.routers.plugin_marketplace_v3 import router

    unified_routes = tuple(
        _plugin_marketplace_route_v2(
            path=route.path,
            methods=tuple(sorted(route.methods)),
            endpoint=route.endpoint,
            name=route.name,
            response_model=route.response_model,
            status_code=route.status_code,
        )
        for route in router.routes
        if isinstance(route, APIRoute)
    )
    return (
        *unified_routes,
        _plugin_marketplace_route_v2(
            path=prefix,
            methods=("GET",),
            endpoint=list_packages,
            name="list_packages",
            response_model=list[MarketplacePackageCatalogEntry],
        ),
        _plugin_marketplace_route_v2(
            path=f"{prefix}/{{plugin_id}}",
            methods=("GET",),
            endpoint=get_package,
            name="get_package",
            response_model=MarketplacePackageDetailResponse,
        ),
        _plugin_marketplace_route_v2(
            path=f"{prefix}/{{plugin_id}}/install",
            methods=("POST",),
            endpoint=install_package,
            name="install_package",
            response_model=MarketplacePackageResponse,
            status_code=202,
        ),
        _plugin_marketplace_route_v2(
            path=f"{prefix}/{{plugin_id}}/approve",
            methods=("POST",),
            endpoint=approve_package,
            name="approve_package",
            response_model=MarketplacePackageApprovalResponse,
        ),
        _plugin_marketplace_route_v2(
            path=f"{prefix}/{{plugin_id}}/revoke",
            methods=("POST",),
            endpoint=revoke_package,
            name="revoke_package",
            response_model=MarketplacePackageRevocationResponse,
        ),
        _plugin_marketplace_route_v2(
            path=f"{prefix}/{{plugin_id}}/uninstall",
            methods=("POST",),
            endpoint=uninstall_package,
            name="uninstall_package",
            response_model=MarketplacePackageUninstallResponse,
        ),
    )


def builtin_plugin_marketplace_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register marketplace routes as reversible effects of one V2 Fiber."""
    definitions = plugin_marketplace_route_definitions_v2()

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

        await context.effect(setup, label=PLUGIN_MARKETPLACE_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=PLUGIN_MARKETPLACE_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(PLUGIN_MARKETPLACE_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "PLUGIN_MARKETPLACE_HTTP_ROUTES_ENTRY_V2",
    "PLUGIN_MARKETPLACE_HTTP_ROUTES_MODULE_V2",
    "PLUGIN_MARKETPLACE_HTTP_ROUTES_ROW_V2",
    "builtin_plugin_marketplace_http_routes_definition_v2",
    "plugin_marketplace_route_definitions_v2",
]
