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
pool_adapter = None  # Agent Pool Adapter (when enabled)
pool_orchestrator = None  # Pool Orchestrator (with HA services)
hitl_response_listener = None  # HITL Response Listener for real-time delivery

# Agent worker-specific settings
AGENT_TASK_QUEUE = os.getenv("AGENT_TEMPORAL_TASK_QUEUE", "memstack-agent-tasks")
AGENT_WORKER_CONCURRENCY = int(os.getenv("AGENT_WORKER_CONCURRENCY", "50"))
AGENT_SESSION_CLEANUP_INTERVAL = int(
    os.getenv("AGENT_SESSION_CLEANUP_INTERVAL", "600")
)  # 10 minutes
HITL_REALTIME_ENABLED = os.getenv("HITL_REALTIME_ENABLED", "true").lower() == "true"


async def periodic_session_cleanup():
    """Background task to periodically clean up expired Agent Session Pool entries.

    This prevents memory leaks from unused cached sessions.
    Sessions are cleaned up after 24 hours of inactivity (configurable via AGENT_SESSION_TTL_SECONDS).
    Cleanup interval: every 10 minutes (configurable via AGENT_SESSION_CLEANUP_INTERVAL).
    """
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        cleanup_expired_sessions,
        get_pool_stats,
    )

    # Use configured TTL (default 24 hours)
    session_ttl_seconds = settings.agent_session_ttl_seconds

    logger.info(
        f"Agent Worker: Session cleanup task started "
        f"(check_interval={AGENT_SESSION_CLEANUP_INTERVAL}s, ttl={session_ttl_seconds}s/{session_ttl_seconds // 3600}h)"
    )

    while True:
        try:
            await asyncio.sleep(AGENT_SESSION_CLEANUP_INTERVAL)

            # Clean up sessions that have been inactive for longer than TTL
            cleaned = await cleanup_expired_sessions(ttl_seconds=session_ttl_seconds)

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
    2. Close resources in dependency order: Pool -> Redis -> Graph Service -> State
    """
    global worker, temporal_client, cleanup_task, pool_adapter, pool_orchestrator
    global hitl_response_listener

    if signal_enum:
        logger.info(f"Agent Worker: Received exit signal {signal_enum.name}...")

    logger.info("Agent Worker: Shutting down...")

    # Stop HITL Response Listener first
    if hitl_response_listener:
        try:
            await hitl_response_listener.stop()
            logger.info("Agent Worker: HITL Response Listener stopped")
        except Exception as e:
            logger.warning(f"Agent Worker: HITL Listener shutdown error: {e}")

    # Cancel cleanup task first
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("Agent Worker: Cleanup task cancelled")

    # Shutdown Agent Pool Orchestrator (if enabled)
    if pool_orchestrator:
        try:
            await asyncio.wait_for(pool_orchestrator.stop(), timeout=15.0)
            logger.info("Agent Worker: Pool Orchestrator stopped")
        except asyncio.TimeoutError:
            logger.warning("Agent Worker: Pool Orchestrator stop timed out")
        except Exception as e:
            logger.warning(f"Agent Worker: Error stopping Pool Orchestrator: {e}")
    elif pool_adapter:
        # Legacy: Shutdown Agent Pool Manager (if enabled but no orchestrator)
        try:
            await asyncio.wait_for(pool_adapter.stop(), timeout=10.0)
            logger.info("Agent Worker: Pool Manager stopped")
        except asyncio.TimeoutError:
            logger.warning("Agent Worker: Pool Manager stop timed out")
        except Exception as e:
            logger.warning(f"Agent Worker: Error stopping Pool Manager: {e}")

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

        # Sync existing sandbox containers from Docker (wait for completion)
        count = await sync_mcp_sandbox_adapter_from_docker()
        if count > 0:
            logger.info(f"Agent Worker: Synced {count} existing sandboxes from Docker")

    except Exception as e:
        logger.warning(
            f"Agent Worker: Failed to initialize MCP Sandbox adapter (Sandbox tools disabled): {e}"
        )

    # Optional: Prewarm agent session caches to reduce first-request latency
    if settings.agent_session_prewarm_enabled:
        asyncio.create_task(prewarm_agent_sessions())
        logger.info("Agent Worker: Prewarm task scheduled")

    # Initialize HITL Response Listener for real-time delivery
    global hitl_response_listener
    if HITL_REALTIME_ENABLED:
        try:
            import redis.asyncio as aioredis

            from src.infrastructure.agent.hitl.response_listener import (
                HITLResponseListener,
            )

            # Get Redis URL from settings
            redis_url = getattr(settings, "redis_url", None)
            if not redis_url:
                redis_host = getattr(settings, "redis_host", "localhost")
                redis_port = getattr(settings, "redis_port", 6379)
                redis_url = f"redis://{redis_host}:{redis_port}"

            redis_client = aioredis.from_url(redis_url)
            hitl_response_listener = HITLResponseListener(redis_client)
            await hitl_response_listener.start()
            logger.info("Agent Worker: HITL Response Listener started (real-time delivery enabled)")
        except Exception as e:
            logger.warning(
                f"Agent Worker: Failed to initialize HITL Response Listener: {e}. "
                f"Falling back to Temporal Signal only."
            )
            hitl_response_listener = None

    # Optional: Initialize Agent Pool with Orchestrator (new 3-tier architecture with HA)
    global pool_adapter, pool_orchestrator
    if settings.agent_pool_enabled:
        try:
            from src.infrastructure.agent.pool import PoolConfig
            from src.infrastructure.agent.pool.config import TierConfig
            from src.infrastructure.agent.pool.feature_flags import get_feature_flags
            from src.infrastructure.agent.pool.orchestrator import (
                OrchestratorConfig,
                PoolOrchestrator,
            )
            from src.infrastructure.agent.pool.types import ProjectTier

            # Check feature flags for HA components
            flags = get_feature_flags()

            # Create pool config from settings
            pool_config = PoolConfig(
                default_tier=ProjectTier(settings.agent_pool_default_tier),
                tier_configs={
                    ProjectTier.WARM: TierConfig(
                        tier=ProjectTier.WARM,
                        max_instances=settings.agent_pool_warm_max_instances,
                    ),
                    ProjectTier.COLD: TierConfig(
                        tier=ProjectTier.COLD,
                        max_instances=settings.agent_pool_cold_max_instances,
                        eviction_idle_seconds=settings.agent_pool_cold_idle_timeout_seconds,
                    ),
                },
                health_check_interval_seconds=settings.agent_pool_health_check_interval_seconds,
            )

            # Create orchestrator config with HA features
            orchestrator_config = OrchestratorConfig(
                pool_config=pool_config,
                enable_health_monitor=await flags.is_enabled("agent_pool_health_monitor"),
                enable_failure_recovery=await flags.is_enabled("agent_pool_failure_recovery"),
                enable_auto_scaling=await flags.is_enabled("agent_pool_auto_scaling"),
                enable_state_recovery=await flags.is_enabled("agent_pool_state_recovery"),
                enable_metrics=await flags.is_enabled("agent_pool_metrics"),
                redis_url=settings.redis_url if hasattr(settings, "redis_url") else None,
                health_check_interval_seconds=settings.agent_pool_health_check_interval_seconds,
            )

            # Initialize orchestrator
            pool_orchestrator = PoolOrchestrator(orchestrator_config)
            await pool_orchestrator.start()

            # Create adapter wrapper for legacy compatibility
            from src.infrastructure.agent.pool import create_pooled_adapter

            pool_adapter = create_pooled_adapter(pool_config=pool_config)
            pool_adapter._pool_manager = pool_orchestrator.pool_manager
            pool_adapter._is_running = True

            # Register pool adapter in worker state for Activities
            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                set_pool_adapter,
            )

            set_pool_adapter(pool_adapter)

            # Log enabled features
            enabled_features = []
            if orchestrator_config.enable_health_monitor:
                enabled_features.append("health")
            if orchestrator_config.enable_failure_recovery:
                enabled_features.append("recovery")
            if orchestrator_config.enable_auto_scaling:
                enabled_features.append("scaling")
            if orchestrator_config.enable_state_recovery:
                enabled_features.append("checkpoints")
            if orchestrator_config.enable_metrics:
                enabled_features.append("metrics")

            logger.info(
                f"Agent Worker: Pool Orchestrator initialized "
                f"(default_tier={settings.agent_pool_default_tier}, "
                f"warm_max={settings.agent_pool_warm_max_instances}, "
                f"cold_max={settings.agent_pool_cold_max_instances}, "
                f"ha_features=[{', '.join(enabled_features)}])"
            )
        except Exception as e:
            logger.warning(f"Agent Worker: Failed to initialize Pool Orchestrator: {e}")
            pool_adapter = None
            pool_orchestrator = None
            pool_adapter = None

    # Import agent-specific workflows and activities
    from src.infrastructure.adapters.secondary.temporal.activities.agent import (
        clear_agent_running,
        refresh_agent_running_ttl,
        save_checkpoint_activity,
        save_event_activity,
        set_agent_running,
    )
    from src.infrastructure.adapters.secondary.temporal.activities.project_agent import (
        cleanup_project_agent_activity,
        continue_project_chat_activity,
        execute_project_chat_activity,
        initialize_project_agent_activity,
    )
    from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
        ProjectAgentWorkflow,
    )

    # Create worker with agent-specific configuration
    worker = Worker(
        temporal_client,
        task_queue=AGENT_TASK_QUEUE,
        workflows=[
            # Project Agent workflow (primary agent interface)
            ProjectAgentWorkflow,
        ],
        activities=[
            # Common agent activities
            save_event_activity,
            save_checkpoint_activity,
            set_agent_running,
            clear_agent_running,
            refresh_agent_running_ttl,
            # Project Agent activities
            initialize_project_agent_activity,
            execute_project_chat_activity,
            continue_project_chat_activity,
            cleanup_project_agent_activity,
        ],
        max_concurrent_activities=AGENT_WORKER_CONCURRENCY,
        max_concurrent_workflow_tasks=AGENT_WORKER_CONCURRENCY,
    )

    logger.info(
        f"Agent Worker: Configured with "
        f"{AGENT_WORKER_CONCURRENCY} concurrent activities, "
        f"{AGENT_WORKER_CONCURRENCY} concurrent workflows, "
        f"1 workflow type (ProjectAgent)"
    )

    # Install signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))

    logger.info("Agent Worker: Ready and waiting for tasks...")

    # Start background cleanup task for Agent Session Pool
    global cleanup_task
    cleanup_task = asyncio.create_task(periodic_session_cleanup())

    # Recover unprocessed HITL responses from previous Worker instance
    # This handles the case where Worker crashed while Agent was waiting for user response
    try:
        from src.infrastructure.agent.hitl.recovery_service import recover_hitl_on_startup

        recovered = await recover_hitl_on_startup()
        if recovered > 0:
            logger.info(f"Agent Worker: Recovered {recovered} HITL requests from previous session")
    except Exception as e:
        logger.warning(f"Agent Worker: HITL recovery failed (non-fatal): {e}")

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
