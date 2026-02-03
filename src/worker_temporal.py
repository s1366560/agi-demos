"""Temporal Worker entry point for MemStack.

This script runs the Temporal Worker to process workflows and activities.
It replaces the Redis-based worker when USE_TEMPORAL_WORKFLOW is enabled.

Usage:
    python -m src.worker_temporal
    # or
    uv run python src/worker_temporal.py
"""

import asyncio
import logging
import os
import signal
import sys

# Add project root to path if running as script
sys.path.append(os.getcwd())

from temporalio.worker import Worker

from src.configuration.config import get_settings
from src.configuration.factories import create_native_graph_adapter
from src.configuration.temporal_config import get_temporal_settings
from src.infrastructure.adapters.secondary.persistence.database import engine
from src.infrastructure.adapters.secondary.persistence.models import Base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("src.worker_temporal")

settings = get_settings()
temporal_settings = get_temporal_settings()

# Global state
graph_service = None
temporal_client = None
worker = None


async def shutdown(signal_enum=None):
    """Cleanup tasks tied to the service's shutdown.

    Implements a two-phase shutdown:
    1. Stop worker (wait for in-flight tasks with timeout)
    2. Close resources in dependency order
    """
    global worker, temporal_client

    if signal_enum:
        logger.info(f"Received exit signal {signal_enum.name}...")

    logger.info("Shutting down Temporal worker...")

    # Phase 1: Shutdown worker with timeout
    if worker:
        try:
            await asyncio.wait_for(worker.shutdown(), timeout=30.0)
            logger.info("Temporal worker shutdown complete")
        except asyncio.TimeoutError:
            logger.warning("Worker shutdown timed out after 30s, forcing shutdown")
        except Exception as e:
            logger.warning(f"Error during worker shutdown: {e}")

    # Phase 2: Close resources in dependency order
    # Close graph service
    if graph_service and hasattr(graph_service, "close"):
        try:
            await asyncio.wait_for(graph_service.close(), timeout=10.0)
            logger.info("Graph service closed")
        except asyncio.TimeoutError:
            logger.warning("Graph service close timed out")
        except Exception as e:
            logger.warning(f"Error closing graph service: {e}")

    # Clear worker state
    from src.infrastructure.adapters.secondary.temporal.worker_state import clear_state

    clear_state()

    # Cancel remaining tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"Cancelling {len(tasks)} outstanding tasks")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("Temporal worker shutdown complete")

    try:
        loop = asyncio.get_running_loop()
        loop.stop()
    except RuntimeError:
        pass


async def main():
    """Main Temporal Worker entry point."""
    global graph_service, temporal_client, worker, provider_refresh_task

    logger.info(f"Starting MemStack Temporal Worker (PID: {os.getpid()})...")
    logger.info(f"Temporal server: {temporal_settings.temporal_host}")
    logger.info(f"Task queue: {temporal_settings.temporal_default_task_queue}")

    # Verify database connection
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database connection verified")
    except Exception as e:
        logger.error(f"Failed to verify database connection: {e}")
        sys.exit(1)

    # Initialize default LLM providers
    try:
        from src.infrastructure.llm.initializer import initialize_default_llm_providers

        provider_created = await initialize_default_llm_providers()
        if provider_created:
            logger.info("Default LLM provider initialized successfully")
        else:
            logger.info("LLM providers already configured")
    except Exception as e:
        logger.error(f"Failed to initialize default LLM provider: {e}", exc_info=True)

    # Initialize NativeGraphAdapter
    try:
        graph_service = await create_native_graph_adapter()
        logger.info("Graph service (NativeGraphAdapter) initialized")

        # Set graph service in worker state for Activities
        from src.infrastructure.adapters.secondary.temporal.worker_state import set_graph_service

        set_graph_service(graph_service)
    except Exception as e:
        logger.error(f"Failed to initialize graph service: {e}")
        sys.exit(1)

    # Connect to Temporal
    try:
        from src.infrastructure.adapters.secondary.temporal.client import get_temporal_client

        temporal_client = await get_temporal_client(temporal_settings)
        logger.info("Connected to Temporal server")
    except Exception as e:
        logger.error(f"Failed to connect to Temporal server: {e}")
        sys.exit(1)

    # Import workflows and activities (data processing only - agent workflows moved to agent_worker.py)
    from src.infrastructure.adapters.secondary.temporal.activities import (
        add_episode_activity,
        incremental_refresh_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.community import (
        detect_communities_activity,
        rebuild_communities_activity,
        update_communities_for_entities_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.entity import (
        find_duplicate_entities_activity,
        merge_entities_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.episode import (
        extract_entities_activity,
        extract_relationships_activity,
    )

    # Note: deduplicate_entities_activity is deprecated, using merge activities instead
    from src.infrastructure.adapters.secondary.temporal.workflows import (
        DeduplicateEntitiesWorkflow,
        EpisodeProcessingWorkflow,
        IncrementalRefreshWorkflow,
        RebuildCommunitiesWorkflow,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.community import (
        BatchRebuildCommunitiesWorkflow,
        IncrementalCommunityUpdateWorkflow,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.entity import (
        BatchDeduplicateEntitiesWorkflow,
        DeduplicateEntitiesDAGWorkflow,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.episode import (
        EpisodeProcessingDAGWorkflow,
    )

    # Note: Agent workflows (AgentExecutionWorkflow) and activities have been moved
    # to the dedicated agent worker (src/agent_worker.py) for independent scaling.
    # Create worker (data processing workflows only)
    worker = Worker(
        temporal_client,
        task_queue=temporal_settings.temporal_default_task_queue,
        workflows=[
            # Episode workflows
            EpisodeProcessingWorkflow,
            EpisodeProcessingDAGWorkflow,
            IncrementalRefreshWorkflow,
            # Community workflows
            RebuildCommunitiesWorkflow,
            BatchRebuildCommunitiesWorkflow,
            IncrementalCommunityUpdateWorkflow,
            # Entity workflows
            DeduplicateEntitiesWorkflow,
            DeduplicateEntitiesDAGWorkflow,
            BatchDeduplicateEntitiesWorkflow,
        ],
        activities=[
            # Episode activities
            add_episode_activity,
            incremental_refresh_activity,
            extract_entities_activity,
            extract_relationships_activity,
            # Community activities
            rebuild_communities_activity,
            update_communities_for_entities_activity,
            detect_communities_activity,
            # Entity activities
            merge_entities_activity,
            find_duplicate_entities_activity,
        ],
        max_concurrent_activities=temporal_settings.temporal_max_concurrent_activities,
        max_concurrent_workflow_tasks=temporal_settings.temporal_max_concurrent_workflows,
    )

    logger.info(
        f"Temporal worker configured with "
        f"{temporal_settings.temporal_max_concurrent_activities} concurrent activities, "
        f"{temporal_settings.temporal_max_concurrent_workflows} concurrent workflows"
    )

    # Install signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    logger.info("Temporal worker is ready and waiting for tasks...")

    try:
        # Run the worker
        await worker.run()
    except asyncio.CancelledError:
        logger.info("Worker main loop cancelled")
    except Exception as e:
        logger.error(f"Unexpected error in worker: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        if str(e) != "Event loop is closed":
            raise
