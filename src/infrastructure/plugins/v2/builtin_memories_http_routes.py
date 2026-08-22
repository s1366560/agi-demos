"""V2-owned production contributions for the memories HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, cast

from fastapi import BackgroundTasks, Depends, Query, status
from fastapi.responses import JSONResponse, Response

from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
    MemoryApplicationAuthorityV2,
    memory_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.memories import (
    MemoryCreate,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdate,
    create_memory as _create_memory,
    delete_memory as _delete_memory,
    extract_entities as _extract_entities,
    extract_relationships as _extract_relationships,
    get_memory as _get_memory,
    list_memories as _list_memories,
    reprocess_memory as _reprocess_memory,
    update_memory as _update_memory,
)
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User

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


async def extract_entities_v2(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    return await _extract_entities(payload, current_user, memory_application)


async def extract_relationships_v2(
    payload: dict[str, Any],
    current_user: User = Depends(get_current_user),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> dict[str, Any]:
    return await _extract_relationships(payload, current_user, memory_application)


async def create_memory_v2(
    memory_data: MemoryCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
    workflow_engine: WorkflowEnginePort = Depends(workflow_engine_authority_dependency_v2),
) -> MemoryResponse:
    """Create a new memory.

    This endpoint stores memory using a hybrid approach:
    1. Immediate storage in DB
    2. Asynchronous graph building via Graphiti for relationship extraction
    """
    return cast(
        MemoryResponse,
        await _create_memory(
            memory_data,
            background_tasks,
            current_user,
            memory_application,
            workflow_engine,
        ),
    )


async def list_memories_v2(
    project_id: str = Query(..., description="Project ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    search: str | None = Query(None, description="Search query"),
    content_type: Literal["text", "document", "image", "video"] | None = Query(
        None,
        description="Memory content type filter",
    ),
    current_user: User = Depends(get_current_user),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> MemoryListResponse:
    """List memories for a project."""
    return await _list_memories(
        project_id,
        page,
        page_size,
        search,
        content_type,
        current_user,
        memory_application,
    )


async def get_memory_v2(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> MemoryResponse:
    """Get a specific memory."""
    return cast(MemoryResponse, await _get_memory(memory_id, current_user, memory_application))


async def delete_memory_v2(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> JSONResponse | Response:
    """Delete a memory from all storage systems (DB, Graphiti)."""
    return await _delete_memory(memory_id, current_user, memory_application)


async def reprocess_memory_v2(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    workflow_engine: WorkflowEnginePort = Depends(workflow_engine_authority_dependency_v2),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> MemoryResponse:
    """Manually trigger re-processing of a memory."""
    return cast(
        MemoryResponse,
        await _reprocess_memory(
            memory_id,
            current_user,
            workflow_engine,
            memory_application,
        ),
    )


async def update_memory_v2(
    memory_id: str,
    memory_data: MemoryUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    workflow_engine: WorkflowEnginePort = Depends(workflow_engine_authority_dependency_v2),
    memory_application: MemoryApplicationAuthorityV2 = Depends(
        memory_application_authority_dependency_v2
    ),
) -> MemoryResponse:
    """Update an existing memory with optimistic locking."""
    return cast(
        MemoryResponse,
        await _update_memory(
            memory_id,
            memory_data,
            background_tasks,
            current_user,
            workflow_engine,
            memory_application,
        ),
    )


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
            endpoint=extract_entities_v2,
            name="extract_entities",
            response_model=dict[str, Any],
        ),
        _memories_route_v2(
            path="/api/v1/memories/extract-relationships",
            methods=("POST",),
            endpoint=extract_relationships_v2,
            name="extract_relationships",
            response_model=dict[str, Any],
        ),
        _memories_route_v2(
            path="/api/v1/memories/",
            methods=("POST",),
            endpoint=create_memory_v2,
            name="create_memory",
            status_code=status.HTTP_201_CREATED,
            response_model=MemoryResponse,
        ),
        _memories_route_v2(
            path="/api/v1/memories/",
            methods=("GET",),
            endpoint=list_memories_v2,
            name="list_memories",
            response_model=MemoryListResponse,
        ),
        _memories_route_v2(
            path=memory_path,
            methods=("GET",),
            endpoint=get_memory_v2,
            name="get_memory",
            response_model=MemoryResponse,
        ),
        _memories_route_v2(
            path=memory_path,
            methods=("DELETE",),
            endpoint=delete_memory_v2,
            name="delete_memory",
            status_code=status.HTTP_204_NO_CONTENT,
        ),
        _memories_route_v2(
            path=f"{memory_path}/reprocess",
            methods=("POST",),
            endpoint=reprocess_memory_v2,
            name="reprocess_memory",
            response_model=MemoryResponse,
        ),
        _memories_route_v2(
            path=memory_path,
            methods=("PATCH",),
            endpoint=update_memory_v2,
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
    "MemoryCreate",
    "MemoryListResponse",
    "MemoryResponse",
    "MemoryUpdate",
    "builtin_memories_http_routes_definition_v2",
    "create_memory_v2",
    "delete_memory_v2",
    "extract_entities_v2",
    "extract_relationships_v2",
    "get_memory_v2",
    "list_memories_v2",
    "memories_route_definitions_v2",
    "reprocess_memory_v2",
    "update_memory_v2",
]
