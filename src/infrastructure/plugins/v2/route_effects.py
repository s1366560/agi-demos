"""Fiber-owned route contribution definitions for protocol v2 staging."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error

ROUTE_TABLE_BUILDER_SERVICE_V2 = "service:http.route-table-builder"
ROUTE_TABLE_BUILDER_INJECT_V2 = "route_table"
ROUTE_TABLE_BUILDER_MODULE_V2 = "builtin://memstack/http/route-table-builder"


def route_table_builder_definition_v2(
    *,
    module_ref: str = ROUTE_TABLE_BUILDER_MODULE_V2,
    builder: RouteTableBuilderV2 | None = None,
) -> PluginDefinitionV2:
    """Provide one builder owned by the staging generation's provider Fiber."""

    def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        _ = context.provide(
            ROUTE_TABLE_BUILDER_SERVICE_V2,
            builder or RouteTableBuilderV2(),
            label="route-table-builder",
        )

    return PluginDefinitionV2(
        module_ref=module_ref,
        apply=apply,
        provides=(ROUTE_TABLE_BUILDER_SERVICE_V2,),
    )


def route_contribution_definition_v2(
    *,
    module_ref: str,
    routes: Sequence[RouteDefinitionV2],
) -> PluginDefinitionV2:
    """Contribute static routes as reversible effects of one plugin entry Fiber."""
    definitions = tuple(routes)

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        value = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(value, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )
        for definition in definitions:
            if definition.owner_entry_id != context.entry_id:
                raise RuntimeV2Error(
                    "route_owner_mismatch",
                    f"route {definition.name} is not owned by entry {context.entry_id}",
                )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(value.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label="http-route-contributions")

    return PluginDefinitionV2(module_ref=module_ref, apply=apply)


__all__ = [
    "ROUTE_TABLE_BUILDER_INJECT_V2",
    "ROUTE_TABLE_BUILDER_MODULE_V2",
    "ROUTE_TABLE_BUILDER_SERVICE_V2",
    "route_contribution_definition_v2",
    "route_table_builder_definition_v2",
]
