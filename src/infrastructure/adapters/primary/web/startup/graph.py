"""Graph service initialization for startup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from src.configuration.factories import create_native_graph_adapter

if TYPE_CHECKING:
    from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter

logger = logging.getLogger(__name__)


async def initialize_graph_service() -> NativeGraphAdapter:
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
        return cast("NativeGraphAdapter", graph_service)
    except Exception as e:
        logger.error(f"Failed to create NativeGraphAdapter: {e}")
        logger.error("Neo4j is required for MemStack to function. Please ensure Neo4j is running.")
        raise


async def shutdown_graph_service(graph_service: NativeGraphAdapter) -> None:
    """Shutdown graph service and close Neo4j connection."""
    if hasattr(graph_service, "client") and hasattr(graph_service.client, "close"):
        await graph_service.client.close()
        logger.info("Neo4j connection closed")
