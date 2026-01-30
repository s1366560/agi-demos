"""Temporal Worker for Agent Execution.

This script runs a dedicated Temporal Worker for Agent workflows only.
It allows independent scaling and deployment from the main data processing worker.

Usage:
    python -m src.agent_worker
    # or
    uv run python src/agent_worker.py
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
logger = logging.getLogger("src.agent_worker")

settings = get_settings()
temporal_settings = get_temporal_settings()

# Global state
agent_graph_service = None
temporal_client = None
worker = None
cleanup_task = None  # Background cleanup task for Agent Session Pool

# Agent worker-specific settings
AGENT_TASK_QUEUE = os.getenv("AGENT_TEMPORAL_TASK_QUEUE", "memstack-agent-tasks")
AGENT_WORKER_CONCURRENCY = int(os.getenv("AGENT_WORKER_CONCURRENCY", "50"))
AGENT_SESSION_CLEANUP_INTERVAL = int(
    os.getenv("AGENT_SESSION_CLEANUP_INTERVAL", "600")
)  # 10 minutes


async def periodic_session_cleanup():
    """Background task to periodically clean up expired Agent Session Pool entries.

    This prevents memory leaks from unused cached sessions.
    Default interval: every 10 minutes.
    """
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        cleanup_expired_sessions,
        get_pool_stats,
    )

    logger.info(
        f"Agent Worker: Session cleanup task started (interval: {AGENT_SESSION_CLEANUP_INTERVAL}s)"
    )

    while True:
        try:
            await asyncio.sleep(AGENT_SESSION_CLEANUP_INTERVAL)

            # Clean up expired sessions
            cleaned = await cleanup_expired_sessions()

            # Log pool stats
            stats = get_pool_stats()

            logger.info(
                f"Agent Worker: Session cleanup completed "
                f"(cleaned={cleaned}, total_sessions={stats['total_sessions']}, "
                f"tool_defs={stats['tool_definitions_cached']}, "
                f"mcp_tools={stats['mcp_tools_cached']})"
            )

        except asyncio.CancelledError:
            logger.info("Agent Worker: Session cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Agent Worker: Session cleanup error: {e}", exc_info=True)
            # Continue running despite errors
            await asyncio.sleep(60)  # Wait before retry


async def prewarm_agent_sessions() -> None:
    """Prewarm agent session caches for existing projects.

    Controlled by settings.agent_session_prewarm_enabled.
    Runs in the background to avoid blocking worker startup.
    """
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import Project
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        prewarm_agent_session,
    )

    max_projects = settings.agent_session_prewarm_max_projects
    concurrency = settings.agent_session_prewarm_concurrency

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Project.id, Project.tenant_id)
                .order_by(Project.created_at.desc())
                .limit(max_projects)
            )
            rows = result.all()

        if not rows:
            logger.info("Agent Worker: No projects found for prewarm")
            return

        logger.info(
            "Agent Worker: Prewarming %d projects (concurrency=%d)",
            len(rows),
            concurrency,
        )

        sem = asyncio.Semaphore(concurrency)

        async def _run(row):
            async with sem:
                await prewarm_agent_session(
                    tenant_id=row.tenant_id,
                    project_id=row.id,
                    agent_mode="default",
                )

        await asyncio.gather(*[_run(row) for row in rows])
        logger.info("Agent Worker: Prewarm completed")
    except Exception as e:
        logger.warning(f"Agent Worker: Prewarm failed: {e}")


async def shutdown(signal_enum=None):
    """Cleanup tasks tied to the service's shutdown.

    Implements a two-phase shutdown:
    1. Stop worker (wait for in-flight tasks with timeout)
    2. Close resources in dependency order: Redis -> Graph Service -> State
    """
    global worker, temporal_client, cleanup_task

    if signal_enum:
        logger.info(f"Agent Worker: Received exit signal {signal_enum.name}...")

    logger.info("Agent Worker: Shutting down...")

    # Cancel cleanup task first
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Agent Worker: Cleanup task cancelled")

    # Phase 1: Shutdown worker with timeout
    if worker:
        try:
            await asyncio.wait_for(worker.shutdown(), timeout=30.0)
            logger.info("Agent Worker: Worker shutdown complete")
        except asyncio.TimeoutError:
            logger.warning("Agent Worker: Worker shutdown timed out after 30s, forcing shutdown")
        except Exception as e:
            logger.warning(f"Agent Worker: Error during worker shutdown: {e}")

    # Phase 2: Close resources in dependency order
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        clear_state,
        close_redis_pool,
    )

    # Close Redis connection pool first
    try:
        await asyncio.wait_for(close_redis_pool(), timeout=5.0)
        logger.info("Agent Worker: Redis connection pool closed")
    except asyncio.TimeoutError:
        logger.warning("Agent Worker: Redis pool close timed out")
    except Exception as e:
        logger.warning(f"Agent Worker: Error closing Redis pool: {e}")

    # Close graph service
    if agent_graph_service and hasattr(agent_graph_service, "close"):
        try:
            await asyncio.wait_for(agent_graph_service.close(), timeout=10.0)
            logger.info("Agent Worker: Graph service closed")
        except asyncio.TimeoutError:
            logger.warning("Agent Worker: Graph service close timed out")
        except Exception as e:
            logger.warning(f"Agent Worker: Error closing graph service: {e}")

    # Clear worker state
    clear_state()

    # Cancel remaining tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        logger.info(f"Agent Worker: Cancelling {len(tasks)} outstanding tasks")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("Agent Worker: Shutdown complete")

    try:
        loop = asyncio.get_running_loop()
        loop.stop()
    except RuntimeError:
        pass


async def main():
    """Main Agent Worker entry point."""
    global agent_graph_service, temporal_client, worker

    logger.info(f"Starting MemStack Agent Worker (PID: {os.getpid()})...")
    logger.info(f"Temporal server: {temporal_settings.temporal_host}")
    logger.info(f"Agent task queue: {AGENT_TASK_QUEUE}")
    logger.info(f"Max concurrency: {AGENT_WORKER_CONCURRENCY}")

    # Verify database connection
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Agent Worker: Database connection verified")
    except Exception as e:
        logger.error(f"Agent Worker: Failed to verify database connection: {e}")
        sys.exit(1)

    # Initialize default LLM providers
    try:
        from src.infrastructure.llm.initializer import initialize_default_llm_providers

        provider_created = await initialize_default_llm_providers()
        if provider_created:
            logger.info("Agent Worker: Default LLM provider initialized successfully")
        else:
            logger.info("Agent Worker: LLM providers already configured")
    except Exception as e:
        logger.error(f"Agent Worker: Failed to initialize default LLM provider: {e}", exc_info=True)

    # Initialize NativeGraphAdapter
    try:
        agent_graph_service = await create_native_graph_adapter()
        logger.info("Agent Worker: Graph service (NativeGraphAdapter) initialized")

        # Set graph service in worker state for Activities
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            set_agent_graph_service,
        )

        set_agent_graph_service(agent_graph_service)
    except Exception as e:
        logger.error(f"Agent Worker: Failed to initialize graph service: {e}")
        sys.exit(1)

    # Connect to Temporal
    try:
        from src.infrastructure.adapters.secondary.temporal.client import get_temporal_client

        temporal_client = await get_temporal_client(temporal_settings)
        logger.info("Agent Worker: Connected to Temporal server")
    except Exception as e:
        logger.error(f"Agent Worker: Failed to connect to Temporal server: {e}")
        sys.exit(1)

    # Initialize MCP Temporal Adapter for MCP tool loading
    try:
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            set_mcp_temporal_adapter,
        )
        from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPTemporalAdapter

        mcp_temporal_adapter = MCPTemporalAdapter(temporal_client)
        set_mcp_temporal_adapter(mcp_temporal_adapter)
        logger.info("Agent Worker: MCP Temporal Adapter initialized")
    except Exception as e:
        logger.warning(f"Agent Worker: Failed to initialize MCP adapter (MCP tools disabled): {e}")

    # Initialize MCP Sandbox Adapter for Project Sandbox tool loading
    try:
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            set_mcp_sandbox_adapter,
            sync_mcp_sandbox_adapter_from_docker,
        )

        mcp_sandbox_adapter = MCPSandboxAdapter(
            mcp_image=settings.sandbox_default_image,
            default_timeout=settings.sandbox_timeout_seconds,
            default_memory_limit=settings.sandbox_memory_limit,
            default_cpu_limit=settings.sandbox_cpu_limit,
        )
        set_mcp_sandbox_adapter(mcp_sandbox_adapter)
        logger.info("Agent Worker: MCP Sandbox Adapter initialized")

        # Sync existing sandbox containers from Docker
        asyncio.create_task(sync_mcp_sandbox_adapter_from_docker())

    except Exception as e:
        logger.warning(
            f"Agent Worker: Failed to initialize MCP Sandbox adapter (Sandbox tools disabled): {e}"
        )

    # Optional: Prewarm agent session caches to reduce first-request latency
    if settings.agent_session_prewarm_enabled:
        asyncio.create_task(prewarm_agent_sessions())
        logger.info("Agent Worker: Prewarm task scheduled")

    # Import agent-specific workflows and activities
    from src.infrastructure.adapters.secondary.temporal.activities.agent import (  # New: uses ReActAgent  # Legacy: hardcoded logic
        clear_agent_running,
        execute_react_agent_activity,
        execute_react_step_activity,
        refresh_agent_running_ttl,
        save_checkpoint_activity,
        save_event_activity,
        set_agent_running,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.agent_session import (
        cleanup_agent_session_activity,
        execute_chat_activity,
        initialize_agent_session_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.project_agent import (
        cleanup_project_agent_activity,
        execute_project_chat_activity,
        initialize_project_agent_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.agent import (
        AgentExecutionWorkflow,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
        AgentSessionWorkflow,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
        ProjectAgentWorkflow,
    )

    # Create worker with agent-specific configuration
    worker = Worker(
        temporal_client,
        task_queue=AGENT_TASK_QUEUE,
        workflows=[
            # Agent workflows
            AgentExecutionWorkflow,  # Legacy: per-request workflow
            AgentSessionWorkflow,  # Long-running session workflow
            ProjectAgentWorkflow,  # New: project-level persistent workflow
        ],
        activities=[
            # Legacy agent activities
            execute_react_agent_activity,  # Uses ReActAgent (recommended)
            execute_react_step_activity,  # Legacy: hardcoded logic
            save_event_activity,
            save_checkpoint_activity,
            set_agent_running,
            clear_agent_running,
            refresh_agent_running_ttl,
            # Agent Session activities
            initialize_agent_session_activity,
            execute_chat_activity,
            cleanup_agent_session_activity,
            # Project Agent activities (new)
            initialize_project_agent_activity,
            execute_project_chat_activity,
            cleanup_project_agent_activity,
        ],
        max_concurrent_activities=AGENT_WORKER_CONCURRENCY,
        max_concurrent_workflow_tasks=AGENT_WORKER_CONCURRENCY,
    )

    logger.info(
        f"Agent Worker: Configured with "
        f"{AGENT_WORKER_CONCURRENCY} concurrent activities, "
        f"{AGENT_WORKER_CONCURRENCY} concurrent workflows, "
        f"3 workflow types (AgentExecution, AgentSession, ProjectAgent)"
    )

    # Install signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    logger.info("Agent Worker: Ready and waiting for tasks...")

    # Start background cleanup task for Agent Session Pool
    global cleanup_task
    cleanup_task = asyncio.create_task(periodic_session_cleanup())

    try:
        # Run the worker
        await worker.run()
    except asyncio.CancelledError:
        logger.info("Agent Worker: Main loop cancelled")
    except Exception as e:
        logger.error(f"Agent Worker: Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        if str(e) != "Event loop is closed":
            raise
