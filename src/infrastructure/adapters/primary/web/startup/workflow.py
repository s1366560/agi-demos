"""Workflow engine initialization for startup."""

import logging

from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.secondary.workflow import AsyncioWorkflowEngine

logger = logging.getLogger(__name__)


async def initialize_workflow_engine() -> WorkflowEnginePort | None:
    """Initialize the asyncio-based workflow engine.

    Returns:
        WorkflowEnginePort instance.
    """
    logger.info("Initializing Asyncio Workflow Engine...")
    workflow_engine = AsyncioWorkflowEngine()
    logger.info("Asyncio Workflow Engine initialized")
    return workflow_engine
