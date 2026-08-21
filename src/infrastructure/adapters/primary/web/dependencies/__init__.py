# FastAPI dependencies for authentication

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Protocol, cast

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    create_api_key,
    create_user,
    generate_api_key,
    get_api_key_from_header,
    get_api_key_from_header_or_query,
    get_current_actor,
    get_current_user,
    get_current_user_from_header_or_query,
    get_current_user_tenant,
    get_password_hash,
    hash_api_key,
    initialize_default_credentials,
    security,
    verify_api_key,
    verify_api_key_dependency,
    verify_api_key_from_header_or_query,
    verify_password,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.graph.registry import ENV_STORE_ID_PREFIX
from src.infrastructure.plugins.v2.backend_store_services import BackendStoreServicesV2
from src.infrastructure.plugins.v2.boundary import current_generation_v2
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_SERVICE_V2,
    GraphRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.retrieval_runtime import (
    RETRIEVAL_RUNTIME_SERVICE_V2,
    RetrievalRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


class _BackendStoreAuthorityProtocolV2(Protocol):
    """Cycle-free structural view of the canonical backend-store authority."""

    db: AsyncSession
    services: BackendStoreServicesV2


async def _backend_store_authority_dependency_proxy_v2(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[_BackendStoreAuthorityProtocolV2]:
    """Lazily enter the canonical authority without an import cycle."""
    from src.infrastructure.adapters.primary.web.backend_store_authority_v2 import (
        backend_store_authority_dependency_v2,
    )

    dependency = cast(
        AsyncGenerator[_BackendStoreAuthorityProtocolV2, None],
        backend_store_authority_dependency_v2(
            request=request,
            current_user=current_user,
            db=db,
        ),
    )
    try:
        yield await anext(dependency)
    finally:
        await dependency.aclose()


logger = logging.getLogger(__name__)


def get_neo4j_client(_request: Request) -> object | None:
    """Resolve direct graph-driver access from the request's generation."""
    graph_service = _graph_runtime_v2().graph_service
    return getattr(graph_service, "client", None)


def get_workflow_engine(request: Request) -> None:
    """Get WorkflowEngine from app state.

    Returns the Temporal WorkflowEngine for submitting workflow tasks.
    """
    try:
        app = request.app
        state = app.state
    except AttributeError as e:
        logger.critical(
            "Application state is not properly configured for workflow engine. "
            "Ensure app.state and workflow_engine are initialized during app startup.",
            exc_info=True,
        )
        raise RuntimeError(
            "Workflow engine not initialized. Cannot process workflow requests."
        ) from e

    if not hasattr(state, "workflow_engine"):
        logger.critical(
            "Workflow engine not available in app state. "
            "Ensure workflow_engine is initialized during app startup."
        )
        raise RuntimeError("Workflow engine not initialized. Cannot process workflow requests.")

    return cast(None, state.workflow_engine)


def _graph_runtime_v2() -> GraphRuntimeServiceV2:
    runtime = current_generation_v2().resolve(
        GRAPH_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(runtime, GraphRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_graph_runtime",
            "pinned generation has an invalid graph runtime service",
        )
    return runtime


def _retrieval_runtime_v2() -> RetrievalRuntimeServiceV2:
    runtime = current_generation_v2().resolve(
        RETRIEVAL_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(runtime, RetrievalRuntimeServiceV2):
        raise RuntimeV2Error(
            "invalid_retrieval_runtime",
            "pinned generation has an invalid env retrieval runtime service",
        )
    return runtime


def get_graph_service(_request: Request) -> GraphStorePort | None:
    """Resolve the optional graph resource from the pinned V2 generation."""
    return _graph_runtime_v2().graph_service


def get_graphiti_client(request: Request) -> GraphStorePort | None:
    """Legacy dependency returning the native graph service.

    Older routes still refer to this as a Graphiti client, but the runtime graph
    implementation is NativeGraphAdapter. It exposes the direct driver for
    compatibility with legacy read/query routes.
    """
    return get_graph_service(request)


def _request_project_id(request: Request) -> str | None:
    raw = request.path_params.get("project_id") or request.query_params.get("project_id")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


async def get_graph_store(
    request: Request,
    backend_store: _BackendStoreAuthorityProtocolV2 = Depends(
        _backend_store_authority_dependency_proxy_v2
    ),
) -> GraphStorePort | None:
    """Get the ``GraphStorePort`` from the request's pinned generation.

    If a project_id is present in the path/query, resolve that project's
    persisted ``graph_store_id`` through the V2 application service. Null and
    environment bindings resolve to the generation-owned graph resource.
    """
    project_id = _request_project_id(request)
    if project_id:
        result = await backend_store.db.execute(
            refresh_select_statement(
                select(Project.tenant_id, Project.graph_store_id).where(Project.id == project_id)
            )
        )
        row = result.first()
        tenant_id = str(row[0]) if row is not None else None
        store_id = str(row[1]) if row is not None and row[1] else None
        if tenant_id and store_id:
            if store_id.startswith(ENV_STORE_ID_PREFIX):
                return get_graph_service(request)
            return await backend_store.services.graph_service.resolve_backend(
                tenant_id,
                store_id,
            )
    return get_graph_service(request)


async def get_retrieval_store(
    request: Request,
    backend_store: _BackendStoreAuthorityProtocolV2 = Depends(
        _backend_store_authority_dependency_proxy_v2
    ),
) -> RetrievalStorePort | None:
    """Resolve the project-bound retrieval backend, or env default."""
    project_id = _request_project_id(request)
    if project_id:
        result = await backend_store.db.execute(
            refresh_select_statement(
                select(Project.tenant_id, Project.retrieval_store_id).where(
                    Project.id == project_id
                )
            )
        )
        row = result.first()
        tenant_id = str(row[0]) if row is not None else None
        retrieval_store_id = str(row[1]) if row is not None and row[1] else None
        if retrieval_store_id and tenant_id:
            return await backend_store.services.retrieval_service.resolve_backend(
                tenant_id,
                retrieval_store_id,
            )
    return _retrieval_runtime_v2().retrieval_store


__all__ = [
    "create_api_key",
    "create_user",
    "generate_api_key",
    "get_api_key_from_header",
    "get_api_key_from_header_or_query",
    "get_current_actor",
    "get_current_user",
    "get_current_user_from_header_or_query",
    "get_current_user_tenant",
    "get_db",
    "get_graph_service",
    "get_graph_store",
    "get_graphiti_client",  # Legacy alias
    "get_neo4j_client",
    "get_password_hash",
    "get_retrieval_store",
    "get_workflow_engine",
    "hash_api_key",
    "initialize_default_credentials",
    "security",
    "verify_api_key",
    "verify_api_key_dependency",
    "verify_api_key_from_header_or_query",
    "verify_password",
]
