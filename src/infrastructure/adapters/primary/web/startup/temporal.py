"""Temporal services initialization for startup."""

import logging
from typing import Any, Optional, Tuple

from src.infrastructure.adapters.secondary.temporal import TemporalWorkflowEngine
from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory

logger = logging.getLogger(__name__)


async def initialize_temporal_services() -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """
    Initialize Temporal Workflow Engine and MCP Temporal Adapter.

    Returns:
        Tuple of (temporal_client, workflow_engine, mcp_temporal_adapter).
        Any or all may be None if Temporal is unavailable.
    """
    logger.info("Initializing Temporal Workflow Engine...")
    temporal_client = None
    workflow_engine = None
    mcp_temporal_adapter = None

    try:
        temporal_client = await TemporalClientFactory.get_client()
        workflow_engine = TemporalWorkflowEngine(client=temporal_client)
        logger.info("Temporal Workflow Engine initialized")
    except Exception as e:
        logger.warning(
            f"Failed to connect to Temporal server: {e}. Workflow engine will be unavailable."
        )
        return None, None, None

    # Initialize MCP Temporal Adapter (if Temporal is available)
    logger.info(f"Checking Temporal client availability: {temporal_client is not None}")
    if temporal_client:
        try:
            from src.infrastructure.adapters.secondary.temporal.mcp.adapter import (
                MCPTemporalAdapter,
            )

            mcp_temporal_adapter = MCPTemporalAdapter(temporal_client)
            logger.info("MCP Temporal Adapter initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize MCP Temporal Adapter: {e}")

    return temporal_client, workflow_engine, mcp_temporal_adapter
