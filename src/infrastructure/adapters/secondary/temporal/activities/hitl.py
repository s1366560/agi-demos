"""
HITL Temporal Activities - Activities for Human-in-the-Loop operations.

These activities handle:
1. Creating HITL requests and persisting to database
2. Emitting SSE events to frontend
3. Recording HITL history for audit
4. Sending Temporal Signals for user responses

Architecture:
    Workflow → create_hitl_request_activity → SSE Event → Frontend
    Frontend → API → send_hitl_signal_activity → Workflow Signal
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from temporalio import activity

if TYPE_CHECKING:
    from src.domain.model.agent.hitl_types import HITLType

logger = logging.getLogger(__name__)


# =============================================================================
# Activity: Create HITL Request
# =============================================================================


@activity.defn(name="create_hitl_request")
async def create_hitl_request_activity(
    request_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create an HITL request and emit SSE event.

    This activity:
    1. Generates a unique request ID
    2. Persists the request to database (for recovery)
    3. Emits SSE event to frontend

    Args:
        request_data: Dictionary containing:
            - hitl_type: "clarification" | "decision" | "env_var" | "permission"
            - conversation_id: str
            - tenant_id: str
            - project_id: str
            - message_id: Optional[str]
            - timeout_seconds: float
            - type_specific_data: dict (question, options, etc.)

    Returns:
        Dictionary containing:
            - request_id: Generated request ID
            - status: "created"
            - created_at: ISO timestamp
    """
    from src.domain.model.agent.hitl_types import HITLType

    hitl_type = HITLType(request_data["hitl_type"])
    conversation_id = request_data["conversation_id"]
    tenant_id = request_data.get("tenant_id", "")
    project_id = request_data.get("project_id", "")
    message_id = request_data.get("message_id")
    timeout_seconds = request_data.get("timeout_seconds", 300.0)
    type_data = request_data.get("type_specific_data", {})

    # Generate request ID
    prefix = hitl_type.value[:4]  # "clar", "deci", "env_", "perm"
    request_id = f"{prefix}_{uuid.uuid4().hex[:8]}"

    created_at = datetime.utcnow()

    logger.info(
        f"[HITL Activity] Creating {hitl_type.value} request: {request_id} "
        f"for conversation {conversation_id}"
    )

    # Persist to database
    await _persist_hitl_request(
        request_id=request_id,
        hitl_type=hitl_type,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        project_id=project_id,
        message_id=message_id,
        timeout_seconds=timeout_seconds,
        type_data=type_data,
        created_at=created_at,
    )

    # Emit SSE event
    await _emit_hitl_sse_event(
        request_id=request_id,
        hitl_type=hitl_type,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        project_id=project_id,
        type_data=type_data,
        timeout_seconds=timeout_seconds,
    )

    # Heartbeat for Temporal
    activity.heartbeat({"request_id": request_id, "status": "created"})

    return {
        "request_id": request_id,
        "status": "created",
        "created_at": created_at.isoformat(),
    }


# =============================================================================
# Activity: Emit HITL SSE Event
# =============================================================================


