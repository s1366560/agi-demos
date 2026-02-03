"""Graph service initialization for startup."""

import logging
from typing import Any

from src.configuration.factories import create_native_graph_adapter

logger = logging.getLogger(__name__)


async def initialize_graph_service() -> Any:
    """
    Initialize NativeGraphAdapter (self-developed knowledge graph engine).

    Returns:
        The initialized graph service.

    Raises:
        Exception: If Neo4j is not available or initialization fails.
    """
    logger.info("Creating NativeGraphAdapter...")
    try:
        graph_service = await create_native_graph_adapter()
        logger.info("NativeGraphAdapter created successfully")
        return graph_service
    except Exception as e:
        logger.error(f"Failed to create NativeGraphAdapter: {e}")
        logger.error("Neo4j is required for MemStack to function. Please ensure Neo4j is running.")
        raise


async def shutdown_graph_service(graph_service: Any) -> None:
    """Shutdown graph service and close Neo4j connection."""
    if hasattr(graph_service, "client") and hasattr(graph_service.client, "close"):
        await graph_service.client.close()
        logger.info("Neo4j connection closed")
