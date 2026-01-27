"""
Agent Session Activities for Temporal.

This module provides activity implementations for the AgentSessionWorkflow,
enabling long-lived Agent sessions with cached components.

Activities:
- initialize_agent_session_activity: Initialize session and warm up caches
- execute_chat_activity: Execute a chat request using cached components
- cleanup_agent_session_activity: Clean up session resources
"""

import base64
import json
import logging
import re
import time as time_module
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from temporalio import activity

logger = logging.getLogger(__name__)

_ARTIFACT_STORAGE_ADAPTER = None


async def _get_artifact_storage_adapter():
    """Initialize and cache storage adapter for artifact uploads."""
    global _ARTIFACT_STORAGE_ADAPTER
    if _ARTIFACT_STORAGE_ADAPTER is not None:
        return _ARTIFACT_STORAGE_ADAPTER

    try:
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        settings = get_settings()
        _ARTIFACT_STORAGE_ADAPTER = S3StorageAdapter(
            bucket_name=settings.s3_bucket_name,
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )
        return _ARTIFACT_STORAGE_ADAPTER
    except Exception as e:
        logger.warning(f"[AgentSession] Failed to init artifact storage adapter: {e}")
        return None


def _parse_data_uri(value: str) -> tuple[str | None, str | None]:
    """Parse data URI and return (mime_type, base64_payload)."""
    match = re.match(r"^data:([^;]+);base64,(.*)$", value)
    if not match:
        return None, None
    return match.group(1), match.group(2)


async def _store_artifact(
    conversation_id: str,
    message_id: str,
    content_b64: str,
    mime_type: str,
    source: str,
) -> dict[str, Any] | None:
    """Store artifact content and return reference dict."""
    try:
        from src.configuration.config import get_settings

        settings = get_settings()
        storage = await _get_artifact_storage_adapter()
        if storage is None:
            return None

        content_bytes = base64.b64decode(content_b64)
        ext = mime_type.split("/")[-1] if "/" in mime_type else "bin"
        object_key = f"agent-artifacts/{conversation_id}/{message_id}/{uuid.uuid4()}.{ext}"
        upload_result = await storage.upload_file(
            file_content=content_bytes,
            object_key=object_key,
            content_type=mime_type,
            metadata={"source": source},
        )
        url = await storage.generate_presigned_url(
            object_key=upload_result.object_key,
            expiration_seconds=settings.agent_artifact_url_ttl_seconds,
        )
        return {
            "object_key": upload_result.object_key,
            "url": url,
            "mime_type": upload_result.content_type,
            "size_bytes": upload_result.size_bytes,
            "source": source,
        }
    except Exception as e:
        logger.warning(f"[AgentSession] Failed to store artifact: {e}")
        return None


async def _extract_artifacts_from_event_data(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    """Extract large base64 artifacts from event data and store externally."""
    artifacts: list[Dict[str, Any]] = []
    sanitized = dict(event_data)

    # Direct base64 field
    if isinstance(sanitized.get("image_base64"), str):
        mime_type = sanitized.get("mime_type") or sanitized.get("format") or "image/png"
        artifact = await _store_artifact(
            conversation_id,
            message_id,
            sanitized["image_base64"],
            mime_type,
            source=event_type,
        )
        if artifact:
            artifacts.append(artifact)
            sanitized.pop("image_base64", None)

    # Data URI in content
    if isinstance(sanitized.get("content"), str):
        mime_type, payload = _parse_data_uri(sanitized["content"])
        if payload and mime_type:
            artifact = await _store_artifact(
                conversation_id,
                message_id,
                payload,
                mime_type,
                source=event_type,
            )
            if artifact:
                artifacts.append(artifact)
                sanitized["content"] = "[artifact]"

    # Tool result payloads (stringified or dict)
    result = sanitized.get("result")
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("image_base64"), str):
            mime_type = parsed.get("mime_type") or parsed.get("format") or "image/png"
            artifact = await _store_artifact(
                conversation_id,
                message_id,
                parsed["image_base64"],
                mime_type,
                source=event_type,
            )
            if artifact:
                artifacts.append(artifact)
                parsed.pop("image_base64", None)
                parsed["artifact_url"] = artifact["url"]
                parsed["artifact"] = {
                    "object_key": artifact["object_key"],
                    "mime_type": artifact["mime_type"],
                    "size_bytes": artifact["size_bytes"],
                }
                sanitized["result"] = json.dumps(parsed)
    elif isinstance(result, dict) and isinstance(result.get("image_base64"), str):
        mime_type = result.get("mime_type") or result.get("format") or "image/png"
        artifact = await _store_artifact(
            conversation_id,
            message_id,
            result["image_base64"],
            mime_type,
            source=event_type,
        )
        if artifact:
            artifacts.append(artifact)
            result.pop("image_base64", None)
            result["artifact_url"] = artifact["url"]
            result["artifact"] = {
                "object_key": artifact["object_key"],
                "mime_type": artifact["mime_type"],
                "size_bytes": artifact["size_bytes"],
            }
            sanitized["result"] = result

    if artifacts:
        sanitized["artifacts"] = artifacts

    return sanitized, artifacts


