"""
Temporal Activities for Agent Execution - Core Activities.

This module provides core activity implementations for the agent execution workflow,
including event persistence, checkpoint management, and running state tracking.

Note: Legacy activities (execute_react_step_activity, execute_react_agent_activity)
have been removed. Use ProjectAgentWorkflow with project_agent activities instead.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from temporalio import activity

from src.infrastructure.adapters.secondary.temporal.activities._shared import (
    save_event_to_db,
)
from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
    get_redis_client,
)

logger = logging.getLogger(__name__)


@activity.defn
async def save_event_activity(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
) -> None:
    """Activity for saving SSE events to database.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event_type: Type of event
        event_data: Event payload data
        sequence_number: Unique sequence number for ordering
    """
    await save_event_to_db(conversation_id, message_id, event_type, event_data, sequence_number)


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
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import ExecutionCheckpoint

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
    redis_client = await get_redis_client()

    key = f"agent:running:{conversation_id}"
    await redis_client.setex(
        key,
        ttl_seconds,
        message_id,
    )
    logger.info(f"Set agent running state: {key} -> {message_id} (TTL={ttl_seconds}s)")


@activity.defn
async def clear_agent_running(conversation_id: str) -> None:
    """
    Activity for clearing the agent running state in Redis.

    Args:
        conversation_id: Conversation ID
    """
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
    redis_client = await get_redis_client()

    key = f"agent:running:{conversation_id}"
    await redis_client.expire(key, ttl_seconds)
    logger.debug(f"Refreshed agent running TTL: {key} (TTL={ttl_seconds}s)")
