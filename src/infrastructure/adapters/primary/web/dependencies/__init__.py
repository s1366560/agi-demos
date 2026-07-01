# FastAPI dependencies for authentication

import logging
from inspect import isawaitable
from typing import cast

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.services.graph_service_port import GraphServicePort
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
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.adapters.secondary.persistence.sql_graph_store_repository import (
    SqlGraphStoreRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_retrieval_store_repository import (
    SqlRetrievalStoreRepository,
)
from src.infrastructure.graph.backend_factory import build_default_factory
from src.infrastructure.graph.registry import (
    get_env_default_store,
    get_graph_backend_registry,
)
from src.infrastructure.retrieval.backend_factory import build_default_retrieval_factory
from src.infrastructure.retrieval.registry import (
    get_env_default_retrieval_store,
    get_retrieval_backend_registry,
)

logger = logging.getLogger(__name__)


def get_neo4j_client(request: Request) -> None:
    """Get Neo4j client from app state for direct graph queries."""
    try:
        return cast(None, request.app.state.container.neo4j_client)
    except Exception:
        logger.warning("Failed to get neo4j_client from container")
        return None


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


def get_graph_service(request: Request) -> None:
    """Get GraphServicePort (NativeGraphAdapter) from app state.

    This provides the adapter layer that handles knowledge graph operations
    including entity extraction, search, and community detection.
    """
    try:
        return cast(None, request.app.state.container.graph_service)
    except Exception:
        logger.warning("Failed to get graph_service from container")
        return None


def get_graphiti_client(request: Request) -> GraphServicePort | None:
    """Legacy dependency returning the native graph service.

    Older routes still refer to this as a Graphiti client, but the runtime graph
    implementation is NativeGraphAdapter. It exposes the direct driver for
    compatibility with legacy read/query routes.
    """
    return cast(GraphServicePort | None, get_graph_service(request))


def _request_project_id(request: Request) -> str | None:
    raw = request.path_params.get("project_id") or request.query_params.get("project_id")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


async def get_graph_store(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> GraphStorePort | None:
    """Get the ``GraphStorePort`` (pluggable graph backend) from app state.

    If a project_id is present in the path/query, resolve that project's
    ``graph_store_id`` through the registry. Null bindings fall back to the env
    default singleton registered at startup.
    """
    try:
        project_id = _request_project_id(request)
        if project_id:
            result = await db.execute(
                refresh_select_statement(
                    select(Project.graph_store_id).where(Project.id == project_id)
                )
            )
            store_id = result.scalar_one_or_none()
            if store_id:
                registry = get_graph_backend_registry()
                registered = registry.get_by_store_id(store_id)
                if registered is not None:
                    return cast(GraphStorePort, registered)
                tenant_result = await db.execute(
                    refresh_select_statement(
                        select(Project.tenant_id).where(Project.id == project_id)
                    )
                )
                tenant_id = tenant_result.scalar_one_or_none()
                if tenant_id:
                    graph_store = await SqlGraphStoreRepository(db).find_by_id(tenant_id, store_id)
                    if graph_store is not None:
                        built = build_default_factory().build(graph_store)
                        if isawaitable(built):
                            built = await built
                        registry.register_store(store_id, built)
                        return cast(GraphStorePort, built)
        default_store = get_env_default_store()
        if default_store is not None:
            return cast(GraphStorePort, default_store)
        store = request.app.state.container.graph_service
        return cast(GraphStorePort | None, store)
    except Exception:
        logger.warning("Failed to get graph_store from container")
        return None


async def get_retrieval_store(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RetrievalStorePort | None:
    """Resolve the project-bound retrieval backend, or env default."""
    try:
        project_id = _request_project_id(request)
        if project_id:
            result = await db.execute(
                refresh_select_statement(
                    select(Project.tenant_id, Project.retrieval_store_id).where(
                        Project.id == project_id
                    )
                )
            )
            row = result.first()
            row_data = row._mapping if row else {}
            retrieval_store_id = row_data.get("retrieval_store_id")
            tenant_id = row_data.get("tenant_id")
            if retrieval_store_id and tenant_id:
                registry = get_retrieval_backend_registry()
                registered = registry.get_by_store_id(retrieval_store_id)
                if registered is not None:
                    return cast(RetrievalStorePort, registered)
                retrieval_store = await SqlRetrievalStoreRepository(db).find_by_id(
                    tenant_id,
                    retrieval_store_id,
                )
                if retrieval_store is not None:
                    built = build_default_retrieval_factory().build(retrieval_store)
                    registry.register_store(retrieval_store_id, built)
                    return cast(RetrievalStorePort, built)
        default_store = get_env_default_retrieval_store()
        return cast(RetrievalStorePort | None, default_store)
    except Exception:
        logger.warning("Failed to get retrieval_store from registry")
        return None


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
