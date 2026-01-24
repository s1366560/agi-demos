# FastAPI dependencies for authentication

import logging

from fastapi import Request

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    create_api_key,
    create_user,
    generate_api_key,
    get_api_key_from_header,
    get_current_user,
    get_current_user_tenant,
    get_password_hash,
    hash_api_key,
    initialize_default_credentials,
    security,
    verify_api_key,
    verify_api_key_dependency,
    verify_password,
)

logger = logging.getLogger(__name__)


def get_neo4j_client(request: Request):
    """Get Neo4j client from app state for direct graph queries."""
    try:
        return request.app.state.container.neo4j_client
    except Exception:
        logger.warning("Failed to get neo4j_client from container")
        return None


def get_workflow_engine(request: Request):
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

    return state.workflow_engine


def get_graph_service(request: Request):
    """Get GraphServicePort (NativeGraphAdapter) from app state.

    This provides the adapter layer that handles knowledge graph operations
    including entity extraction, search, and community detection.
    """
    try:
        return request.app.state.container.graph_service
    except Exception:
        logger.warning("Failed to get graph_service from container")
        return None


# Legacy alias for backward compatibility
get_graphiti_client = get_neo4j_client


__all__ = [
    "generate_api_key",
    "hash_api_key",
    "verify_api_key",
    "verify_password",
    "get_password_hash",
    "get_api_key_from_header",
    "verify_api_key_dependency",
    "get_current_user",
    "get_current_user_tenant",
    "create_api_key",
    "create_user",
    "initialize_default_credentials",
    "security",
    "get_neo4j_client",
    "get_workflow_engine",
    "get_graph_service",
    "get_graphiti_client",  # Legacy alias
]
