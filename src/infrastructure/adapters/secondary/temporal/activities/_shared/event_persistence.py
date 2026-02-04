"""Event persistence utilities for Temporal Activities.

This module provides common event storage and persistence functionality
used across Agent activities.

Includes:
- WAL (Write-Ahead Log) pattern for event persistence
- TextDeltaSampler for efficient text_delta handling
- Atomic sequence number generation
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

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


class TextDeltaSampler:
    """
    Sample text_delta events for persistence.

    Strategy:
    - Save every Nth delta (default: every 10th)
    - Always save first delta
    - Merge adjacent deltas for efficiency
    - Finalize on text_end to capture complete text
    """

    SAMPLE_INTERVAL = 10  # Save every 10th delta
    MAX_BUFFER_SIZE = 100  # Max deltas to buffer before force-save

    def __init__(self):
        self._buffer: List[str] = []
        self._count = 0
        self._last_saved_content = ""

    def add_delta(self, delta: str) -> Optional[str]:
        """
        Add a delta and return merged content if should save.

        Args:
            delta: The delta text to add

        Returns:
            Merged content to save, or None if not saving yet
        """
        self._buffer.append(delta)
        self._count += 1

        # Save conditions:
        # 1. First delta (count == 1)
        # 2. Every Nth delta
        # 3. Buffer full
        should_save = (
            self._count == 1
            or self._count % self.SAMPLE_INTERVAL == 0
            or len(self._buffer) >= self.MAX_BUFFER_SIZE
        )

        if should_save:
            return self._flush()

        return None

    def _flush(self) -> str:
        """Flush buffer and return merged content."""
        merged = "".join(self._buffer)
        self._buffer = []

        # Return full accumulated content since last save
        result = self._last_saved_content + merged
        self._last_saved_content = result

        return result

    def finalize(self) -> str:
        """Get final content (call on text_end)."""
        if self._buffer:
            return self._flush()
        return self._last_saved_content

    @property
    def total_count(self) -> int:
        """Get total number of deltas processed."""
        return self._count


async def save_event_to_db(
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

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event_type: Type of event
        event_data: Event payload data
        sequence_number: Unique sequence number for ordering
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


async def save_assistant_message_event(
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

    Args:
        conversation_id: Conversation ID
        message_id: Original user message ID
        content: Assistant response content
        assistant_message_id: Optional ID for the assistant message
        artifacts: Optional list of artifact references
        sequence_number: Event sequence number

    Returns:
        The ID of the assistant message (for reference in other events).
    """
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

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


