"""Temporal services initialization for startup."""

import logging
from typing import Any, Optional, Tuple

from src.infrastructure.adapters.secondary.temporal import TemporalWorkflowEngine
from src.infrastructure.adapters.secondary.temporal.client import TemporalClientFactory

logger = logging.getLogger(__name__)


async def initialize_temporal_services() -> Tuple[Optional[Any], Optional[Any]]:
    """
    Initialize Temporal Workflow Engine.

    Returns:
        Tuple of (temporal_client, workflow_engine).
        Either may be None if services are unavailable.
    """
    logger.info("Initializing Temporal Workflow Engine...")
    temporal_client = None
    workflow_engine = None

    try:
        temporal_client = await TemporalClientFactory.get_client()
        workflow_engine = TemporalWorkflowEngine(client=temporal_client)
        logger.info("Temporal Workflow Engine initialized")
    except Exception as e:
        logger.warning(
            f"Failed to connect to Temporal server: {e}. Workflow engine will be unavailable."
        )

    return temporal_client, workflow_engine
