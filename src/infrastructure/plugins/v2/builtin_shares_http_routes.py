"""V2-owned production contribution for the builtin shares HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.routers.shares import (
    create_share,
    delete_share,
    get_shared_memory,
    list_shares,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SHARES_HTTP_ROUTES_ENTRY_V2 = "builtin-shares-http-routes"
SHARES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/shares-routes"
SHARES_HTTP_ROUTES_ROW_V2 = "shares"
_SHARES_TAGS_V2 = ("shares",)


def _shares_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    response_model: object | None,
    status_code: int | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=SHARES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=_SHARES_TAGS_V2,
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=SHARES_HTTP_ROUTES_ROW_V2,
    )


def shares_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return all four routes explicitly claimed from the ``shares`` inventory row."""
    memory_shares = "/api/v1/memories/{memory_id}/shares"
    return (
        _shares_route_v2(
            path=memory_shares,
            methods=("POST",),
            endpoint=create_share,
            name="create_share",
            response_model=dict[str, Any],
            status_code=201,
        ),
        _shares_route_v2(
            path=memory_shares,
            methods=("GET",),
            endpoint=list_shares,
            name="list_shares",
            response_model=dict[str, Any],
        ),
        _shares_route_v2(
            path=f"{memory_shares}/{{share_id}}",
            methods=("DELETE",),
            endpoint=delete_share,
            name="delete_share",
            response_model=None,
        ),
        _shares_route_v2(
            path="/api/v1/shared/{share_token}",
            methods=("GET",),
            endpoint=get_shared_memory,
            name="get_shared_memory",
            response_model=dict[str, Any],
        ),
    )


def builtin_shares_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register the shares row as reversible route effects of one V2 Fiber."""
    definitions = shares_route_definitions_v2()

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

        await context.effect(setup, label=SHARES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=SHARES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SHARES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "SHARES_HTTP_ROUTES_ENTRY_V2",
    "SHARES_HTTP_ROUTES_MODULE_V2",
    "SHARES_HTTP_ROUTES_ROW_V2",
    "builtin_shares_http_routes_definition_v2",
    "shares_route_definitions_v2",
]