async def save_tool_execution_record(
    conversation_id: str,
    message_id: str,
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_output: Any,
    status: str = "success",
    error_message: Optional[str] = None,
    execution_time_ms: Optional[float] = None,
) -> Optional[str]:
    """Save tool execution record to database.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        tool_name: Name of the executed tool
        tool_input: Tool input parameters
        tool_output: Tool output result
        status: Execution status ('success' or 'error')
        error_message: Error message if status is 'error'
        execution_time_ms: Execution time in milliseconds

    Returns:
        Created record ID or None on failure
    """
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import ToolExecutionRecord

    try:
        # Serialize output safely
        import json

        if tool_output is not None:
            if isinstance(tool_output, str):
                output_str = tool_output
            else:
                try:
                    output_str = json.dumps(tool_output)
                except (TypeError, ValueError):
                    output_str = str(tool_output)
        else:
            output_str = None

        async with async_session_factory() as session:
            async with session.begin():
                record = ToolExecutionRecord(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=output_str,
                    status=status,
                    error_message=error_message,
                    execution_time_ms=execution_time_ms,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(record)
                await session.flush()
                return record.id
    except Exception as e:
        logger.error(f"Failed to save tool execution record: {e}")
        return None


async def sync_sequence_number_from_db(
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

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

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


async def persist_and_publish_event(
    conversation_id: str,
    message_id: str,
    event: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> int:
    """
    Write-Ahead Log pattern: DB first, then Redis.

    1. Get sequence number atomically
    2. Write to DB (source of truth)
    3. Publish to Redis (notification layer)

    If Redis fails, event is still in DB and can be recovered.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event: Event to persist
        correlation_id: Optional request correlation ID

    Returns:
        The sequence number assigned to this event
    """
    import redis.asyncio as aioredis
    from sqlalchemy.dialects.postgresql import insert

    from src.configuration.config import get_settings
    from src.infrastructure.adapters.secondary.messaging.redis_sequence_service import (
        RedisSequenceService,
    )
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import (
        AgentExecutionEvent as AgentExecutionEventModel,
    )

    settings = get_settings()
    redis_client = None

    try:
        # 1. Get atomic sequence
        redis_client = aioredis.from_url(settings.redis_url)
        sequence_service = RedisSequenceService(redis_client)
        seq = await sequence_service.get_next_sequence(conversation_id)

        event_type = event.get("type", "unknown")
        event_data = event.get("data", {})

        # 2. Write to DB first (synchronous, must succeed)
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    insert(AgentExecutionEventModel)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type=event_type,
                        event_data=event_data,
                        sequence_number=seq,
                        correlation_id=correlation_id,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
                )
                await session.execute(stmt)

        # 3. Publish to Redis (async, can fail)
        try:
            stream_key = f"agent:events:{conversation_id}"
            redis_event = {
                "type": event_type,
                "seq": str(seq),
                "data": json.dumps(event_data, default=str),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conversation_id,
                "message_id": message_id,
            }
            if correlation_id:
                redis_event["correlation_id"] = correlation_id

            await redis_client.xadd(stream_key, redis_event, maxlen=1000)

        except Exception as e:
            # Log but don't fail - Redis is notification layer only
            logger.warning(f"Failed to publish event to Redis: {e}")

        return seq

    finally:
        if redis_client:
            await redis_client.close()


async def save_sampled_text_delta(
    conversation_id: str,
    message_id: str,
    accumulated_content: str,
    sequence_number: int,
    correlation_id: Optional[str] = None,
) -> None:
    """
    Save sampled text delta to TextDeltaBuffer table.

    This provides short-term recovery for text_delta events without
    storing every individual delta.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        accumulated_content: Accumulated text content so far
        sequence_number: Current sequence number
        correlation_id: Optional request correlation ID
    """
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import TextDeltaBuffer

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    try:
        async with async_session_factory() as session:
            async with session.begin():
                buffer = TextDeltaBuffer(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type="text_delta_sample",
                    delta_content=accumulated_content,
                    event_data={"accumulated": True, "correlation_id": correlation_id},
                    sequence_number=sequence_number,
                    expires_at=expires_at,
                )
                session.add(buffer)

    except Exception as e:
        logger.warning(f"Failed to save sampled text delta: {e}")


async def publish_event_to_redis(
    conversation_id: str,
    message_id: str,
    event: Dict[str, Any],
    sequence_number: int,
    correlation_id: Optional[str] = None,
) -> None:
    """
    Publish an event to Redis Stream only (no DB write).

    Used for streaming events that don't need DB persistence.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event: Event to publish
        sequence_number: Sequence number
        correlation_id: Optional correlation ID
    """
    import redis.asyncio as aioredis

    from src.configuration.config import get_settings

    settings = get_settings()
    redis_client = None

    try:
        redis_client = aioredis.from_url(settings.redis_url)
        stream_key = f"agent:events:{conversation_id}"

        event_type = event.get("type", "unknown")
        event_data = event.get("data", {})

        redis_event = {
            "type": event_type,
            "seq": str(sequence_number),
            "data": json.dumps(event_data, default=str),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
        if correlation_id:
            redis_event["correlation_id"] = correlation_id

        await redis_client.xadd(stream_key, redis_event, maxlen=1000)

    except Exception as e:
        logger.warning(f"Failed to publish event to Redis: {e}")

    finally:
        if redis_client:
            await redis_client.close()
