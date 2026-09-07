"""V2-owned production contribution for the recall HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.graph_application_authority_v2 import (
    graph_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.recall import (
    ShortTermRecallResponse,
    short_term_recall,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

RECALL_HTTP_ROUTES_ENTRY_V2 = "builtin-recall-http-routes"
RECALL_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/recall-routes"
RECALL_HTTP_ROUTES_ROW_V2 = "recall"


def recall_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``recall`` inventory row."""
    return (
        RouteDefinitionV2(
            owner_entry_id=RECALL_HTTP_ROUTES_ENTRY_V2,
            path="/api/v1/recall/short",
            methods=("POST",),
            endpoint=short_term_recall,
            name="short_term_recall",
            tags=("recall",),
            response_model=ShortTermRecallResponse,
            replaces_builtin_row_id=RECALL_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_recall_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register recall routes as reversible effects of one V2 Fiber."""
    definitions = recall_route_definitions_v2()

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

        await context.effect(setup, label=RECALL_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=RECALL_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(RECALL_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "RECALL_HTTP_ROUTES_ENTRY_V2",
    "RECALL_HTTP_ROUTES_MODULE_V2",
    "RECALL_HTTP_ROUTES_ROW_V2",
    "builtin_recall_http_routes_definition_v2",
    "get_current_user",
    "graph_application_authority_dependency_v2",
    "recall_route_definitions_v2",
    "short_term_recall",
]
