"""
Temporal Activities for Agent Execution.

This module provides activity implementations for the agent execution workflow,
including LLM calls, tool execution, and event persistence.
"""

import base64
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity

from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
    get_agent_graph_service, get_redis_client)

logger = logging.getLogger(__name__)

_ARTIFACT_STORAGE_ADAPTER = None


async def _get_artifact_storage_adapter():
    """Initialize and cache storage adapter for artifact uploads."""
    global _ARTIFACT_STORAGE_ADAPTER
    if _ARTIFACT_STORAGE_ADAPTER is not None:
        return _ARTIFACT_STORAGE_ADAPTER

    try:
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import \
            S3StorageAdapter

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
        logger.warning(f"[AgentActivity] Failed to init artifact storage adapter: {e}")
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
) -> Dict[str, Any] | None:
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
        logger.warning(f"[AgentActivity] Failed to store artifact: {e}")
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
async def execute_react_step_activity(
    input: Dict[str, Any],
    state: Dict[str, Any],
    signal_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    Execute a single ReAct step (LLM call + optional tool execution).

    This activity performs:
    1. Calls LLM with conversation context (streaming)
    2. Publishes events to Redis and DB
    3. Parses response for thoughts and tool calls
    4. Executes tool calls if any
    5. Returns result for workflow continuation

    Args:
        input: Agent execution input
        state: Current execution state
        signal_callback: Callback to send signals to workflow

    Returns:
        Step result dictionary with type: 'complete', 'error', or 'continue'
    """
    redis_client = None
    try:
        # Import dependencies here to avoid import issues in worker
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.event.redis_event_bus import \
            RedisEventBusAdapter
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import \
            get_or_create_provider_config
        from src.infrastructure.llm.litellm.litellm_client import \
            create_litellm_client

        settings = get_settings()

        # Use pooled Redis connection for streaming
        redis_client = await get_redis_client()
        event_bus = RedisEventBusAdapter(redis_client)

        # Reconstruct input from dict
        conversation_id = input.get("conversation_id", "")
        message_id = input.get("message_id", "")
        user_message = input.get("user_message", "")
        conversation_context = input.get("conversation_context", [])
        agent_config = input.get("agent_config", {})

        # Get default model based on current LLM provider
        provider = settings.llm_provider.lower()
        default_models = {
            "qwen": settings.qwen_model,
            "gemini": settings.gemini_model,
            "openai": settings.openai_model,
            "deepseek": settings.deepseek_model,
            "zai": settings.zai_model,
            "zhipu": settings.zhipu_model,
        }
        _model = agent_config.get("model", default_models.get(provider, settings.qwen_model))  # noqa: F841
        _api_key = agent_config.get("api_key")  # noqa: F841 - Reserved for future use
        _base_url = agent_config.get("base_url")  # noqa: F841 - Reserved for future use

        # Get current step from state
        current_step = state.get("current_step", 1)
        sequence_number = state.get("sequence_number", 0)
        messages = state.get("messages", [])

        # Sync sequence_number from DB to handle Temporal retry scenarios
        # When Activity is retried, state.sequence_number may be stale
        sequence_number = await _sync_sequence_number_from_db(conversation_id, sequence_number)

        # Add conversation context if this is the first step
        if current_step == 1:
            # Build messages from conversation context
            for msg in conversation_context[-10:]:  # Last 10 messages
                messages.append(
                    {
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", ""),
                    }
                )
            # Add current user message
            messages.append(
                {
                    "role": "user",
                    "content": user_message,
                }
            )

        # Create LLM client using factory function
        # Get default provider from cache
        provider_config = await get_or_create_provider_config()

        llm_client = create_litellm_client(provider_config)

        # Get tools from agent config
        tools = agent_config.get("tools", [])
        tool_definitions = _get_tool_definitions(tools)

        # Stream LLM response
        content = ""
        tool_calls = []
        tool_calls_buffer: Dict[int, Dict[str, Any]] = {}  # Index by tool call index
        finish_reason = "stop"

        # Stream channel
        stream_channel = f"agent:stream:{conversation_id}"

        assistant_message_id = str(uuid.uuid4())
        collected_artifacts: list[Dict[str, Any]] = []

        # Send text_start event at the beginning of streaming
        sequence_number += 1
        text_start_data, _ = await _extract_artifacts_from_event_data(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type="text_start",
            event_data={"message_id": message_id},
        )
        await event_bus.publish(
            stream_channel,
            {
                "type": "text_start",
                "data": text_start_data,
                "seq": sequence_number,
            },
        )
        await _save_event_to_db(
            conversation_id,
            message_id,
            "text_start",
            text_start_data,
            sequence_number,
        )

        async for chunk in llm_client.generate_stream(
            messages=messages,
            tools=tool_definitions if tool_definitions else None,
            temperature=agent_config.get("temperature", 0.0),
            max_tokens=agent_config.get("max_tokens", 4096),
        ):
            delta = chunk.choices[0].delta
            content_delta = delta.content or ""

            # Handle tool calls from stream delta
            # OpenAI format: delta.tool_calls is a list of tool call updates
            if delta.tool_calls:
                for tool_call_delta in delta.tool_calls:
                    idx = tool_call_delta.index  # Tool call index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tool_call_delta.id or f"call_{idx}",
                            "function": {"name": "", "arguments": ""},
                        }

                    # Accumulate function name
                    if tool_call_delta.function and tool_call_delta.function.name:
                        tool_calls_buffer[idx]["function"]["name"] = tool_call_delta.function.name

                    # Accumulate function arguments (may come in chunks)
                    if tool_call_delta.function and tool_call_delta.function.arguments:
                        current_args = tool_calls_buffer[idx]["function"]["arguments"]
                        tool_calls_buffer[idx]["function"]["arguments"] = (
                            current_args + tool_call_delta.function.arguments
                        )

            if content_delta:
                content += content_delta
                sequence_number += 1

                text_delta_data, _ = await _extract_artifacts_from_event_data(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type="text_delta",
                    event_data={"delta": content_delta, "message_id": message_id},
                )
                event_payload = {
                    "type": "text_delta",
                    "data": text_delta_data,
                    "seq": sequence_number,
                }

                # Publish to Redis
                await event_bus.publish(stream_channel, event_payload)

                # Save to DB
                await _save_event_to_db(
                    conversation_id,
                    message_id,
                    "text_delta",
                    text_delta_data,
                    sequence_number,
                )

            # Check finish reason
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        # Send text_end event after streaming completes
        sequence_number += 1
        text_end_data, _ = await _extract_artifacts_from_event_data(
            conversation_id=conversation_id,
            message_id=message_id,
            event_type="text_end",
            event_data={"full_text": content, "message_id": message_id},
        )
        await event_bus.publish(
            stream_channel,
            {
                "type": "text_end",
                "data": text_end_data,
                "seq": sequence_number,
            },
        )
        await _save_event_to_db(
            conversation_id,
            message_id,
            "text_end",
            text_end_data,
            sequence_number,
        )

        # Save intermediate assistant_message if content exists (even with tool calls)
        # This ensures text responses in ReAct loop are saved separately
        intermediate_assistant_message_id = None
        if content and content.strip():
            sequence_number += 1
            intermediate_assistant_message_id = str(uuid.uuid4())
            await _save_assistant_message_event(
                conversation_id=conversation_id,
                message_id=message_id,
                content=content,
                assistant_message_id=intermediate_assistant_message_id,
                artifacts=None,  # Artifacts attached at complete event
                sequence_number=sequence_number,
            )
            logger.info(
                f"Saved intermediate assistant_message {intermediate_assistant_message_id} "
                f"for conversation {conversation_id}"
            )

        # Assemble accumulated tool calls from buffer
        if tool_calls_buffer:
            tool_calls = list(tool_calls_buffer.values())
            # Parse arguments as JSON for each tool call
            for tool_call in tool_calls:
                try:
                    args_str = tool_call["function"]["arguments"]
                    if args_str:
                        tool_call["function"]["arguments"] = json.loads(args_str)
                except json.JSONDecodeError:
                    # Arguments might be incomplete, leave as string
                    pass

        # If no tool calls were accumulated but content is empty (likely tool call scenario),
        # fall back to non-streaming call for reliability
        if not tool_calls and not content:
            # Likely a tool call that wasn't properly accumulated
            # Rerun non-streaming to get structured tool calls
            response = await llm_client.generate(
                messages=messages,
                tools=tool_definitions if tool_definitions else None,
                temperature=agent_config.get("temperature", 0.0),
                max_tokens=agent_config.get("max_tokens", 4096),
            )
            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "") or ""
            finish_reason = response.get("finish_reason", "stop")

        # Update messages with assistant response
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls if tool_calls else None,
            }
        )

        # Execute tool calls if present
        tool_results = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "")
            tool_args_raw = tool_call.get("function", {}).get("arguments", {})

            # Handle both dict (already parsed) and JSON string formats
            if isinstance(tool_args_raw, dict):
                tool_args = tool_args_raw
            elif isinstance(tool_args_raw, str):
                try:
                    tool_args = json.loads(tool_args_raw) if tool_args_raw else {}
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments: {tool_args_raw}")
                    tool_args = {}
            else:
                tool_args = {}

            call_id = tool_call.get("id", str(uuid.uuid4()))

            # Publish tool start event
            sequence_number += 1
            tool_start_data, _ = await _extract_artifacts_from_event_data(
                conversation_id=conversation_id,
                message_id=message_id,
                event_type="tool_start",
                event_data={"tool": tool_name, "input": tool_args},
            )
            await event_bus.publish(
                stream_channel,
                {
                    "type": "tool_start",
                    "data": tool_start_data,
                    "seq": sequence_number,
                },
            )
            await _save_event_to_db(
                conversation_id,
                message_id,
                "tool_start",
                tool_start_data,
                sequence_number,
            )

            # Execute tool
            try:
                graph_service = get_agent_graph_service()
                result = await _execute_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    project_id=input.get("project_id", ""),
                    user_id=input.get("user_id", ""),
                    tenant_id=input.get("tenant_id", ""),
                    graph_service=graph_service,
                )

                # Save tool execution record
                await _save_tool_execution_record(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_name=tool_name,
                    tool_input=tool_args,
                    tool_output=result,
                    status="success",
                )

                tool_results.append(
                    {
                        "tool": tool_name,
                        "result": result,
                        "status": "success",
                    }
                )

                # Publish tool result
                sequence_number += 1
                tool_result_data, artifacts = await _extract_artifacts_from_event_data(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type="tool_result",
                    event_data={"tool": tool_name, "result": result},
                )
                if artifacts:
                    collected_artifacts.extend(artifacts)
                await event_bus.publish(
                    stream_channel,
                    {
                        "type": "tool_result",
                        "data": tool_result_data,
                        "seq": sequence_number,
                    },
                )
                await _save_event_to_db(
                    conversation_id,
                    message_id,
                    "tool_result",
                    tool_result_data,
                    sequence_number,
                )

                # Add tool result to messages
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                    }
                )

            except Exception as e:
                logger.error(f"Tool execution error: {e}", exc_info=True)
                error_msg = f"Error executing tool {tool_name}: {str(e)}"

                await _save_tool_execution_record(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_name=tool_name,
                    tool_input=tool_args,
                    tool_output=None,
                    status="error",
                    error_message=str(e),
                )

                tool_results.append(
                    {
                        "tool": tool_name,
                        "error": str(e),
                        "status": "error",
                    }
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": error_msg,
                    }
                )

        # Return result based on finish reason
        result_type = "continue"
        if finish_reason == "stop" and not tool_calls:
            result_type = "complete"
        elif finish_reason == "length":
            result_type = "compact"

        # Send complete event to Redis when finished
        if result_type == "complete":
            # Use intermediate assistant_message_id if content was already saved,
            # otherwise save it now
            final_message_id = intermediate_assistant_message_id
            if not final_message_id and content and content.strip():
                # Content not saved yet, save it now
                sequence_number += 1
                final_message_id = await _save_assistant_message_event(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    content=content,
                    assistant_message_id=assistant_message_id,
                    artifacts=collected_artifacts or None,
                    sequence_number=sequence_number,
                )
            elif final_message_id:
                # Content already saved, just log
                logger.info(
                    f"Using previously saved assistant_message {final_message_id} "
                    f"for complete event"
                )

            # Use the final message ID (either intermediate or new)
            complete_message_id = final_message_id or assistant_message_id

            sequence_number += 1
            complete_data = {
                "id": complete_message_id,
                "assistant_message_id": complete_message_id,
                "content": content,
                "message_id": message_id,  # Original user message ID for reference
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if collected_artifacts:
                complete_data["artifacts"] = collected_artifacts
            complete_event = {
                "type": "complete",
                "data": complete_data,
                "seq": sequence_number,
            }
            await event_bus.publish(stream_channel, complete_event)
            await _save_event_to_db(
                conversation_id,
                message_id,
                "complete",
                complete_data,
                sequence_number,
            )

            logger.info(
                f"Published complete event for conversation {conversation_id}, "
                f"assistant message {complete_message_id}"
            )

        return {
            "type": result_type,
            "content": content,
            "tool_results": tool_results,
            "messages": messages,
            "step": current_step,
            "sequence_number": sequence_number,  # Return updated sequence
        }

    except Exception as e:
        logger.error(f"Error executing ReAct step activity: {e}", exc_info=True)
        return {
            "type": "error",
            "error": str(e),
        }
    # Note: No need to close redis_client as it's from a pool


@activity.defn
async def save_event_activity(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
) -> None:
    """Activity for saving SSE events to database."""
    await _save_event_to_db(conversation_id, message_id, event_type, event_data, sequence_number)


async def _sync_sequence_number_from_db(
    conversation_id: str,
    state_sequence_number: int,
) -> int:
    """Sync sequence_number from database to handle Temporal retry scenarios.

    When an Activity is retried by Temporal, the state.sequence_number passed in
    may be stale (from before the retry). This function queries the database
    for the actual last sequence number and returns the correct starting point.

    Args:
        conversation_id: The conversation ID to query
        state_sequence_number: The sequence number from Activity state

    Returns:
        The correct sequence number to start from (max of state and DB)
    """
    from sqlalchemy import func, select

    from src.infrastructure.adapters.secondary.persistence.database import \
        async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import \
        AgentExecutionEvent

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(func.max(AgentExecutionEvent.sequence_number)).where(
                    AgentExecutionEvent.conversation_id == conversation_id
                )
            )
            db_last_seq = result.scalar() or 0

            if db_last_seq > state_sequence_number:
                logger.warning(
                    f"Temporal retry detected for conversation={conversation_id}. "
                    f"Syncing sequence_number from {state_sequence_number} to {db_last_seq} "
                    "(DB has more recent events)."
                )
                return db_last_seq

            return state_sequence_number
    except Exception as e:
        logger.error(f"Failed to sync sequence_number from DB: {e}")
        # Fall back to state value if DB query fails
        return state_sequence_number


# Delta event types to skip persisting to DB
# These are streaming fragments; complete events (thought, act, observe, etc.) are kept
SKIP_PERSIST_EVENT_TYPES = {
    "thought_delta",  # Streaming thought fragments -> complete 'thought' event exists
    "text_delta",  # Streaming text fragments -> content in 'assistant_message'
    "text_start",  # Stream start marker
    "text_end",  # Stream end marker
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


async def _save_event_to_db(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
) -> None:
    """Helper to save event to DB with idempotency guarantee.

    Uses INSERT ON CONFLICT DO NOTHING to handle Temporal retry scenarios
    where the same (conversation_id, sequence_number) may be saved twice.

    Delta events are skipped - frontend renders complete events (thought,
    act, observe, assistant_message) for historical message display.
    """
    from src.configuration.config import get_settings

    settings = get_settings()

    # Skip delta events - complete events are stored for history rendering
    if event_type in SKIP_PERSIST_EVENT_TYPES:
        return
    if not settings.agent_persist_thoughts and event_type == "thought":
        return
    if not settings.agent_persist_detail_events and event_type in NOISY_EVENT_TYPES:
        return
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import \
        async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import \
        AgentExecutionEvent

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
        # Unique constraint violation - event already exists (likely Temporal retry)
        if "uq_agent_events_conv_seq" in str(e):
            logger.warning(
                f"Event already exists (conv={conversation_id}, seq={sequence_number}). "
                "Skipping duplicate save due to Temporal retry."
            )
            return  # Don't raise - treat as idempotent success
        # Other integrity errors should be raised
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save event to DB: {e}")
        raise  # Raise to let Temporal handle retry


async def _save_assistant_message_event(
    conversation_id: str,
    message_id: str,
    content: str,
    assistant_message_id: Optional[str] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    sequence_number: int = 0,
) -> str:
    """Helper to save assistant_message event to unified event timeline.

    Saves an assistant_message event to agent_execution_events table instead
    of the deprecated messages table.

    Returns:
        The ID of the assistant message (for reference in other events).
    """
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import \
        async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import \
        AgentExecutionEvent

    assistant_msg_id = assistant_message_id or str(uuid.uuid4())
    event_data = {
        "content": content,
        "message_id": assistant_msg_id,
        "role": "assistant",
    }
    if artifacts:
        event_data["artifacts"] = artifacts
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
                        event_data=event_data,
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
        return assistant_msg_id  # Return the ID even on error so complete event has it


@activity.defn
async def save_checkpoint_activity(
    conversation_id: str,
    message_id: str,
    checkpoint_type: str,
    execution_state: Dict[str, Any],
    step_number: Optional[int] = None,
) -> str:
    """
    Activity for saving execution checkpoints.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        checkpoint_type: Type of checkpoint
        execution_state: Full execution state snapshot
        step_number: Current step number

    Returns:
        Created checkpoint ID
    """
    from src.infrastructure.adapters.secondary.persistence.database import \
        async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import \
        ExecutionCheckpoint

    async with async_session_factory() as session:
        async with session.begin():
            checkpoint = ExecutionCheckpoint(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                message_id=message_id,
                checkpoint_type=checkpoint_type,
                execution_state=execution_state,
                step_number=step_number,
                created_at=datetime.now(timezone.utc),
            )
            session.add(checkpoint)
            await session.flush()

            return checkpoint.id


@activity.defn
async def set_agent_running(conversation_id: str, message_id: str, ttl_seconds: int = 300) -> None:
    """
    Activity for marking an agent execution as running in Redis.

    Args:
        conversation_id: Conversation ID
        message_id: Current message ID being processed
        ttl_seconds: Time to live for the running key (default 5 minutes)
    """
    # Use pooled Redis connection
    redis_client = await get_redis_client()

    # Set a key with TTL to track active execution
    key = f"agent:running:{conversation_id}"
    await redis_client.setex(
        key,
        ttl_seconds,
        message_id,  # Store the message_id as the value
    )
    logger.info(f"Set agent running state: {key} -> {message_id} (TTL={ttl_seconds}s)")


@activity.defn
async def clear_agent_running(conversation_id: str) -> None:
    """
    Activity for clearing the agent running state in Redis.

    Args:
        conversation_id: Conversation ID
    """
    # Use pooled Redis connection
    redis_client = await get_redis_client()

    key = f"agent:running:{conversation_id}"
    await redis_client.delete(key)
    logger.info(f"Cleared agent running state: {key}")


@activity.defn
async def refresh_agent_running_ttl(conversation_id: str, ttl_seconds: int = 300) -> None:
    """
    Activity for refreshing the agent running state TTL in Redis.

    This should be called periodically during long-running executions
    to prevent the running key from expiring.

    Args:
        conversation_id: Conversation ID
        ttl_seconds: Time to live for the running key (default 5 minutes)
    """
    # Use pooled Redis connection
    redis_client = await get_redis_client()

    key = f"agent:running:{conversation_id}"
    await redis_client.expire(key, ttl_seconds)
    logger.debug(f"Refreshed agent running TTL: {key} (TTL={ttl_seconds}s)")


# Helper functions


def _get_tool_definitions(tools_config: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Get tool definitions in OpenAI format.

    Args:
        tools_config: List of tool configurations

    Returns:
        List of tool definitions
    """
    definitions = []

    for tool in tools_config:
        tool_name = tool.get("name")
        tool_description = tool.get("description", "")
        tool_parameters = tool.get(
            "parameters", {"type": "object", "properties": {}, "required": []}
        )

        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": tool_parameters,
                },
            }
        )

    return definitions


