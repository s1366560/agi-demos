"""V2-owned production contributions for the memories HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import status

from src.infrastructure.adapters.primary.web.routers.memories import (
    MemoryListResponse,
    MemoryResponse,
    create_memory,
    delete_memory,
    extract_entities,
    extract_relationships,
    get_memory,
    list_memories,
    reprocess_memory,
    update_memory,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

MEMORIES_HTTP_ROUTES_ENTRY_V2 = "builtin-memories-http-routes"
MEMORIES_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/memories-routes"
MEMORIES_HTTP_ROUTES_ROW_V2 = "memories"


def _memories_route_v2(
    *,
    path: str,
    methods: tuple[str, ...],
    endpoint: Callable[..., Any],
    name: str,
    status_code: int | None = None,
    response_model: object | None = None,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=MEMORIES_HTTP_ROUTES_ENTRY_V2,
        path=path,
        methods=methods,
        endpoint=endpoint,
        name=name,
        tags=("memories",),
        status_code=status_code,
        response_model=response_model,
        replaces_builtin_row_id=MEMORIES_HTTP_ROUTES_ROW_V2,
    )


def memories_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``memories`` inventory row."""
    memory_path = "/api/v1/memories/{memory_id}"
    return (
        _memories_route_v2(
            path="/api/v1/memories/extract-entities",
            methods=("POST",),
            endpoint=extract_entities,
            name="extract_entities",
            response_model=dict[str, Any],
        ),
        _memories_route_v2(
            path="/api/v1/memories/extract-relationships",
            methods=("POST",),
            endpoint=extract_relationships,
            name="extract_relationships",
            response_model=dict[str, Any],
        ),
        _memories_route_v2(
            path="/api/v1/memories/",
            methods=("POST",),
            endpoint=create_memory,
            name="create_memory",
            status_code=status.HTTP_201_CREATED,
            response_model=MemoryResponse,
        ),
        _memories_route_v2(
            path="/api/v1/memories/",
            methods=("GET",),
            endpoint=list_memories,
            name="list_memories",
            response_model=MemoryListResponse,
        ),
        _memories_route_v2(
            path=memory_path,
            methods=("GET",),
            endpoint=get_memory,
            name="get_memory",
            response_model=MemoryResponse,
        ),
        _memories_route_v2(
            path=memory_path,
            methods=("DELETE",),
            endpoint=delete_memory,
            name="delete_memory",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _memories_route_v2(
            path=f"{memory_path}/reprocess",
            methods=("POST",),
            endpoint=reprocess_memory,
            name="reprocess_memory",
            response_model=MemoryResponse,
        ),
        _memories_route_v2(
            path=memory_path,
            methods=("PATCH",),
            endpoint=update_memory,
            name="update_memory",
            response_model=MemoryResponse,
        ),
    )


def builtin_memories_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register memories routes as reversible effects of one V2 Fiber."""
    definitions = memories_route_definitions_v2()

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

        await context.effect(setup, label=MEMORIES_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=MEMORIES_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(MEMORIES_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "MEMORIES_HTTP_ROUTES_ENTRY_V2",
    "MEMORIES_HTTP_ROUTES_MODULE_V2",
    "MEMORIES_HTTP_ROUTES_ROW_V2",
    "builtin_memories_http_routes_definition_v2",
    "memories_route_definitions_v2",
]
