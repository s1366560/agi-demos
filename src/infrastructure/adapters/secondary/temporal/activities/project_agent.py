"""
Project Agent Activities for Temporal.

This module provides activity implementations for the ProjectAgentWorkflow,
enabling project-level agent lifecycle management.

Activities:
- initialize_project_agent_activity: Initialize project agent and warm caches
- execute_project_chat_activity: Execute chat using project agent
- cleanup_project_agent_activity: Cleanup project agent resources

Metrics (via OpenTelemetry):
- project_agent.init_latency_ms: Initialization latency histogram
- project_agent.chat_latency_ms: Chat execution latency histogram
- project_agent.chat_total: Total chat requests counter
- project_agent.chat_errors: Chat errors counter
- project_agent.active_count: Active agent instances gauge
"""

import logging
import time as time_module
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity

from src.infrastructure.adapters.primary.web.metrics import agent_metrics
from src.infrastructure.agent.core.project_react_agent import (
    ProjectAgentConfig,
    ProjectReActAgent,
)

logger = logging.getLogger(__name__)

# Global registry of project agent instances (per-activity-worker)
# This provides caching at the activity worker level
_project_agent_instances: Dict[str, ProjectReActAgent] = {}
_instances_lock = False  # Simple flag lock (activities are single-threaded per worker)


def _get_project_agent_key(
    tenant_id: str,
    project_id: str,
    agent_mode: str = "default",
) -> str:
    """Generate unique key for project agent."""
    return f"{tenant_id}:{project_id}:{agent_mode}"


def _get_cached_project_agent(
    tenant_id: str,
    project_id: str,
    agent_mode: str = "default",
) -> Optional[ProjectReActAgent]:
    """Get cached project agent instance if exists and is active."""
    key = _get_project_agent_key(tenant_id, project_id, agent_mode)
    agent = _project_agent_instances.get(key)

    if agent and agent.is_active:
        return agent

    # Remove inactive agent
    if agent:
        _project_agent_instances.pop(key, None)

    return None


def _cache_project_agent(agent: ProjectReActAgent) -> None:
    """Cache a project agent instance."""
    key = agent.project_key
    _project_agent_instances[key] = agent


def _remove_cached_project_agent(
    tenant_id: str,
    project_id: str,
    agent_mode: str = "default",
) -> bool:
    """Remove cached project agent instance."""
    key = _get_project_agent_key(tenant_id, project_id, agent_mode)
    return _project_agent_instances.pop(key, None) is not None


