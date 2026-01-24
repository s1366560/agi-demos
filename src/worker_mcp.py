"""MCP Temporal Worker entry point.

This script runs the MCP Temporal Worker to process MCP server workflows
and activities. It manages MCP subprocess lifecycle independently from
the API service, enabling horizontal scaling and fault tolerance.

Usage:
    python -m src.worker_mcp
    # or
    uv run python src/worker_mcp.py
"""

import asyncio
import logging
import os
import signal
import sys

# Add project root to path if running as script
sys.path.append(os.getcwd())

from temporalio.worker import Worker

from src.configuration.temporal_config import get_temporal_settings
from src.infrastructure.adapters.secondary.temporal.client import get_temporal_client
from src.infrastructure.adapters.secondary.temporal.mcp.activities import (
    call_mcp_tool_activity,
    cleanup_all_clients,
    start_mcp_server_activity,
    stop_mcp_server_activity,
)
from src.infrastructure.adapters.secondary.temporal.mcp.workflows import MCPServerWorkflow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("src.worker_mcp")

# Task queue for MCP workflows
MCP_TASK_QUEUE = os.getenv("MCP_TASK_QUEUE", "mcp-tasks")

# Global state
temporal_client = None
worker = None
shutdown_event = asyncio.Event()


async def main():
    """Main entry point for the MCP Worker."""
    global temporal_client, worker

    temporal_settings = get_temporal_settings()

    logger.info("=" * 60)
    logger.info("Starting MemStack MCP Worker")
    logger.info("=" * 60)
    logger.info(f"Temporal Host: {temporal_settings.temporal_host}")
    logger.info(f"Temporal Namespace: {temporal_settings.temporal_namespace}")
    logger.info(f"Task Queue: {MCP_TASK_QUEUE}")
    logger.info("=" * 60)

    try:
        # Connect to Temporal
        temporal_client = await get_temporal_client()
        logger.info("Connected to Temporal server")

        # Create worker
        worker = Worker(
            temporal_client,
            task_queue=MCP_TASK_QUEUE,
            workflows=[MCPServerWorkflow],
            activities=[
                start_mcp_server_activity,
                call_mcp_tool_activity,
                stop_mcp_server_activity,
            ],
            # Worker configuration
            max_concurrent_workflow_task_polls=10,
            max_concurrent_activity_task_polls=20,
            max_cached_workflows=50,
        )

        logger.info("MCP Worker created successfully")
        logger.info("  - Workflows: MCPServerWorkflow")
        logger.info("  - Activities: start_mcp_server, call_mcp_tool, stop_mcp_server")
        logger.info("  - Max concurrent workflows: 10")
        logger.info("  - Max concurrent activities: 20")
        logger.info("=" * 60)
        logger.info("MCP Worker is running. Press Ctrl+C to stop.")
        logger.info("=" * 60)

        # Run worker until shutdown
        async with worker:
            await shutdown_event.wait()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")

    except Exception as e:
        logger.exception(f"Worker error: {e}")
        raise

    finally:
        await shutdown()


async def shutdown():
    """Graceful shutdown."""
    global worker, temporal_client

    logger.info("Shutting down MCP Worker...")

    # Cleanup all MCP clients
    logger.info("Cleaning up MCP clients...")
    await cleanup_all_clients()

    # Close Temporal client
    if temporal_client:
        try:
            # Note: Temporal client doesn't have a close method in the Python SDK
            # The connection is managed by the worker context manager
            pass
        except Exception as e:
            logger.error(f"Error closing Temporal client: {e}")

    logger.info("MCP Worker shutdown complete")


def handle_signal(sig, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {sig}")
    shutdown_event.set()


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Run the worker
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