async def _execute_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Any:
    """
    Execute a tool by name.

    Args:
        tool_name: Name of tool to execute
        tool_args: Tool arguments
        project_id: Project ID
        user_id: User ID
        tenant_id: Tenant ID
        graph_service: Graph service instance

    Returns:
        Tool execution result
    """

    # Map tool names to their implementations
    tool_implementations = {
        "memory_search": _execute_memory_search,
        "entity_lookup": _execute_entity_lookup,
        "graph_query": _execute_graph_query,
        "memory_create": _execute_memory_create,
        "web_search": _execute_web_search,
        "web_scrape": _execute_web_scrape,
        "summary": _execute_summary,
    }

    if tool_name not in tool_implementations:
        raise ValueError(f"Unknown tool: {tool_name}")

    # Get tool implementation
    tool_func = tool_implementations[tool_name]

    # Execute tool
    return await tool_func(
        tool_args=tool_args,
        project_id=project_id,
        user_id=user_id,
        tenant_id=tenant_id,
        graph_service=graph_service,
    )


async def _execute_memory_search(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute memory search tool."""
    query = tool_args.get("query", "")
    limit = tool_args.get("limit", 10)

    from src.domain.ports.services.graph_service_port import GraphServicePort

    if not isinstance(graph_service, GraphServicePort):
        return {"error": "Graph service not available"}

    # Perform semantic search
    results = await graph_service.search_memories(
        project_id=project_id,
        query=query,
        limit=limit,
    )

    return {
        "query": query,
        "results": results,
        "count": len(results) if results else 0,
    }


async def _execute_entity_lookup(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute entity lookup tool."""
    entity_name = tool_args.get("name", "")

    from src.infrastructure.graph.native_graph_adapter import \
        NativeGraphAdapter

    if not isinstance(graph_service, NativeGraphAdapter):
        return {"error": "Graph service not available"}

    # Lookup entity
    client = graph_service.client
    result = await client.execute_query(
        "MATCH (e:Entity {name: $name, project_id: $project_id}) RETURN e LIMIT 1",
        name=entity_name,
        project_id=project_id,
    )

    if result and result.get("data"):
        entity = result["data"][0].get("e")
        return {
            "name": entity.get("name"),
            "entity_type": entity.get("entity_type"),
            "summary": entity.get("summary"),
            "attributes": entity.get("attributes", {}),
        }

    return {"error": f"Entity '{entity_name}' not found"}


async def _execute_graph_query(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute graph query tool."""
    query = tool_args.get("query", "")
    params = tool_args.get("params", {})

    from src.infrastructure.graph.native_graph_adapter import \
        NativeGraphAdapter

    if not isinstance(graph_service, NativeGraphAdapter):
        return {"error": "Graph service not available"}

    client = graph_service.client
    result = await client.execute_query(query, **params)

    return {
        "query": query,
        "result": result,
    }


async def _execute_memory_create(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute memory create tool."""
    content = tool_args.get("content", "")

    from src.domain.ports.services.graph_service_port import GraphServicePort

    if not isinstance(graph_service, GraphServicePort):
        return {"error": "Graph service not available"}

    # Create memory
    memory_id = await graph_service.create_memory(
        project_id=project_id,
        content=content,
        user_id=user_id,
    )

    return {
        "memory_id": memory_id,
        "status": "created",
    }


async def _execute_web_search(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute web search tool."""
    query = tool_args.get("query", "")
    num_results = tool_args.get("num_results", 5)

    # For now, return a placeholder
    # In production, integrate with actual search API
    return {
        "query": query,
        "results": [
            {
                "title": f"Search result for: {query}",
                "url": "https://example.com",
                "snippet": f"Placeholder search result for {query}",
            }
        ],
        "count": num_results,
    }


async def _execute_web_scrape(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute web scrape tool."""
    url = tool_args.get("url", "")

    # For now, return a placeholder
    # In production, integrate with actual scraping service
    return {
        "url": url,
        "content": f"Placeholder scraped content from {url}",
        "title": "Scraped Page",
    }


async def _execute_summary(
    tool_args: Dict[str, Any],
    project_id: str,
    user_id: str,
    tenant_id: str,
    graph_service: Any,
) -> Dict[str, Any]:
    """Execute summary tool."""
    content = tool_args.get("content", "")

    # For now, return a truncated version
    max_length = 500
    if len(content) > max_length:
        summary = content[:max_length] + "..."
    else:
        summary = content

    return {
        "summary": summary,
        "original_length": len(content),
    }


async def _save_tool_execution_record(
    conversation_id: str,
    message_id: str,
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_output: Any,
    status: str,
    error_message: Optional[str] = None,
    call_id: Optional[str] = None,
    sequence_number: int = 0,
) -> None:
    """
    Save tool execution record to database.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        tool_name: Tool name
        tool_input: Tool input arguments
        tool_output: Tool output result
        status: Execution status
        error_message: Optional error message
        call_id: Optional call ID (will be generated if not provided)
        sequence_number: Sequence number within the message
    """
    import json

    from src.infrastructure.adapters.secondary.persistence.database import \
        async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import \
        ToolExecutionRecord

    # Convert tool_output to JSON string if it's a dict
    output_str = None
    if status == "success" and tool_output is not None:
        if isinstance(tool_output, dict):
            output_str = json.dumps(tool_output, ensure_ascii=False)
        else:
            output_str = str(tool_output)

    async with async_session_factory() as session:
        async with session.begin():
            record = ToolExecutionRecord(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                message_id=message_id,
                call_id=call_id or str(uuid.uuid4()),
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=output_str,
                status=status,
                error=error_message,
                sequence_number=sequence_number,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            session.add(record)
            await session.flush()


# ============================================================================
# New ReActAgent-based Activity (replaces hardcoded implementation)
# ============================================================================


@activity.defn
async def execute_react_agent_activity(
    input: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute Agent using the self-developed ReActAgent with Session Pool optimization.

    This Activity uses the complete ReActAgent implementation from
    src/infrastructure/agent/core/react_agent.py with Agent Session Pool
    for component caching and reuse.

    Performance Impact (with Agent Session Pool):
    - First request: ~300-800ms (builds cache)
    - Subsequent requests: <20ms (95%+ reduction)

    Cached Components:
    - Tool definitions (avoids _convert_tools() overhead)
    - SubAgentRouter (avoids keyword index building)
    - SystemPromptManager (shared singleton)
    - MCP tools (TTL-based cache, default 5 minutes)

    Benefits:
    - Full 30+ event types (thought, act, observe, cost_update, etc.)
    - Permission management (PermissionManager)
    - Doom loop detection (DoomLoopDetector)
    - Cost tracking (CostTracker)
    - Skill system (L2) and SubAgent routing (L3)
    - Unified tool interface (AgentTool)

    Args:
        input: Agent execution input containing:
            - conversation_id: Conversation ID
            - message_id: Message ID
            - user_message: User's message
            - project_id: Project ID
            - user_id: User ID
            - tenant_id: Tenant ID
            - agent_config: Agent configuration (model, api_key, base_url, etc.)
            - conversation_context: Conversation history
        state: Current execution state containing:
            - sequence_number: Current event sequence number

    Returns:
        Step result dictionary with type: 'complete', 'error', or 'continue'
    """
    import time as time_module

    from src.configuration.config import get_settings
    from src.infrastructure.adapters.secondary.event.redis_event_bus import \
        RedisEventBusAdapter
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_agent_graph_service, get_or_create_agent_session,
        get_or_create_llm_client, get_or_create_provider_config,
        get_or_create_skills, get_or_create_tools, get_redis_client)
    from src.infrastructure.agent.core.react_agent import ReActAgent
    from src.infrastructure.security.encryption_service import \
        get_encryption_service

    redis_client = None
    start_time = time_module.time()

    try:
        settings = get_settings()

        # Extract input parameters
        conversation_id = input.get("conversation_id", "")
        message_id = input.get("message_id", "")
        user_message = input.get("user_message", "")
        project_id = input.get("project_id", "")
        user_id = input.get("user_id", "")
        tenant_id = input.get("tenant_id", "")
        agent_config = input.get("agent_config", {})
        conversation_context = input.get("conversation_context", [])

        # Get current sequence number
        sequence_number = state.get("sequence_number", 0)

        # Sync sequence_number from DB to handle Temporal retry scenarios
        # When Activity is retried, state.sequence_number may be stale
        sequence_number = await _sync_sequence_number_from_db(conversation_id, sequence_number)

        # Get shared resources from Worker State
        graph_service = get_agent_graph_service()
        redis_client = await get_redis_client()
        event_bus = RedisEventBusAdapter(redis_client)

        # Get LLM provider configuration (cached)
        provider_config = await get_or_create_provider_config()

        # Pre-warm LLM client cache (provider lookup cached across requests)
        llm_client = await get_or_create_llm_client(provider_config)

        # Extract agent_mode from agent_config early (needed for tool loading)
        agent_mode = agent_config.get("agent_mode", "default")

        # Get or create cached tools (including MCP tools with TTL cache and skill_loader)
        # Pass agent_mode so skill_loader can filter skills appropriately
        tools = await get_or_create_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            graph_service=graph_service,
            redis_client=redis_client,
            llm=llm_client,
            agent_mode=agent_mode,
            mcp_tools_ttl_seconds=300,  # 5 minutes TTL for MCP tools
        )

        # Get or create cached skills
        skills = await get_or_create_skills(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # ====================================================================
        # Agent Session Pool: Get cached session context
        # This provides pre-computed tool_definitions, SubAgentRouter, etc.
        # ====================================================================
        from src.infrastructure.agent.core.processor import ProcessorConfig

        processor_config = ProcessorConfig(
            model="",  # Will be set properly below
            api_key="",
            base_url=None,
            temperature=agent_config.get("temperature", 0.7),
            max_tokens=agent_config.get("max_tokens", 4096),
            max_steps=agent_config.get("max_steps", 20),
        )

        session_ctx = await get_or_create_agent_session(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tools=tools,
            skills=skills,
            subagents=[],  # SubAgents loaded separately if needed
            processor_config=processor_config,
        )

        init_time_ms = (time_module.time() - start_time) * 1000
        logger.info(
            f"[ReActAgentActivity] Session pool initialization took {init_time_ms:.1f}ms "
            f"(use_count={session_ctx.use_count})"
        )

        # Construct full model name for LiteLLM (provider_type/model_name format)
        # Use agent_config model if provided, otherwise use provider_config.llm_model
        base_model = agent_config.get("model") or provider_config.llm_model
        # Get provider type as string (handle both enum and string values)
        provider_type_str = (
            provider_config.provider_type.value
            if hasattr(provider_config.provider_type, "value")
            else str(provider_config.provider_type)
        )
        # Ensure model has provider prefix for LiteLLM
        # Map provider types to LiteLLM-compatible prefixes
        if "/" not in base_model:
            # ZAI uses OpenAI-compatible API, so use openai/ prefix
            if provider_type_str == "zai":
                default_model = f"openai/{base_model}"
            elif provider_type_str == "qwen":
                default_model = f"dashscope/{base_model}"
            else:
                default_model = f"{provider_type_str}/{base_model}"
        else:
            default_model = base_model

        # Decrypt API key from provider config
        encryption_service = get_encryption_service()
        api_key = agent_config.get("api_key") or encryption_service.decrypt(
            provider_config.api_key_encrypted
        )
        base_url = agent_config.get("base_url") or provider_config.base_url

        # Set environment variables for LiteLLM based on provider type
        # LiteLLM requires specific env vars for each provider
        import os

        if provider_type_str == "zai":
            # ZAI uses OpenAI-compatible API, so we set OPENAI env vars
            os.environ["OPENAI_API_KEY"] = api_key
            if base_url:
                os.environ["OPENAI_API_BASE"] = base_url
            else:
                # Default ZAI base URL
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

        # Create ReActAgent instance with cached components from session pool
        # Note: We pass pre-converted tool_definitions to avoid _convert_tools() overhead
        agent = ReActAgent(
            model=default_model,
            tools=tools,  # Raw tools for SubAgent filtering
            api_key=api_key,
            base_url=base_url,
            temperature=agent_config.get("temperature", 0.7),
            max_tokens=agent_config.get("max_tokens", 4096),
            max_steps=agent_config.get("max_steps", 20),
            agent_mode=agent_mode,
            skills=skills,
            # Use cached components from session pool
            _cached_tool_definitions=session_ctx.tool_definitions,
            _cached_system_prompt_manager=session_ctx.system_prompt_manager,
            _cached_subagent_router=session_ctx.subagent_router,
        )

        # Stream channel for Redis events
        stream_channel = f"agent:stream:{conversation_id}"

        # Track final content and result
        assistant_message_id = str(uuid.uuid4())
        collected_artifacts: list[Dict[str, Any]] = []
        final_content = ""
        result_type = "complete"

        logger.info(
            f"[ReActAgentActivity] Starting execution for conversation {conversation_id}, "
            f"message {message_id}, user: {user_id}"
        )

        # Execute ReActAgent and stream events
        async for event in agent.stream(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_context=conversation_context,
        ):
            sequence_number += 1

            # Get event type and data
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # Inject message_id into event_data for frontend filtering
            # connect_chat_stream filters events by message_id
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

            # Track content for text_delta events - accumulate within current segment
            if event_type == "text_delta":
                final_content += event_data_with_message_id.get("delta", "")
            elif event_type == "text_end":
                # When a text segment ends, save it as an independent assistant_message
                # This ensures multiple LLM responses in a ReAct loop are rendered separately
                segment_content = event_data_with_message_id.get("full_text", final_content)
                if segment_content and segment_content.strip():
                    # Increment sequence for the assistant_message event
                    sequence_number += 1
                    segment_message_id = str(uuid.uuid4())
                    await _save_assistant_message_event(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        content=segment_content,
                        assistant_message_id=segment_message_id,
                        artifacts=None,  # Artifacts attached at complete event
                        sequence_number=sequence_number,
                    )
                    logger.info(
                        f"[ReActAgentActivity] Saved intermediate assistant_message {segment_message_id} "
                        f"for conversation {conversation_id}"
                    )
                # Reset content accumulator for next segment
                final_content = ""
            elif event_type == "complete":
                # Complete event may have final content if there was no text_end
                final_content = event_data_with_message_id.get("content", final_content)

            # Publish to Redis (real-time streaming)
            if should_publish:
                await event_bus.publish(
                    stream_channel,
                    {
                        "type": event_type,
                        "data": event_data_with_message_id,
                        "seq": sequence_number,
                    },
                )

            # Save to DB (persistence)
            await _save_event_to_db(
                conversation_id,
                message_id,
                event_type,
                event_data_with_message_id,
                sequence_number,
            )

            # Check for error or completion
            if event_type == "error":
                result_type = "error"
            elif event_type == "complete":
                result_type = "complete"

        # Save final assistant_message event only if there's remaining content
        # (content not already saved in text_end handler)
        if result_type == "complete" and final_content and final_content.strip():
            sequence_number += 1
            assistant_message_id = await _save_assistant_message_event(
                conversation_id=conversation_id,
                message_id=message_id,
                content=final_content,
                assistant_message_id=assistant_message_id,
                artifacts=collected_artifacts or None,
                sequence_number=sequence_number,
            )

            total_time_ms = (time_module.time() - start_time) * 1000
            logger.info(
                f"[ReActAgentActivity] Completed for conversation {conversation_id}, "
                f"final assistant message {assistant_message_id}, total time: {total_time_ms:.1f}ms"
            )
        else:
            total_time_ms = (time_module.time() - start_time) * 1000
            logger.info(
                f"[ReActAgentActivity] Completed for conversation {conversation_id}, "
                f"no final content (already saved via text_end), total time: {total_time_ms:.1f}ms"
            )

        return {
            "type": result_type,
            "content": final_content,
            "sequence_number": sequence_number,
        }

    except Exception as e:
        logger.error(f"[ReActAgentActivity] Error: {e}", exc_info=True)

        # Publish error event
        if redis_client:
            try:
                stream_channel = f"agent:stream:{input.get('conversation_id', '')}"
                event_bus = RedisEventBusAdapter(redis_client)
                await event_bus.publish(
                    stream_channel,
                    {
                        "type": "error",
                        "data": {
                            "message": str(e),
                            "code": "AGENT_EXECUTION_ERROR",
                            "message_id": input.get("message_id", ""),
                        },
                        "seq": state.get("sequence_number", 0) + 1,
                    },
                )
            except Exception as publish_error:
                logger.error(f"[ReActAgentActivity] Failed to publish error event: {publish_error}")

        return {
            "type": "error",
            "error": str(e),
            "sequence_number": state.get("sequence_number", 0),
        }