@activity.defn
async def initialize_project_agent_activity(
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Initialize a project agent instance.

    This activity creates and initializes a ProjectReActAgent for the
    specified project, warming up all caches.

    Args:
        input_data: Contains:
            - config: ProjectAgentConfig
            - force_refresh: Whether to force cache refresh

    Returns:
        Initialization result with status and metadata
    """
    start_time = time_module.time()

    try:
        config_data = input_data.get("config", {})
        force_refresh = input_data.get("force_refresh", False)

        # Build config from dict
        config = ProjectAgentConfig(
            tenant_id=config_data.get("tenant_id", ""),
            project_id=config_data.get("project_id", ""),
            agent_mode=config_data.get("agent_mode", "default"),
            model=config_data.get("model"),
            api_key=config_data.get("api_key"),
            base_url=config_data.get("base_url"),
            temperature=config_data.get("temperature", 0.7),
            max_tokens=config_data.get("max_tokens", 4096),
            max_steps=config_data.get("max_steps", 20),
            persistent=config_data.get("persistent", True),
            max_concurrent_chats=config_data.get("max_concurrent_chats", 10),
            mcp_tools_ttl_seconds=config_data.get("mcp_tools_ttl_seconds", 300),
            enable_skills=config_data.get("enable_skills", True),
            enable_subagents=config_data.get("enable_subagents", True),
        )

        logger.info(
            f"[ProjectAgentActivity] Initializing: tenant={config.tenant_id}, "
            f"project={config.project_id}, mode={config.agent_mode}"
        )

        # Check for cached instance
        cached_agent = _get_cached_project_agent(
            config.tenant_id,
            config.project_id,
            config.agent_mode,
        )

        if cached_agent and not force_refresh:
            logger.info(f"[ProjectAgentActivity] Using cached agent: {cached_agent.project_key}")
            return {
                "status": "initialized",
                "tool_count": cached_agent._status.tool_count,
                "skill_count": cached_agent._status.skill_count,
                "cached": True,
            }

        # Remove old cached instance if refreshing
        if cached_agent and force_refresh:
            await cached_agent.stop()
            _remove_cached_project_agent(
                config.tenant_id,
                config.project_id,
                config.agent_mode,
            )

        # Create and initialize new agent
        agent = ProjectReActAgent(config)
        success = await agent.initialize(force_refresh=force_refresh)

        if success:
            # Cache the initialized agent
            _cache_project_agent(agent)

            init_time_ms = (time_module.time() - start_time) * 1000

            # Record metrics
            agent_metrics.observe(
                "project_agent.init_latency_ms",
                init_time_ms,
                labels={"project_id": config.project_id, "cached": "false"},
            )
            agent_metrics.set_gauge(
                "project_agent.active_count",
                len(_project_agent_instances),
            )

            logger.info(
                f"[ProjectAgentActivity] Initialized in {init_time_ms:.1f}ms: "
                f"tools={agent._status.tool_count}, skills={agent._status.skill_count}"
            )

            return {
                "status": "initialized",
                "tool_count": agent._status.tool_count,
                "skill_count": agent._status.skill_count,
                "cached": False,
            }
        else:
            agent_metrics.increment(
                "project_agent.init_errors",
                labels={"project_id": config.project_id},
            )
            logger.error(
                f"[ProjectAgentActivity] Initialization failed: {agent._status.last_error}"
            )
            return {
                "status": "error",
                "error": agent._status.last_error or "Unknown error",
            }

    except Exception as e:
        agent_metrics.increment("project_agent.init_errors")
        logger.error(f"[ProjectAgentActivity] Initialization error: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


@activity.defn
async def execute_project_chat_activity(
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a chat request using the project agent.

    This activity uses a cached ProjectReActAgent instance to process
    chat requests efficiently.

    Args:
        input_data: Contains:
            - conversation_id: Conversation ID
            - message_id: Message ID
            - user_message: User's message
            - user_id: User ID
            - conversation_context: Conversation history
            - config: Project configuration

    Returns:
        Chat result with content and metadata
    """
    start_time = time_module.time()

    try:
        # Extract parameters
        conversation_id = input_data.get("conversation_id", "")
        message_id = input_data.get("message_id", "")
        user_message = input_data.get("user_message", "")
        user_id = input_data.get("user_id", "")
        conversation_context = input_data.get("conversation_context", [])
        config = input_data.get("config", {})

        tenant_id = config.get("tenant_id", "")
        project_id = config.get("project_id", "")
        agent_mode = config.get("agent_mode", "default")

        logger.info(
            f"[ProjectAgentActivity] Executing chat: conversation={conversation_id}, "
            f"message={message_id}, project={project_id}"
        )

        # Get cached agent
        agent = _get_cached_project_agent(tenant_id, project_id, agent_mode)

        if not agent:
            # Agent not cached - need to initialize first
            logger.warning(
                f"[ProjectAgentActivity] Agent not cached, initializing: {tenant_id}:{project_id}"
            )

            # Build config
            agent_config = ProjectAgentConfig(
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=agent_mode,
                model=config.get("model"),
                temperature=config.get("temperature", 0.7),
                max_tokens=config.get("max_tokens", 4096),
                max_steps=config.get("max_steps", 20),
            )

            agent = ProjectReActAgent(agent_config)
            success = await agent.initialize()

            if not success:
                return {
                    "content": "",
                    "sequence_number": 0,
                    "is_error": True,
                    "error_message": "Failed to initialize project agent",
                    "execution_time_ms": (time_module.time() - start_time) * 1000,
                    "event_count": 0,
                }

            _cache_project_agent(agent)

        # Collect all events
        events: List[Dict[str, Any]] = []
        final_content = ""
        is_error = False
        error_message = None

        # Execute chat
        async for event in agent.execute_chat(
            conversation_id=conversation_id,
            user_message=user_message,
            user_id=user_id,
            conversation_context=conversation_context,
            tenant_id=tenant_id,
            message_id=message_id,
        ):
            events.append(event)

            # Track important events
            event_type = event.get("type")
            if event_type == "complete":
                final_content = event.get("data", {}).get("content", "")
            elif event_type == "error":
                is_error = True
                error_message = event.get("data", {}).get("message", "Unknown error")

        # Persist events to database
        sequence_number = await _persist_events(
            conversation_id=conversation_id,
            message_id=message_id,
            events=events,
        )

        execution_time_ms = (time_module.time() - start_time) * 1000

        # Record metrics
        agent_metrics.increment(
            "project_agent.chat_total",
            labels={"project_id": project_id},
        )
        agent_metrics.observe(
            "project_agent.chat_latency_ms",
            execution_time_ms,
            labels={"project_id": project_id},
        )

        if is_error:
            agent_metrics.increment(
                "project_agent.chat_errors",
                labels={"project_id": project_id},
            )
            logger.warning(
                f"[ProjectAgentActivity] Chat failed: {error_message}, "
                f"time={execution_time_ms:.1f}ms"
            )
        else:
            logger.info(
                f"[ProjectAgentActivity] Chat completed: events={len(events)}, "
                f"time={execution_time_ms:.1f}ms"
            )

        return {
            "content": final_content,
            "sequence_number": sequence_number,
            "is_error": is_error,
            "error_message": error_message,
            "execution_time_ms": execution_time_ms,
            "event_count": len(events),
        }

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        agent_metrics.increment("project_agent.chat_errors")
        logger.error(f"[ProjectAgentActivity] Chat error: {e}", exc_info=True)

        return {
            "content": "",
            "sequence_number": 0,
            "is_error": True,
            "error_message": str(e),
            "execution_time_ms": execution_time_ms,
            "event_count": 0,
        }


@activity.defn
async def cleanup_project_agent_activity(
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Cleanup a project agent instance.

    This activity stops and removes a cached project agent.

    Args:
        input_data: Contains:
            - tenant_id: Tenant ID
            - project_id: Project ID
            - agent_mode: Agent mode

    Returns:
        Cleanup result
    """
    try:
        tenant_id = input_data.get("tenant_id", "")
        project_id = input_data.get("project_id", "")
        agent_mode = input_data.get("agent_mode", "default")

        logger.info(
            f"[ProjectAgentActivity] Cleaning up: tenant={tenant_id}, "
            f"project={project_id}, mode={agent_mode}"
        )

        # Get cached agent and stop it
        agent = _get_cached_project_agent(tenant_id, project_id, agent_mode)

        if agent:
            await agent.stop()

        # Remove from cache
        removed = _remove_cached_project_agent(tenant_id, project_id, agent_mode)

        logger.info(f"[ProjectAgentActivity] Cleanup completed: removed={removed}")

        return {
            "status": "cleaned",
            "removed": removed,
        }

    except Exception as e:
        logger.error(f"[ProjectAgentActivity] Cleanup error: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# Helper Functions
# ============================================================================


async def _persist_events(
    conversation_id: str,
    message_id: str,
    events: List[Dict[str, Any]],
) -> int:
    """
    Persist agent events to database.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        events: List of events to persist

    Returns:
        Last sequence number
    """
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    # Event types to skip (streaming fragments)
    SKIP_EVENT_TYPES = {
        "thought_delta",
        "text_delta",
        "text_start",
        "text_end",
    }

    sequence_number = 0

    try:
        async with async_session_factory() as session:
            async with session.begin():
                for idx, event in enumerate(events):
                    event_type = event.get("type", "unknown")
                    event_data = event.get("data", {})
                    sequence_number = event.get("seq", idx + 1)

                    # Skip streaming fragments
                    if event_type in SKIP_EVENT_TYPES:
                        continue

                    stmt = (
                        insert(AgentExecutionEvent)
                        .values(
                            id=str(uuid.uuid4()),
                            conversation_id=conversation_id,
                            message_id=message_id,
                            event_type=event_type,
                            event_data=event_data,
                            sequence_number=sequence_number,
                            created_at=datetime.now(timezone.utc),
                        )
                        .on_conflict_do_nothing(
                            index_elements=["conversation_id", "sequence_number"]
                        )
                    )
                    await session.execute(stmt)

        return sequence_number

    except IntegrityError as e:
        if "uq_agent_events_conv_seq" in str(e):
            logger.warning(
                f"Duplicate events detected for conversation={conversation_id}, "
                "skipping persistence"
            )
            return sequence_number
        raise

    except Exception as e:
        logger.error(f"Failed to persist events: {e}")
        # Don't raise - event persistence is not critical
        return sequence_number