@activity.defn(name="emit_hitl_sse_event")
async def emit_hitl_sse_event_activity(
    event_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Emit an HITL SSE event to the frontend.

    Used for emitting answered/cancelled events after the initial asked event.

    Args:
        event_data: Dictionary containing:
            - event_type: str (e.g., "clarification_answered")
            - conversation_id: str
            - request_id: str
            - payload: dict

    Returns:
        Dictionary with status
    """
    event_type = event_data["event_type"]
    conversation_id = event_data["conversation_id"]
    request_id = event_data["request_id"]
    payload = event_data.get("payload", {})

    logger.info(
        f"[HITL Activity] Emitting SSE event: {event_type} for request {request_id}"
    )

    await _publish_to_unified_event_bus(
        event_type=event_type,
        conversation_id=conversation_id,
        data={
            "request_id": request_id,
            **payload,
        },
    )

    return {"status": "emitted", "event_type": event_type}


# =============================================================================
# Activity: Record HITL History
# =============================================================================


@activity.defn(name="record_hitl_history")
async def record_hitl_history_activity(
    history_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Record HITL interaction in history for audit trail.

    Args:
        history_data: Dictionary containing:
            - request_id: str
            - hitl_type: str
            - conversation_id: str
            - tenant_id: str
            - project_id: str
            - question: str
            - response: str or dict
            - response_metadata: dict
            - created_at: ISO timestamp
            - answered_at: ISO timestamp

    Returns:
        Dictionary with status
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    request_id = history_data["request_id"]

    logger.info(f"[HITL Activity] Recording history for request {request_id}")

    try:
        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)

            # Update the request with response
            response = history_data.get("response")
            if isinstance(response, dict):
                import json
                response = json.dumps(response)

            await repo.update_response(
                request_id=request_id,
                response=response,
                response_metadata=history_data.get("response_metadata"),
            )
            await repo.mark_completed(request_id)
            await session.commit()

        return {"status": "recorded", "request_id": request_id}

    except Exception as e:
        logger.error(f"[HITL Activity] Failed to record history: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# Activity: Get Pending HITL Requests
# =============================================================================


@activity.defn(name="get_pending_hitl_requests")
async def get_pending_hitl_requests_activity(
    query_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Get pending HITL requests for a conversation.

    Args:
        query_data: Dictionary containing:
            - conversation_id: str
            - tenant_id: str
            - project_id: str (optional)

    Returns:
        Dictionary containing:
            - requests: List of pending request dicts
            - total: int
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    conversation_id = query_data["conversation_id"]
    tenant_id = query_data["tenant_id"]
    project_id = query_data.get("project_id")

    logger.info(f"[HITL Activity] Getting pending requests for conversation {conversation_id}")

    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)

        requests = await repo.get_pending_by_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            exclude_expired=True,
        )

        request_dicts = [req.to_dict() for req in requests]

    return {
        "requests": request_dicts,
        "total": len(request_dicts),
    }


# =============================================================================
# Activity: Cancel HITL Request
# =============================================================================


@activity.defn(name="cancel_hitl_request")
async def cancel_hitl_request_activity(
    cancel_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Cancel a pending HITL request.

    Args:
        cancel_data: Dictionary containing:
            - request_id: str
            - reason: Optional[str]
            - conversation_id: str

    Returns:
        Dictionary with status
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    request_id = cancel_data["request_id"]
    reason = cancel_data.get("reason")
    conversation_id = cancel_data["conversation_id"]

    logger.info(f"[HITL Activity] Cancelling request {request_id}")

    try:
        async with async_session_factory() as session:
            repo = SqlHITLRequestRepository(session)
            result = await repo.mark_cancelled(request_id, reason)
            await session.commit()

            if result:
                # Emit cancellation SSE event
                await _publish_to_unified_event_bus(
                    event_type="hitl_cancelled",
                    conversation_id=conversation_id,
                    data={
                        "request_id": request_id,
                        "reason": reason,
                    },
                )

        return {"status": "cancelled" if result else "not_found", "request_id": request_id}

    except Exception as e:
        logger.error(f"[HITL Activity] Failed to cancel request: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# Helper Functions
# =============================================================================


async def _persist_hitl_request(
    request_id: str,
    hitl_type: "HITLType",
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    message_id: Optional[str],
    timeout_seconds: float,
    type_data: Dict[str, Any],
    created_at: datetime,
) -> None:
    """Persist HITL request to database."""
    from datetime import timedelta

    from src.domain.model.agent.hitl_request import (
        HITLRequest as HITLRequestEntity,
    )
    from src.domain.model.agent.hitl_request import (
        HITLRequestType,
    )
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    # Map HITLType to HITLRequestType
    type_mapping = {
        "clarification": HITLRequestType.CLARIFICATION,
        "decision": HITLRequestType.DECISION,
        "env_var": HITLRequestType.ENV_VAR,
    }
    request_type = type_mapping.get(hitl_type.value, HITLRequestType.CLARIFICATION)

    # Extract question from type_data
    question = type_data.get("question", "")
    if not question and hitl_type.value == "env_var":
        question = type_data.get("message", "Please provide environment variables")

    entity = HITLRequestEntity(
        id=request_id,
        request_type=request_type,
        conversation_id=conversation_id,
        message_id=message_id,
        tenant_id=tenant_id,
        project_id=project_id,
        question=question,
        options=type_data.get("options", []),
        context=type_data.get("context", {}),
        metadata={
            "hitl_type": hitl_type.value,
            **{k: v for k, v in type_data.items() if k not in ("question", "options", "context")},
        },
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=timeout_seconds),
    )

    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        await repo.create(entity)
        await session.commit()

    logger.debug(f"[HITL Activity] Persisted request {request_id} to database")


async def _emit_hitl_sse_event(
    request_id: str,
    hitl_type: "HITLType",
    conversation_id: str,
    tenant_id: str,
    project_id: str,
    type_data: Dict[str, Any],
    timeout_seconds: float,
) -> None:
    """Emit HITL asked event via SSE."""
    # Map HITL type to event type
    event_type_mapping = {
        "clarification": "clarification_asked",
        "decision": "decision_asked",
        "env_var": "env_var_requested",
        "permission": "permission_asked",
    }
    event_type = event_type_mapping.get(hitl_type.value, "clarification_asked")

    # Build event data
    event_data = {
        "request_id": request_id,
        "timeout_seconds": timeout_seconds,
        **type_data,
    }

    await _publish_to_unified_event_bus(
        event_type=event_type,
        conversation_id=conversation_id,
        data=event_data,
    )

    logger.debug(f"[HITL Activity] Emitted SSE event {event_type} for {request_id}")


async def _publish_to_unified_event_bus(
    event_type: str,
    conversation_id: str,
    data: Dict[str, Any],
) -> None:
    """Publish event to the Unified Event Bus for SSE delivery."""
    try:
        from src.domain.events.envelope import EventEnvelope
        from src.domain.ports.services.unified_event_bus_port import RoutingKey
        from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
            RedisUnifiedEventBusAdapter,
        )
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            get_redis_client,
        )

        redis_client = await get_redis_client()
        if redis_client:
            event_bus = RedisUnifiedEventBusAdapter(redis_client)

            # Create event envelope
            envelope = EventEnvelope(
                event_type=event_type,
                payload=data,
                metadata={"conversation_id": conversation_id},
            )

            # Create routing key for conversation (namespace.entity_id)
            routing_key = RoutingKey(
                namespace="agent",
                entity_id=conversation_id,
            )

            await event_bus.publish(event=envelope, routing_key=routing_key)
            logger.info(f"[HITL Activity] Published SSE event: {event_type} for {conversation_id}")
        else:
            logger.warning("[HITL Activity] Redis client not available for SSE event")

    except Exception as e:
        logger.error(f"[HITL Activity] Failed to publish SSE event: {e}")


# =============================================================================
# Activity Registration
# =============================================================================


def get_hitl_activities() -> List:
    """Get all HITL activities for worker registration."""
    return [
        create_hitl_request_activity,
        emit_hitl_sse_event_activity,
        record_hitl_history_activity,
        get_pending_hitl_requests_activity,
        cancel_hitl_request_activity,
    ]
