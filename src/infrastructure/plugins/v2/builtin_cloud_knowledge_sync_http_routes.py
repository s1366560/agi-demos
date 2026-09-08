"""Optional V2 route contribution for explicit cloud synchronization enrollment."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi.routing import APIRoute

from src.infrastructure.adapters.primary.web.routers.cloud_knowledge_sync import (
    create_cloud_knowledge_sync_router,
)

from .cloud_knowledge_sync_services import CloudKnowledgeSyncResolverProtocolV2
from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2 = "builtin-cloud-knowledge-sync-http-routes"
CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2 = "builtin://memstack/http/cloud-knowledge-sync-routes"


def cloud_knowledge_sync_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    router = create_cloud_knowledge_sync_router()
    return tuple(
        RouteDefinitionV2(
            owner_entry_id=CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2,
            path=f"/api/v1{route.path}",
            methods=tuple(sorted(route.methods)),
            endpoint=route.endpoint,
            name=route.name,
            dependencies=tuple(route.dependencies),
            tags=("knowledge-sync",),
            response_model=route.response_model,
            status_code=route.status_code,
        )
        for route in router.routes
        if isinstance(route, APIRoute)
    )


def builtin_cloud_knowledge_sync_http_routes_definition_v2() -> PluginDefinitionV2:
    definitions = cloud_knowledge_sync_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error("invalid_route_table_builder", "cloud sync requires route table")
        if not isinstance(context.require("application"), CloudKnowledgeSyncResolverProtocolV2):
            raise RuntimeV2Error("invalid_cloud_sync_resolver", "cloud sync application is invalid")

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

        await context.effect(setup, label=CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2,
        contract_digest=generated_contract_digest_v2(CLOUD_KNOWLEDGE_SYNC_HTTP_MODULE_V2),
        apply=apply,
    )
