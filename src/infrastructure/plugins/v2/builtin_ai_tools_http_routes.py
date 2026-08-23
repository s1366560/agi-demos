"""V2-owned production contribution for the lightweight AI-tools HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.infrastructure.adapters.primary.web.ai_tool_application_authority_v2 import (
    ai_tool_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.ai_tools import (
    OptimizeResponse,
    TitleResponse,
    generate_title,
    optimize_content,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AI_TOOLS_HTTP_ROUTES_ENTRY_V2 = "builtin-ai-tools-http-routes"
AI_TOOLS_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/ai-tools-routes"
AI_TOOLS_HTTP_ROUTES_ROW_V2 = "ai-tools"


def ai_tool_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``ai-tools`` inventory row."""
    prefix = "/api/v1/ai"
    return (
        RouteDefinitionV2(
            owner_entry_id=AI_TOOLS_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/optimize",
            methods=("POST",),
            endpoint=optimize_content,
            name="optimize_content",
            tags=("ai",),
            response_model=OptimizeResponse,
            replaces_builtin_row_id=AI_TOOLS_HTTP_ROUTES_ROW_V2,
        ),
        RouteDefinitionV2(
            owner_entry_id=AI_TOOLS_HTTP_ROUTES_ENTRY_V2,
            path=f"{prefix}/generate-title",
            methods=("POST",),
            endpoint=generate_title,
            name="generate_title",
            tags=("ai",),
            response_model=TitleResponse,
            replaces_builtin_row_id=AI_TOOLS_HTTP_ROUTES_ROW_V2,
        ),
    )


def builtin_ai_tools_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register lightweight AI-tool routes as one reversible V2 effect."""
    definitions = ai_tool_route_definitions_v2()

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

        await context.effect(setup, label=AI_TOOLS_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=AI_TOOLS_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AI_TOOLS_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AI_TOOLS_HTTP_ROUTES_ENTRY_V2",
    "AI_TOOLS_HTTP_ROUTES_MODULE_V2",
    "AI_TOOLS_HTTP_ROUTES_ROW_V2",
    "ai_tool_application_authority_dependency_v2",
    "ai_tool_route_definitions_v2",
    "builtin_ai_tools_http_routes_definition_v2",
]