@activity.defn
async def initialize_agent_session_activity(
    config: Any,  # AgentSessionConfig dataclass
) -> Dict[str, Any]:
    """
    Initialize an Agent Session and warm up caches.

    This activity:
    1. Loads tools (including MCP tools)
    2. Initializes SubAgentRouter
    3. Creates SystemPromptManager singleton
    4. Pre-converts tool definitions
    5. Stores session data for reuse

    Args:
        config: AgentSessionConfig containing tenant_id, project_id, agent_mode, etc.

    Returns:
        Initialization result with status and session data
    """
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_agent_graph_service,
        get_or_create_agent_session,
        get_or_create_llm_client,
        get_or_create_provider_config,
        get_or_create_skills,
        get_or_create_tools,
        get_redis_client,
    )
    from src.infrastructure.agent.core.processor import ProcessorConfig

    start_time = time_module.time()

    try:
        # Extract config values (handle both dataclass and dict)
        if hasattr(config, "tenant_id"):
            tenant_id = config.tenant_id
            project_id = config.project_id
            agent_mode = config.agent_mode
            mcp_tools_ttl = getattr(config, "mcp_tools_ttl_seconds", 300)
            temperature = getattr(config, "temperature", 0.7)
            max_tokens = getattr(config, "max_tokens", 4096)
            max_steps = getattr(config, "max_steps", 20)
        else:
            tenant_id = config.get("tenant_id", "")
            project_id = config.get("project_id", "")
            agent_mode = config.get("agent_mode", "default")
            mcp_tools_ttl = config.get("mcp_tools_ttl_seconds", 300)
            temperature = config.get("temperature", 0.7)
            max_tokens = config.get("max_tokens", 4096)
            max_steps = config.get("max_steps", 20)

        logger.info(
            f"[AgentSession] Initializing session: tenant={tenant_id}, "
            f"project={project_id}, mode={agent_mode}"
        )

        # Get shared resources
        graph_service = get_agent_graph_service()
        redis_client = await get_redis_client()

        # Get LLM provider configuration (cached)
        provider_config = await get_or_create_provider_config()

        # Pre-warm LLM client cache
        llm_client = await get_or_create_llm_client(provider_config)

        # Load and cache tools
        tools = await get_or_create_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            graph_service=graph_service,
            redis_client=redis_client,
            llm=llm_client,
            agent_mode=agent_mode,
            mcp_tools_ttl_seconds=mcp_tools_ttl,
            force_mcp_refresh=(mcp_tools_ttl == 0),
        )

        # Load and cache skills
        skills = await get_or_create_skills(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # Create processor config for session
        processor_config = ProcessorConfig(
            model="",  # Set at chat time
            api_key="",
            base_url=None,
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
        )

        # Get or create agent session (warms up all caches)
        session_ctx = await get_or_create_agent_session(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tools=tools,
            skills=skills,
            subagents=[],
            processor_config=processor_config,
        )

        init_time_ms = (time_module.time() - start_time) * 1000

        logger.info(
            f"[AgentSession] Session initialized in {init_time_ms:.1f}ms: "
            f"tenant={tenant_id}, project={project_id}, "
            f"tools={len(tools)}, use_count={session_ctx.use_count}"
        )

        # Return session data for Workflow to store
        return {
            "status": "initialized",
            "tool_count": len(tools),
            "skill_count": len(skills),
            "session_data": {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "agent_mode": agent_mode,
                "provider_type": (
                    provider_config.provider_type.value
                    if hasattr(provider_config.provider_type, "value")
                    else str(provider_config.provider_type)
                ),
                "initialized_at": datetime.now(timezone.utc).isoformat(),
                "init_time_ms": init_time_ms,
            },
        }

    except Exception as e:
        logger.error(f"[AgentSession] Initialization failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


@activity.defn
async def execute_chat_activity(
    input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a chat request using cached session components.

    This activity uses the Agent Session Pool to get pre-initialized
    components, significantly reducing per-request latency.

    Args:
        input: Chat execution input containing:
            - conversation_id: Conversation ID
            - message_id: Message ID
            - user_message: User's message
            - user_id: User ID
            - conversation_context: Conversation history
            - session_config: Session configuration
            - session_data: Cached session data from Workflow

    Returns:
        Chat result with content and metadata
    """
    import os

    from src.infrastructure.adapters.secondary.event.redis_event_bus import RedisEventBusAdapter
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_agent_graph_service,
        get_or_create_agent_session,
        get_or_create_llm_client,
        get_or_create_provider_config,
        get_or_create_skills,
        get_or_create_tools,
        get_redis_client,
    )
    from src.infrastructure.agent.core.processor import ProcessorConfig
    from src.infrastructure.agent.core.react_agent import ReActAgent
    from src.infrastructure.security.encryption_service import get_encryption_service

    start_time = time_module.time()

    try:
        # Extract input parameters
        conversation_id = input.get("conversation_id", "")
        message_id = input.get("message_id", "")
        user_message = input.get("user_message", "")
        user_id = input.get("user_id", "")
        conversation_context = input.get("conversation_context", [])
        session_config = input.get("session_config", {})
        # session_data from Workflow (reserved for future use)
        _ = input.get("session_data", {})

        tenant_id = session_config.get("tenant_id", "")
        project_id = session_config.get("project_id", "")
        agent_mode = session_config.get("agent_mode", "default")

        logger.info(
            f"[AgentSession] Executing chat: conversation={conversation_id}, "
            f"message={message_id}, tenant={tenant_id}, project={project_id}"
        )

        # Get shared resources
        graph_service = get_agent_graph_service()
        redis_client = await get_redis_client()
        event_bus = RedisEventBusAdapter(redis_client)

        # Get LLM provider configuration (cached)
        provider_config = await get_or_create_provider_config()

        # Get cached LLM client
        llm_client = await get_or_create_llm_client(provider_config)

        # Get cached tools
        tools = await get_or_create_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            graph_service=graph_service,
            redis_client=redis_client,
            llm=llm_client,
            agent_mode=agent_mode,
            mcp_tools_ttl_seconds=session_config.get("mcp_tools_ttl_seconds", 300),
        )

        # Get cached skills
        skills = await get_or_create_skills(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # Get cached session context (fast path - should be already cached)
        processor_config = ProcessorConfig(
            model="",
            api_key="",
            base_url=None,
            temperature=session_config.get("temperature", 0.7),
            max_tokens=session_config.get("max_tokens", 4096),
            max_steps=session_config.get("max_steps", 20),
        )

        session_ctx = await get_or_create_agent_session(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tools=tools,
            skills=skills,
            subagents=[],
            processor_config=processor_config,
        )

        cache_time_ms = (time_module.time() - start_time) * 1000
        logger.info(
            f"[AgentSession] Cache retrieval took {cache_time_ms:.1f}ms "
            f"(use_count={session_ctx.use_count})"
        )

        # Construct model name for LiteLLM
        base_model = session_config.get("model") or provider_config.llm_model
        provider_type_str = (
            provider_config.provider_type.value
            if hasattr(provider_config.provider_type, "value")
            else str(provider_config.provider_type)
        )

        if "/" not in base_model:
            if provider_type_str == "zai":
                default_model = f"openai/{base_model}"
            elif provider_type_str == "qwen":
                default_model = f"dashscope/{base_model}"
            else:
                default_model = f"{provider_type_str}/{base_model}"
        else:
            default_model = base_model

        # Decrypt API key
        encryption_service = get_encryption_service()
        api_key = session_config.get("api_key") or encryption_service.decrypt(
            provider_config.api_key_encrypted
        )
        base_url = session_config.get("base_url") or provider_config.base_url

        # Set environment variables for LiteLLM
        if provider_type_str == "zai":
            os.environ["OPENAI_API_KEY"] = api_key
            if base_url:
                os.environ["OPENAI_API_BASE"] = base_url
            else:
                os.environ["OPENAI_API_BASE"] = "https://open.bigmodel.cn/api/paas/v4"
        elif provider_type_str == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
            if base_url:
                os.environ["OPENAI_API_BASE"] = base_url
        elif provider_type_str == "qwen":
            os.environ["DASHSCOPE_API_KEY"] = api_key
        elif provider_type_str == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = api_key
            if base_url:
                os.environ["DEEPSEEK_API_BASE"] = base_url
        elif provider_type_str == "gemini":
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key
        elif provider_type_str == "anthropic":
            os.environ["ANTHROPIC_API_KEY"] = api_key

        # Create ReActAgent with cached components
        agent = ReActAgent(
            model=default_model,
            tools=tools,
            api_key=api_key,
            base_url=base_url,
            temperature=session_config.get("temperature", 0.7),
            max_tokens=session_config.get("max_tokens", 4096),
            max_steps=session_config.get("max_steps", 20),
            agent_mode=agent_mode,
            skills=skills,
            # Use cached components from session pool
            _cached_tool_definitions=session_ctx.tool_definitions,
            _cached_system_prompt_manager=session_ctx.system_prompt_manager,
            _cached_subagent_router=session_ctx.subagent_router,
        )

        agent_init_time_ms = (time_module.time() - start_time) * 1000
        logger.info(f"[AgentSession] Agent initialized in {agent_init_time_ms:.1f}ms total")

        # Get the last sequence number from DB to continue from there
        # This ensures sequence_number is globally consistent across user_message and agent events
        sequence_number = await _get_last_sequence_number(conversation_id)
        logger.info(
            f"[AgentSession] Starting from sequence_number={sequence_number} for conversation={conversation_id}"
        )

        # Track execution
        final_content = ""
        is_error = False
        error_message = None

        from src.configuration.config import get_settings

        settings = get_settings()

        # Pre-generate assistant message ID for consistent references
        assistant_message_id = str(uuid.uuid4())

        # Collect artifacts produced during execution
        collected_artifacts: list[Dict[str, Any]] = []

        # Execute ReActAgent and stream events
        event_count = 0
        # Stream key for persistent storage (Redis Stream)
        stream_key = f"agent:events:{conversation_id}"

        async for event in agent.stream(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_context=conversation_context,
        ):
            event_count += 1
            sequence_number += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # Log important events (reduce noise from text_delta)
            if event_type == "text_delta":
                if event_count <= 3 or event_count % 10 == 0:
                    delta_preview = event_data.get("delta", "")[:20]
                    logger.info(
                        f"[AgentSession] TEXT_DELTA #{event_count}: seq={sequence_number}, "
                        f"delta='{delta_preview}...'"
                    )
            else:
                logger.info(
                    f"[AgentSession] Event #{event_count}: type={event_type}, seq={sequence_number}"
                )

            # Inject message_id for frontend filtering
            event_data_with_message_id = {**event_data, "message_id": message_id}

            # Extract and externalize artifacts (e.g., screenshots) to avoid large payloads
            event_data_with_message_id, artifacts = await _extract_artifacts_from_event_data(
                conversation_id=conversation_id,
                message_id=message_id,
                event_type=event_type,
                event_data=event_data_with_message_id,
            )
            if artifacts:
                collected_artifacts.extend(artifacts)

            # Filter empty thoughts and optionally suppress thought streaming
            should_publish = True
            if event_type == "thought":
                thought_text = (
                    event_data_with_message_id.get("thought")
                    or event_data_with_message_id.get("content")
                    or ""
                )
                if not thought_text.strip():
                    continue
                if not settings.agent_emit_thoughts:
                    should_publish = False

            # Attach artifacts to complete event for downstream rendering
            if event_type == "complete":
                event_data_with_message_id["id"] = assistant_message_id
                event_data_with_message_id["assistant_message_id"] = assistant_message_id
                if collected_artifacts:
                    event_data_with_message_id["artifacts"] = collected_artifacts

            # Track content
            if event_type == "text_delta":
                final_content += event_data_with_message_id.get("delta", "")
            elif event_type == "complete":
                final_content = event_data_with_message_id.get("content", final_content)
            elif event_type == "error":
                is_error = True
                error_message = event_data_with_message_id.get("message", "Unknown error")

            # Construct event payload using EventSerializer (single source of truth)
            # This replaces manual event construction with a unified serialization approach
            event_payload = {
                "type": event_type,
                "data": event_data_with_message_id,
                "seq": sequence_number,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # ================================================================
            # Simplified event publication (single-write to Redis Stream):
            # - Redis Stream provides both persistence AND real-time delivery via XREAD
            # - Removed: Redis List buffer (redundant - Stream has replay capability)
            # - Removed: Redis Pub/Sub (redundant - Stream XREAD with block=0 provides real-time)
            # ================================================================

            try:
                if should_publish:
                    # Single write to Redis Stream (persistent, replayable, real-time)
                    # Auto-trim to 1000 messages per conversation to prevent unbounded growth
                    await event_bus.stream_add(stream_key, event_payload, maxlen=1000)

            except Exception as publish_err:
                logger.warning(f"[AgentSession] Failed to publish event: {publish_err}")

            # Save to DB (skip delta & noisy events for performance)
            await _save_event_to_db(
                conversation_id,
                message_id,
                event_type,
                event_data_with_message_id,
                sequence_number,
            )

            # Buffer text_delta events to database for debugging/late replay
            if event_type in BUFFER_EVENT_TYPES:
                await _save_text_delta_to_buffer(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type=event_type,
                    event_data=event_data_with_message_id,
                    sequence_number=sequence_number,
                    ttl_seconds=300,  # 5 minutes
                )

        # Save assistant message if completed successfully
        if not is_error and final_content:
            sequence_number += 1
            await _save_assistant_message_event(
                conversation_id=conversation_id,
                message_id=message_id,
                content=final_content,
                assistant_message_id=assistant_message_id,
                artifacts=collected_artifacts or None,
                sequence_number=sequence_number,
            )

        total_time_ms = (time_module.time() - start_time) * 1000
        logger.info(
            f"[AgentSession] Chat completed in {total_time_ms:.1f}ms: "
            f"conversation={conversation_id}, error={is_error}"
        )

        return {
            "content": final_content,
            "sequence_number": sequence_number,
            "is_error": is_error,
            "error_message": error_message,
            "execution_time_ms": total_time_ms,
        }

    except Exception as e:
        logger.error(f"[AgentSession] Chat execution failed: {e}", exc_info=True)
        return {
            "content": "",
            "sequence_number": 0,
            "is_error": True,
            "error_message": str(e),
        }


@activity.defn
async def cleanup_agent_session_activity(
    config: Any,  # AgentSessionConfig dataclass
) -> Dict[str, Any]:
    """
    Clean up Agent Session resources.

    This activity is called when the session workflow is stopping.
    It clears session-specific caches to free memory.

    Args:
        config: AgentSessionConfig

    Returns:
        Cleanup result
    """
    from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
        clear_session_cache,
    )

    try:
        # Extract config values
        if hasattr(config, "tenant_id"):
            tenant_id = config.tenant_id
            project_id = config.project_id
            agent_mode = config.agent_mode
        else:
            tenant_id = config.get("tenant_id", "")
            project_id = config.get("project_id", "")
            agent_mode = config.get("agent_mode", "default")

        logger.info(
            f"[AgentSession] Cleaning up session: tenant={tenant_id}, "
            f"project={project_id}, mode={agent_mode}"
        )

        # Clear session-specific cache
        cleared = await clear_session_cache(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )

        logger.info(
            f"[AgentSession] Cleanup completed: tenant={tenant_id}, "
            f"project={project_id}, cleared={cleared}"
        )

        return {
            "status": "cleaned",
            "cleared": cleared,
        }

    except Exception as e:
        logger.error(f"[AgentSession] Cleanup failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# Helper functions (imported from agent.py to avoid duplication)
# ============================================================================


# Delta event types to skip persisting to main DB table
# These are stored in Redis Stream instead for better performance
SKIP_PERSIST_EVENT_TYPES = {
    "thought_delta",
    "text_delta",
    "text_start",
    "text_end",
}

# Noisy event types to skip when persistence is disabled
NOISY_EVENT_TYPES = {
    "step_start",
    "step_end",
    "act",
    "observe",
    "tool_start",
    "tool_result",
    "cost_update",
    "pattern_match",
}

# Event types to save to text_delta buffer table (for debugging and late replay)
# These events are auto-cleaned after 5 minutes
BUFFER_EVENT_TYPES = {
    "text_delta",
    "text_start",
    "text_end",
}


async def _get_last_sequence_number(conversation_id: str) -> int:
    """Get the last sequence number for a conversation from the database.

    This ensures that agent events continue from the correct sequence number
    after user_message events are saved by the service layer.
    """
    from sqlalchemy import func, select

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(func.max(AgentExecutionEvent.sequence_number)).where(
                    AgentExecutionEvent.conversation_id == conversation_id
                )
            )
            last_seq = result.scalar()
            return last_seq if last_seq is not None else 0
    except Exception as e:
        logger.warning(f"Failed to get last sequence number: {e}, defaulting to 0")
        return 0


async def _save_event_to_db(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
) -> None:
    """Save event to DB with idempotency guarantee."""
    if event_type in SKIP_PERSIST_EVENT_TYPES:
        return

    from src.configuration.config import get_settings

    settings = get_settings()
    if event_type == "thought" and not settings.agent_persist_thoughts:
        return
    if not settings.agent_persist_detail_events and event_type in NOISY_EVENT_TYPES:
        return

    import uuid

    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    try:
        async with async_session_factory() as session:
            async with session.begin():
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
                    .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
                )
                await session.execute(stmt)
    except IntegrityError as e:
        if "uq_agent_events_conv_seq" in str(e):
            logger.warning(
                f"Event already exists (conv={conversation_id}, seq={sequence_number}). "
                "Skipping duplicate."
            )
            return
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save event to DB: {e}")
        raise


async def _save_text_delta_to_buffer(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
    ttl_seconds: int = 300,  # 5 minutes default
) -> None:
    """
    Save text_delta event to short-term buffer table for debugging and late replay.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event_type: Event type (text_delta, text_start, text_end)
        event_data: Full event data
        sequence_number: Sequence number
        ttl_seconds: Time-to-live in seconds (default 5 minutes)
    """
    if event_type not in BUFFER_EVENT_TYPES:
        return

    import uuid
    from datetime import timedelta

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import TextDeltaBuffer

    try:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        delta_content = event_data.get("delta", "") if event_type == "text_delta" else None

        async with async_session_factory() as session:
            async with session.begin():
                buffer_event = TextDeltaBuffer(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type=event_type,
                    delta_content=delta_content,
                    event_data=event_data,
                    sequence_number=sequence_number,
                    expires_at=expires_at,
                )
                session.add(buffer_event)

    except Exception as e:
        # Non-critical, just log and continue
        logger.warning(f"[AgentSession] Failed to buffer text_delta: {e}", exc_info=True)


async def _cleanup_expired_text_delta_buffer() -> int:
    """
    Clean up expired text_delta buffer entries.

    This should be called periodically (e.g., every minute) to remove expired entries.

    Returns:
        Number of entries deleted
    """
    from sqlalchemy import delete

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import TextDeltaBuffer

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(TextDeltaBuffer).where(
                        TextDeltaBuffer.expires_at < datetime.now(timezone.utc)
                    )
                )
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"[TextDeltaBuffer] Cleaned up {deleted_count} expired entries")
                return deleted_count
    except Exception as e:
        logger.warning(f"[TextDeltaBuffer] Failed to cleanup: {e}")
        return 0


async def _save_assistant_message_event(
    conversation_id: str,
    message_id: str,
    content: str,
    sequence_number: int,
    assistant_message_id: Optional[str] = None,
    artifacts: Optional[list[Dict[str, Any]]] = None,
) -> str:
    """Save assistant_message event to unified event timeline."""
    import uuid

    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    assistant_msg_id = assistant_message_id or str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    insert(AgentExecutionEvent)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type="assistant_message",
                        event_data={
                            "content": content,
                            "message_id": assistant_msg_id,
                            "role": "assistant",
                            "artifacts": artifacts or [],
                        },
                        sequence_number=sequence_number,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
                )
                await session.execute(stmt)
        logger.info(
            f"Saved assistant_message event {assistant_msg_id} to conversation {conversation_id}"
        )
        return assistant_msg_id
    except IntegrityError as e:
        if "uq_agent_events_conv_seq" in str(e):
            logger.warning(
                f"assistant_message event already exists (conv={conversation_id}, "
                f"seq={sequence_number}). Skipping duplicate."
            )
            return assistant_msg_id
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
