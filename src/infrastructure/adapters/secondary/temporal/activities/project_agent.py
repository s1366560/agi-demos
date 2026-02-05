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

import json
import logging
import time as time_module
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from temporalio import activity

from src.configuration.config import get_settings
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

# Global Redis connection pool for event publishing
_redis_pool: Optional[aioredis.ConnectionPool] = None


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


def _format_hitl_response_as_tool_result(
    hitl_type: str,
    response_data: Dict[str, Any],
) -> str:
    """
    Format HITL response data as a tool result content string.

    This is used to inject the user's HITL response into the conversation
    as a tool result, so the LLM can see what the user chose.

    Args:
        hitl_type: Type of HITL request (clarification, decision, env_var, permission)
        response_data: User's response data (dict or str)

    Returns:
        Formatted tool result content string
    """
    # Handle string response_data (defensive coding)
    if isinstance(response_data, str):
        try:
            response_data = json.loads(response_data)
        except (json.JSONDecodeError, TypeError):
            # If can't parse, treat as plain answer
            return f"User responded: {response_data}"

    # Ensure response_data is a dict
    if not isinstance(response_data, dict):
        return f"User responded to {hitl_type} request"

    if hitl_type == "clarification":
        selected = response_data.get("selected_option_id") or response_data.get("selected_options")
        custom = response_data.get("custom_input")
        if custom:
            return f"User clarification: {custom}"
        elif selected:
            if isinstance(selected, list):
                return f"User selected options: {', '.join(selected)}"
            return f"User selected: {selected}"
        return "User provided clarification (no specific selection)"

    elif hitl_type == "decision":
        selected = response_data.get("selected_option_id")
        custom = response_data.get("custom_input")
        if custom:
            return f"User decision (custom): {custom}"
        elif selected:
            return f"User chose: {selected}"
        return "User made a decision (no specific selection)"

    elif hitl_type == "env_var":
        # For env vars, we don't expose the actual values in the tool result
        # Just indicate that values were provided
        values = response_data.get("values", {})
        provided_vars = list(values.keys()) if values else []
        if provided_vars:
            return f"User provided environment variables: {', '.join(provided_vars)}"
        return "User provided environment variable values"

    elif hitl_type == "permission":
        granted = response_data.get("granted", False)
        scope = response_data.get("scope", "once")
        if granted:
            return f"User granted permission (scope: {scope})"
        else:
            return "User denied permission"

    # Fallback for unknown types
    return f"User responded to {hitl_type} request"


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

    When an HITL request is encountered, this activity:
    1. Saves the Agent state to Redis
    2. Returns a result with hitl_pending=True
    3. The Workflow then waits for user response via Signal
    4. After receiving response, Workflow calls continue_project_chat_activity

    Args:
        input_data: Contains:
            - conversation_id: Conversation ID
            - message_id: Message ID
            - user_message: User's message
            - user_id: User ID
            - conversation_context: Conversation history
            - config: Project configuration
            - hitl_response: Optional HITL response (for resume scenario)

    Returns:
        Chat result with content and metadata, or hitl_pending indicator
    """
    from src.domain.model.agent.hitl_types import HITLPendingException
    from src.infrastructure.agent.hitl.state_store import (
        HITLAgentState,
        HITLStateStore,
    )

    start_time = time_module.time()

    try:
        # Extract parameters
        conversation_id = input_data.get("conversation_id", "")
        message_id = input_data.get("message_id", "")
        user_message = input_data.get("user_message", "")
        user_id = input_data.get("user_id", "")
        conversation_context = input_data.get("conversation_context", [])
        correlation_id = input_data.get("correlation_id")  # Request correlation ID
        config = input_data.get("config", {})
        hitl_response = input_data.get("hitl_response")  # For resume scenario

        tenant_id = config.get("tenant_id", "")
        project_id = config.get("project_id", "")
        agent_mode = config.get("agent_mode", "default")

        logger.info(
            f"[ProjectAgentActivity] Executing chat: conversation={conversation_id}, "
            f"message={message_id}, project={project_id}, correlation={correlation_id}, "
            f"has_hitl_response={hitl_response is not None}"
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

        # Collect all events and publish in real-time
        events: List[Dict[str, Any]] = []
        final_content = ""
        is_error = False
        error_message = None
        sequence_number = 0

        # Get Redis client for connection reuse during streaming
        pool = await _get_redis_pool()
        redis_client = aioredis.Redis(connection_pool=pool)

        try:
            # Execute chat and stream events to Redis
            async for event in agent.execute_chat(
                conversation_id=conversation_id,
                user_message=user_message,
                user_id=user_id,
                conversation_context=conversation_context,
                tenant_id=tenant_id,
                message_id=message_id,
                hitl_response=hitl_response,  # Pass HITL response for resume
            ):
                events.append(event)
                sequence_number += 1

                # Publish event to Redis Stream in real-time
                await _publish_event_to_stream(
                    conversation_id=conversation_id,
                    event=event,
                    message_id=message_id,
                    sequence_number=sequence_number,
                    correlation_id=correlation_id,
                    redis_client=redis_client,
                )

                # Track important events
                event_type = event.get("type")
                if event_type == "complete":
                    final_content = event.get("data", {}).get("content", "")
                elif event_type == "error":
                    is_error = True
                    error_message = event.get("data", {}).get("message", "Unknown error")

            # Normal completion - persist events and return result
            await _persist_events(
                conversation_id=conversation_id,
                message_id=message_id,
                events=events,
                correlation_id=correlation_id,
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

        except HITLPendingException as hitl_ex:
            # HITL request encountered - try fast path first, then fall back to Workflow Signal
            logger.info(
                f"[ProjectAgentActivity] HITL pending: request_id={hitl_ex.request_id}, "
                f"type={hitl_ex.hitl_type.value}"
            )

            # Use current_messages from exception if available (includes assistant's tool call)
            # Fall back to conversation_context if not set (backward compatibility)
            saved_messages = hitl_ex.current_messages or conversation_context

            if hitl_ex.current_messages:
                logger.info(
                    f"[ProjectAgentActivity] Saving {len(hitl_ex.current_messages)} messages "
                    f"(with assistant tool call)"
                )
            else:
                logger.warning(
                    f"[ProjectAgentActivity] current_messages not available, "
                    f"falling back to conversation_context ({len(conversation_context)} messages)"
                )

            # Save Agent state to Redis for later resumption (needed for backup path)
            state = HITLAgentState(
                conversation_id=conversation_id,
                message_id=message_id,
                tenant_id=tenant_id,
                project_id=project_id,
                hitl_request_id=hitl_ex.request_id,
                hitl_type=hitl_ex.hitl_type.value,
                hitl_request_data=hitl_ex.request_data,
                messages=saved_messages,
                user_message=user_message,
                user_id=user_id,
                step_count=getattr(agent, "_step_count", 0),
                timeout_seconds=hitl_ex.timeout_seconds,
                pending_tool_call_id=hitl_ex.tool_call_id,
            )

            state_store = HITLStateStore(redis_client)
            state_key = await state_store.save_state(state)

            # Persist events collected so far
            if events:
                await _persist_events(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    events=events,
                    correlation_id=correlation_id,
                )

            # === FAST PATH: Try to wait for response via Redis Streams (in-process) ===
            # This provides ~30ms latency vs ~500ms for Temporal Signal
            settings = get_settings()
            fast_path_response = None

            if getattr(settings, "hitl_realtime_enabled", True):
                fast_path_response = await _wait_for_hitl_response_fast_path(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    request_id=hitl_ex.request_id,
                    hitl_type=hitl_ex.hitl_type.value,
                    timeout_seconds=min(
                        10.0, hitl_ex.timeout_seconds
                    ),  # Wait max 10s for fast path
                )

            if fast_path_response:
                # Fast path succeeded! Continue execution directly in this Activity
                logger.info(
                    f"[ProjectAgentActivity] Fast path response received for {hitl_ex.request_id}, "
                    f"continuing execution"
                )

                # Build context with HITL response
                hitl_response_for_agent = {
                    "request_id": hitl_ex.request_id,
                    "hitl_type": hitl_ex.hitl_type.value,
                    "response_data": fast_path_response,
                }

                # Build conversation context with injected tool result
                conversation_context_with_response = list(saved_messages)

                if hitl_ex.tool_call_id:
                    tool_result_content = _format_hitl_response_as_tool_result(
                        hitl_type=hitl_ex.hitl_type.value,
                        response_data=fast_path_response,
                    )

                    conversation_context_with_response.append(
                        {
                            "role": "tool",
                            "tool_call_id": hitl_ex.tool_call_id,
                            "content": tool_result_content,
                        }
                    )

                # Continue execution - may trigger another HITL
                try:
                    async for event in agent.execute_chat(
                        conversation_id=conversation_id,
                        user_message=user_message,
                        user_id=user_id,
                        conversation_context=conversation_context_with_response,
                        tenant_id=tenant_id,
                        message_id=message_id,
                        hitl_response=hitl_response_for_agent,
                    ):
                        events.append(event)
                        sequence_number += 1

                        await _publish_event_to_stream(
                            conversation_id=conversation_id,
                            event=event,
                            message_id=message_id,
                            sequence_number=sequence_number,
                            correlation_id=correlation_id,
                            redis_client=redis_client,
                        )

                        event_type = event.get("type")
                        if event_type == "complete":
                            final_content = event.get("data", {}).get("content", "")
                        elif event_type == "error":
                            is_error = True
                            error_message = event.get("data", {}).get("message", "Unknown error")

                    # Clean up state
                    await state_store.delete_state(state_key)

                    # Persist all events
                    await _persist_events(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        events=events,
                        correlation_id=correlation_id,
                    )

                    execution_time_ms = (time_module.time() - start_time) * 1000

                    agent_metrics.increment(
                        "project_agent.chat_total",
                        labels={"project_id": project_id},
                    )
                    agent_metrics.increment(
                        "project_agent.hitl_fast_path_success",
                        labels={"project_id": project_id},
                    )

                    return {
                        "content": final_content,
                        "sequence_number": sequence_number,
                        "is_error": is_error,
                        "error_message": error_message,
                        "execution_time_ms": execution_time_ms,
                        "event_count": len(events),
                    }

                except HITLPendingException as nested_hitl_ex:
                    # Another HITL triggered during fast path execution
                    logger.info(
                        f"[ProjectAgentActivity] Nested HITL during fast path: "
                        f"request_id={nested_hitl_ex.request_id}, type={nested_hitl_ex.hitl_type.value}"
                    )

                    # Save state for the new HITL
                    nested_saved_messages = nested_hitl_ex.current_messages or conversation_context_with_response

                    nested_state = HITLAgentState(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        hitl_request_id=nested_hitl_ex.request_id,
                        hitl_type=nested_hitl_ex.hitl_type.value,
                        hitl_request_data=nested_hitl_ex.request_data,
                        messages=nested_saved_messages,
                        user_message=user_message,
                        user_id=user_id,
                        step_count=getattr(agent, "_step_count", 0),
                        timeout_seconds=nested_hitl_ex.timeout_seconds,
                        pending_tool_call_id=nested_hitl_ex.tool_call_id,
                    )

                    nested_state_key = await state_store.save_state(nested_state)

                    # Delete the old state
                    await state_store.delete_state(state_key)

                    # Persist events collected so far
                    if events:
                        await _persist_events(
                            conversation_id=conversation_id,
                            message_id=message_id,
                            events=events,
                            correlation_id=correlation_id,
                        )

                    execution_time_ms = (time_module.time() - start_time) * 1000

                    # Return new HITL pending status
                    return {
                        "hitl_pending": True,
                        "hitl_request_id": nested_hitl_ex.request_id,
                        "hitl_type": nested_hitl_ex.hitl_type.value,
                        "hitl_request_data": nested_hitl_ex.request_data,
                        "hitl_state_key": nested_state_key,
                        "timeout_seconds": nested_hitl_ex.timeout_seconds,
                        "content": "",
                        "sequence_number": sequence_number,
                        "is_error": False,
                        "error_message": None,
                        "execution_time_ms": execution_time_ms,
                        "event_count": len(events),
                    }

            # Fast path timed out - fall back to Workflow Signal
            execution_time_ms = (time_module.time() - start_time) * 1000

            return {
                "hitl_pending": True,
                "hitl_request_id": hitl_ex.request_id,
                "hitl_type": hitl_ex.hitl_type.value,
                "hitl_request_data": hitl_ex.request_data,
                "hitl_state_key": state_key,
                "timeout_seconds": hitl_ex.timeout_seconds,
                "content": "",
                "sequence_number": sequence_number,
                "is_error": False,
                "error_message": None,
                "execution_time_ms": execution_time_ms,
                "event_count": len(events),
            }

        finally:
            await redis_client.aclose()

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        agent_metrics.increment("project_agent.chat_errors")
        logger.error(f"[ProjectAgentActivity] Chat error: {e}", exc_info=True)

        # Publish error event to Redis so frontend receives it
        try:
            await _publish_error_event(
                conversation_id=conversation_id,
                message_id=message_id,
                error_message=str(e),
                correlation_id=correlation_id,
            )
        except Exception as pub_error:
            logger.warning(f"[ProjectAgentActivity] Failed to publish error event: {pub_error}")

        return {
            "content": "",
            "sequence_number": 0,
            "is_error": True,
            "error_message": str(e),
            "execution_time_ms": execution_time_ms,
            "event_count": 0,
        }


@activity.defn
async def continue_project_chat_activity(
    input_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Continue a chat request after receiving HITL response.

    This activity resumes Agent execution after the user has provided
    a response to an HITL request. It:
    1. Loads the saved Agent state from Redis
    2. Injects the HITL response into the Agent context
    3. Continues execution until completion or another HITL request

    Args:
        input_data: Contains:
            - hitl_state_key: Key to load Agent state from Redis
            - hitl_request_id: The HITL request that was answered
            - hitl_response: User's response data
            - correlation_id: Optional request correlation ID
            - config: Project configuration

    Returns:
        Chat result, or another hitl_pending indicator if more input needed
    """
    from src.domain.model.agent.hitl_types import HITLPendingException
    from src.infrastructure.agent.hitl.state_store import (
        HITLAgentState,
        HITLStateStore,
    )

    start_time = time_module.time()
    conversation_id = ""
    message_id = ""

    try:
        # Extract parameters
        hitl_state_key = input_data.get("hitl_state_key", "")
        hitl_request_id = input_data.get("hitl_request_id", "")
        hitl_response = input_data.get("hitl_response", {})
        correlation_id = input_data.get("correlation_id")
        config = input_data.get("config", {})

        logger.info(
            f"[ProjectAgentActivity] Continuing chat: state_key={hitl_state_key}, "
            f"request_id={hitl_request_id}"
        )

        # Get Redis client
        pool = await _get_redis_pool()
        redis_client = aioredis.Redis(connection_pool=pool)

        try:
            # Load saved state
            state_store = HITLStateStore(redis_client)
            state = await state_store.load_state(hitl_state_key)

            if not state:
                # Try loading by request ID
                state = await state_store.load_state_by_request(hitl_request_id)

            if not state:
                logger.error(
                    f"[ProjectAgentActivity] State not found: key={hitl_state_key}, "
                    f"request_id={hitl_request_id}"
                )
                return {
                    "content": "",
                    "sequence_number": 0,
                    "is_error": True,
                    "error_message": "HITL state not found or expired",
                    "execution_time_ms": (time_module.time() - start_time) * 1000,
                    "event_count": 0,
                }

            conversation_id = state.conversation_id
            message_id = state.message_id
            tenant_id = state.tenant_id
            project_id = state.project_id

            # Get or create agent
            agent_mode = config.get("agent_mode", "default")
            agent = _get_cached_project_agent(tenant_id, project_id, agent_mode)

            if not agent:
                # Reinitialize agent
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
                        "error_message": "Failed to reinitialize project agent",
                        "execution_time_ms": (time_module.time() - start_time) * 1000,
                        "event_count": 0,
                    }

                _cache_project_agent(agent)

            # Prepare HITL response for Agent
            hitl_response_for_agent = {
                "request_id": hitl_request_id,
                "hitl_type": state.hitl_type,
                "response_data": hitl_response,
            }

            # Build conversation context with injected tool result
            # This is critical: LLM needs to see the tool result to understand
            # what the user chose, so it can continue from that context
            conversation_context = list(state.messages)

            if state.pending_tool_call_id:
                # Format the HITL response as a tool result
                tool_result_content = _format_hitl_response_as_tool_result(
                    hitl_type=state.hitl_type,
                    response_data=hitl_response,
                )

                # Inject tool result into messages
                conversation_context.append(
                    {
                        "role": "tool",
                        "tool_call_id": state.pending_tool_call_id,
                        "content": tool_result_content,
                    }
                )

                logger.info(
                    f"[ProjectAgentActivity] Injected tool result for call_id="
                    f"{state.pending_tool_call_id}: {tool_result_content[:100]}..."
                )

            # Collect events
            events: List[Dict[str, Any]] = []
            final_content = ""
            is_error = False
            error_message = None
            sequence_number = 0

            # Continue execution with HITL response
            async for event in agent.execute_chat(
                conversation_id=conversation_id,
                user_message=state.user_message,
                user_id=state.user_id,
                conversation_context=conversation_context,
                tenant_id=tenant_id,
                message_id=message_id,
                hitl_response=hitl_response_for_agent,
            ):
                events.append(event)
                sequence_number += 1

                # Publish event to Redis Stream
                await _publish_event_to_stream(
                    conversation_id=conversation_id,
                    event=event,
                    message_id=message_id,
                    sequence_number=sequence_number,
                    correlation_id=correlation_id,
                    redis_client=redis_client,
                )

                # Track important events
                event_type = event.get("type")
                if event_type == "complete":
                    final_content = event.get("data", {}).get("content", "")
                elif event_type == "error":
                    is_error = True
                    error_message = event.get("data", {}).get("message", "Unknown error")

            # Execution completed - clean up state
            await state_store.delete_state(hitl_state_key)

            # Persist events
            await _persist_events(
                conversation_id=conversation_id,
                message_id=message_id,
                events=events,
                correlation_id=correlation_id,
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

            return {
                "content": final_content,
                "sequence_number": sequence_number,
                "is_error": is_error,
                "error_message": error_message,
                "execution_time_ms": execution_time_ms,
                "event_count": len(events),
            }

        except HITLPendingException as hitl_ex:
            # Another HITL request encountered
            logger.info(
                f"[ProjectAgentActivity] Another HITL pending: request_id={hitl_ex.request_id}"
            )

            # Persist events collected so far (including observe events from this step)
            if events:
                await _persist_events(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    events=events,
                    correlation_id=correlation_id,
                )

            # Use current_messages from exception if available (includes assistant's tool call)
            # Fall back to old state.messages if not set (backward compatibility)
            saved_messages = hitl_ex.current_messages or state.messages

            if hitl_ex.current_messages:
                logger.info(
                    f"[ProjectAgentActivity] Saving {len(hitl_ex.current_messages)} messages "
                    f"(with assistant tool call)"
                )
            else:
                logger.warning(
                    f"[ProjectAgentActivity] current_messages not available, "
                    f"falling back to state.messages ({len(state.messages)} messages)"
                )

            # Save new state
            new_state = HITLAgentState(
                conversation_id=conversation_id,
                message_id=message_id,
                tenant_id=state.tenant_id,
                project_id=state.project_id,
                hitl_request_id=hitl_ex.request_id,
                hitl_type=hitl_ex.hitl_type.value,
                hitl_request_data=hitl_ex.request_data,
                messages=saved_messages,
                user_message=state.user_message,
                user_id=state.user_id,
                step_count=state.step_count + 1,
                timeout_seconds=hitl_ex.timeout_seconds,
                pending_tool_call_id=hitl_ex.tool_call_id,
            )

            new_state_key = await state_store.save_state(new_state)

            # Delete old state
            await state_store.delete_state(hitl_state_key)

            execution_time_ms = (time_module.time() - start_time) * 1000

            return {
                "hitl_pending": True,
                "hitl_request_id": hitl_ex.request_id,
                "hitl_type": hitl_ex.hitl_type.value,
                "hitl_request_data": hitl_ex.request_data,
                "hitl_state_key": new_state_key,
                "timeout_seconds": hitl_ex.timeout_seconds,
                "content": "",
                "sequence_number": sequence_number,
                "is_error": False,
                "error_message": None,
                "execution_time_ms": execution_time_ms,
                "event_count": len(events),
            }

        finally:
            await redis_client.aclose()

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        agent_metrics.increment("project_agent.chat_errors")
        logger.error(f"[ProjectAgentActivity] Continue chat error: {e}", exc_info=True)

        # Publish error event
        if conversation_id:
            try:
                await _publish_error_event(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    error_message=str(e),
                    correlation_id=input_data.get("correlation_id"),
                )
            except Exception as pub_error:
                logger.warning(f"[ProjectAgentActivity] Failed to publish error: {pub_error}")

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
    correlation_id: Optional[str] = None,
) -> int:
    """
    Persist agent events to database.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        events: List of events to persist
        correlation_id: Optional request correlation ID

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

                    # Convert 'complete' to 'assistant_message' for unified event type
                    # This ensures historical messages display correctly
                    if event_type == "complete":
                        content = event_data.get("content", "")
                        if content:
                            event_type = "assistant_message"
                            event_data = {
                                "content": content,
                                "message_id": str(uuid.uuid4()),
                                "role": "assistant",
                            }
                            if event.get("data", {}).get("artifacts"):
                                event_data["artifacts"] = event["data"]["artifacts"]
                        else:
                            # Skip empty complete events
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
                            correlation_id=correlation_id,
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


async def _publish_error_event(
    conversation_id: str,
    message_id: str,
    error_message: str,
    correlation_id: Optional[str] = None,
) -> None:
    """
    Publish error event to Redis Stream for frontend notification.

    When an Activity fails unexpectedly, the frontend needs to receive
    an error event to stop waiting and display the error to the user.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        error_message: Error message to display
        correlation_id: Optional request correlation ID
    """
    import json
    from datetime import datetime, timezone

    import redis.asyncio as aioredis

    from src.configuration.config import get_settings

    settings = get_settings()

    try:
        redis_client = aioredis.from_url(settings.redis_url)
        try:
            stream_key = f"agent:events:{conversation_id}"

            # Build error event matching frontend expected format
            error_event = {
                "type": "error",
                "seq": "999999",  # High sequence to ensure it's processed
                "data": json.dumps(
                    {
                        "message": error_message,
                        "code": "ACTIVITY_ERROR",
                    }
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
                "message_id": message_id,
            }
            if correlation_id:
                error_event["correlation_id"] = correlation_id

            # Publish to Redis Stream
            await redis_client.xadd(stream_key, error_event, maxlen=1000)
            logger.info(
                f"[ProjectAgentActivity] Published error event to {stream_key}: {error_message[:100]}"
            )

        finally:
            await redis_client.close()

    except Exception as e:
        logger.error(f"[ProjectAgentActivity] Failed to publish error to Redis: {e}")


async def _get_redis_pool() -> aioredis.ConnectionPool:
    """
    Get or create Redis connection pool for event publishing.

    Uses a global connection pool to minimize connection overhead
    when publishing multiple events during a chat session.
    """
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=20,
            decode_responses=True,
        )
    return _redis_pool


async def _publish_event_to_stream(
    conversation_id: str,
    event: Dict[str, Any],
    message_id: str,
    sequence_number: int,
    correlation_id: Optional[str] = None,
    redis_client: Optional[aioredis.Redis] = None,
) -> None:
    """
    Publish a single event to Redis Stream in real-time.

    This function is called for each event generated during agent execution,
    enabling real-time streaming to the frontend via WebSocket.

    Args:
        conversation_id: Conversation ID (used in stream key)
        event: Event data with 'type' and 'data' fields
        message_id: Associated message ID
        sequence_number: Event sequence number for ordering
        correlation_id: Optional request correlation ID
        redis_client: Optional existing Redis client (for connection reuse)
    """
    should_close = False

    try:
        # Use provided client or create new one
        if redis_client is None:
            pool = await _get_redis_pool()
            redis_client = aioredis.Redis(connection_pool=pool)
            should_close = True

        stream_key = f"agent:events:{conversation_id}"

        # Build event matching the format expected by stream_read()
        # stream_read expects: {"data": JSON_string} where JSON contains:
        # {type, seq, data (nested), timestamp, conversation_id, message_id}
        event_type = event.get("type", "unknown")
        event_data = event.get("data", {})

        # Ensure event_data includes message_id for filtering
        if isinstance(event_data, dict):
            event_data_with_meta = {**event_data, "message_id": message_id}
        else:
            event_data_with_meta = {"content": event_data, "message_id": message_id}

        stream_event_payload = {
            "type": event_type,
            "seq": sequence_number,
            "data": event_data_with_meta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        if correlation_id:
            stream_event_payload["correlation_id"] = correlation_id

        # IMPORTANT: Redis stream_read expects a "data" field with JSON string
        redis_message = {"data": json.dumps(stream_event_payload)}

        # Publish to Redis Stream
        await redis_client.xadd(stream_key, redis_message, maxlen=1000)

        # Debug log for important events only
        if event_type in ("complete", "error", "tool_start", "tool_end"):
            logger.debug(
                f"[ProjectAgentActivity] Published {event_type} event to {stream_key} (seq={sequence_number})"
            )

    except Exception as e:
        # Don't fail the activity on publish error, just log
        logger.warning(f"[ProjectAgentActivity] Failed to publish event to Redis: {e}")

    finally:
        if should_close and redis_client:
            await redis_client.aclose()


async def _wait_for_hitl_response_fast_path(
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    request_id: str,
    hitl_type: str,
    timeout_seconds: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """
    Wait for HITL response via fast path (Redis Streams + SessionRegistry).

    This function attempts to receive HITL responses with minimal latency
    by using the in-process SessionRegistry rather than Temporal Signals.

    The flow:
    1. Ensure HITLResponseListener is listening to this project's stream
    2. Register a waiter in SessionRegistry
    3. HITLResponseListener (running in agent_worker) receives response from Redis Stream
    4. HITLResponseListener delivers response to SessionRegistry
    5. This function receives response and returns

    Args:
        tenant_id: Tenant ID
        project_id: Project ID
        conversation_id: Conversation ID for the request
        request_id: HITL request ID to wait for
        hitl_type: Type of HITL request
        timeout_seconds: Maximum time to wait (default 10s)

    Returns:
        Response data dict if received, None if timeout or error
    """
    try:
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            get_hitl_response_listener,
        )
        from src.infrastructure.agent.hitl.session_registry import get_session_registry

        # Ensure HITLResponseListener is listening to this project's stream
        listener = get_hitl_response_listener()
        if listener:
            await listener.add_project(tenant_id, project_id)
            logger.debug(
                f"[HITL FastPath] Registered project stream: tenant={tenant_id}, project={project_id}"
            )
        else:
            logger.warning("[HITL FastPath] HITLResponseListener not available, skipping fast path")
            return None

        registry = get_session_registry()

        # Register waiter
        await registry.register_waiter(
            request_id=request_id,
            conversation_id=conversation_id,
            hitl_type=hitl_type,
        )

        logger.info(
            f"[HITL FastPath] Registered waiter: request_id={request_id}, "
            f"timeout={timeout_seconds}s"
        )

        # Wait for response
        response = await registry.wait_for_response(
            request_id=request_id,
            timeout=timeout_seconds,
        )

        if response:
            logger.info(
                f"[HITL FastPath] Response received for {request_id} (latency < {timeout_seconds}s)"
            )
            return response
        else:
            logger.debug(
                f"[HITL FastPath] Timeout waiting for {request_id}, falling back to Temporal Signal"
            )
            return None

    except Exception as e:
        logger.warning(f"[HITL FastPath] Error waiting for response: {e}")
        return None
    finally:
        # Always unregister waiter to prevent memory leaks
        try:
            registry = get_session_registry()
            await registry.unregister_waiter(request_id)
        except Exception:
            pass
