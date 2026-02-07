"""Temporal services initialization for startup."""

import logging
from typing import Any, Optional, Tuple

from src.infrastructure.adapters.secondary.temporal import TemporalWorkflowEngine
from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory

logger = logging.getLogger(__name__)


async def initialize_temporal_services() -> Tuple[Optional[Any], Optional[Any], Optional[Any]]:
    """
    Initialize Temporal Workflow Engine and MCP Adapter.

    Returns:
        Tuple of (temporal_client, workflow_engine, mcp_adapter).
        Any or all may be None if services are unavailable.
    """
    logger.info("Initializing Temporal Workflow Engine...")
    temporal_client = None
    workflow_engine = None
    mcp_adapter = None

    try:
        temporal_client = await TemporalClientFactory.get_client()
        workflow_engine = TemporalWorkflowEngine(client=temporal_client)
        logger.info("Temporal Workflow Engine initialized")
    except Exception as e:
        logger.warning(
            f"Failed to connect to Temporal server: {e}. Workflow engine will be unavailable."
        )

    # Initialize MCP Adapter (Ray or Local Fallback, independent of Temporal)
    try:
        from src.infrastructure.mcp.adapter_factory import create_mcp_adapter

        mcp_adapter = await create_mcp_adapter()
        logger.info("MCP Adapter initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to initialize MCP Adapter: {e}")

    return temporal_client, workflow_engine, mcp_adapter
