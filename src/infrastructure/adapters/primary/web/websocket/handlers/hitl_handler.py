"""
HITL (Human-in-the-Loop) Handlers for WebSocket

Handles clarification_respond, decision_respond, and env_var_respond message types.
Uses Redis Streams to communicate with the running Ray Actor.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


async def _publish_hitl_response_to_redis(
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    request_id: str,
    hitl_type: str,
    response_data: dict,
    user_id: str,
    agent_mode: str,
) -> bool:
    """Publish HITL response to Redis Stream for Ray Actor delivery."""
    try:
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            get_redis_client,
        )

        settings = get_settings()
        if not getattr(settings, "hitl_realtime_enabled", True):
            logger.debug("[WS HITL] Realtime disabled, skipping Redis publish")
            return False

        redis = await get_redis_client()

        stream_key = f"hitl:response:{tenant_id}:{project_id}"
        message_data = {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "response_data": response_data,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "agent_mode": agent_mode,
            "timestamp": datetime.utcnow().isoformat(),
        }

        await redis.xadd(stream_key, {"data": json.dumps(message_data)}, maxlen=1000)

        logger.info(f"[WS HITL] Published response to Redis: {request_id}")
        return True

    except Exception as e:
        logger.warning(f"[WS HITL] Failed to publish to Redis: {e}")
        return False


async def _handle_hitl_response(
    context: MessageContext,
    request_id: str,
    hitl_type: str,
    response_data: dict,
    ack_type: str,
) -> None:
    """
    Common handler for all HITL response types.
    
    Uses Redis Streams to communicate with the running Ray Actor.
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )
    from src.domain.model.agent.hitl_request import HITLRequestStatus
    from sqlalchemy import text

    hitl_request = None
    session = None
    
    # ALWAYS use a fresh session for HITL queries to avoid transaction isolation issues
    # WebSocket connections hold long-lived sessions that may not see other transactions
    try:
        async with async_session_factory() as fresh_session:
            # First, execute a raw SQL to ensure we get fresh data
            result = await fresh_session.execute(
                text("SELECT id, request_type, status, tenant_id, project_id, conversation_id, request_metadata FROM hitl_requests WHERE id = :id"),
                {"id": request_id}
            )
            row = result.fetchone()
            
            if row:
                # Convert row to domain object manually
                from src.domain.model.agent.hitl_request import HITLRequest, HITLRequestType, HITLRequestStatus
                from datetime import datetime
                
                hitl_request = HITLRequest(
                    id=row.id,
                    request_type=HITLRequestType(row.request_type.lower()),
                    conversation_id=row.conversation_id,
                    message_id=None,
                    tenant_id=row.tenant_id,
                    project_id=row.project_id,
                    question="",
                    options=[],
                    context={},
                    metadata=row.request_metadata or {},
                    created_at=datetime.utcnow(),
                    status=HITLRequestStatus(row.status.lower()) if row.status else HITLRequestStatus.PENDING,
                )
                session = fresh_session
                logger.debug(f"[WS HITL] Found HITL request {request_id} using raw SQL query")
            else:
                logger.warning(f"[WS HITL] HITL request {request_id} not found via raw SQL")
    except Exception as e:
        logger.error(f"[WS HITL] Failed to query with raw SQL: {e}", exc_info=True)

    if not hitl_request:
        logger.error(f"[WS HITL] HITL request {request_id} not found in database")
        await context.send_error(f"HITL request {request_id} not found")
        return

    # Check if already answered
    if hitl_request.status != HITLRequestStatus.PENDING:
        await context.send_error(
            f"HITL request {request_id} is no longer pending (status: {hitl_request.status.value})"
        )
        return

    # Publish to Redis Stream
    agent_mode = (hitl_request.metadata or {}).get("agent_mode", "default")
    redis_sent = await _publish_hitl_response_to_redis(
        tenant_id=hitl_request.tenant_id,
        project_id=hitl_request.project_id,
        conversation_id=hitl_request.conversation_id,
        request_id=request_id,
        hitl_type=hitl_type,
        response_data=response_data,
        user_id=context.user_id,
        agent_mode=agent_mode,
    )

    if redis_sent:
        # Update database record using raw SQL to avoid ORM session issues
        try:
            response_str = (
                response_data.get("answer")
                or response_data.get("decision")
                or str(response_data.get("values", {}))
            )
            
            await session.execute(
                text("UPDATE hitl_requests SET status = 'completed', response = :response WHERE id = :id"),
                {"id": request_id, "response": response_str}
            )
            await session.commit()
                
            logger.info(
                f"[WS HITL] User {context.user_id} responded to {hitl_type} {request_id} "
                "via Redis Stream"
            )

            await context.send_json(
                {
                    "type": ack_type,
                    "request_id": request_id,
                    "success": True,
                }
            )

            # Start streaming agent events after HITL response
            await _start_hitl_stream_bridge(
                context=context,
                request_id=request_id,
            )
        except Exception as e:
            logger.error(f"[WS HITL] Failed to update HITL request: {e}", exc_info=True)
            await context.send_error(f"Failed to update HITL request: {str(e)}")
    else:
        await context.send_error(
            f"Failed to send HITL response for {request_id}."
        )


class ClarificationRespondHandler(WebSocketMessageHandler):
    """Handle clarification response via WebSocket using Temporal Signal."""

    @property
    def message_type(self) -> str:
        return "clarification_respond"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Handle clarification response."""
        request_id = message.get("request_id")
        answer = message.get("answer")

        if not request_id or answer is None:
            await context.send_error("Missing required fields: request_id, answer")
            return

        try:
            await _handle_hitl_response(
                context=context,
                request_id=request_id,
                hitl_type="clarification",
                response_data={"answer": answer},
                ack_type="clarification_response_ack",
            )
        except Exception as e:
            logger.error(f"[WS HITL] Error handling clarification response: {e}", exc_info=True)
            await context.send_error(f"Failed to process clarification response: {str(e)}")


class DecisionRespondHandler(WebSocketMessageHandler):
    """Handle decision response via WebSocket using Temporal Signal."""

    @property
    def message_type(self) -> str:
        return "decision_respond"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Handle decision response."""
        request_id = message.get("request_id")
        decision = message.get("decision")

        if not request_id or decision is None:
            await context.send_error("Missing required fields: request_id, decision")
            return

        try:
            await _handle_hitl_response(
                context=context,
                request_id=request_id,
                hitl_type="decision",
                response_data={"decision": decision},
                ack_type="decision_response_ack",
            )
        except Exception as e:
            logger.error(f"[WS HITL] Error handling decision response: {e}", exc_info=True)
            await context.send_error(f"Failed to process decision response: {str(e)}")


class EnvVarRespondHandler(WebSocketMessageHandler):
    """Handle environment variable response via WebSocket using Temporal Signal."""

    @property
    def message_type(self) -> str:
        return "env_var_respond"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Handle environment variable response."""
        request_id = message.get("request_id")
        values = message.get("values")

        if not request_id or not isinstance(values, dict):
            await context.send_error("Missing required fields: request_id, values (object)")
            return

        try:
            await _handle_hitl_response(
                context=context,
                request_id=request_id,
                hitl_type="env_var",
                response_data={"values": values},
                ack_type="env_var_response_ack",
            )
        except Exception as e:
            logger.error(f"[WS HITL] Error handling env var response: {e}", exc_info=True)
            await context.send_error(f"Failed to process env var response: {str(e)}")


# =============================================================================
# Stream Bridge Helper
# =============================================================================


async def _start_hitl_stream_bridge(
    context: MessageContext,
    request_id: str,
) -> None:
    """
    Start streaming agent events after HITL response.

    Handles page refresh scenarios:
    1. Queries the HITL request from database to get conversation_id
    2. Checks if there's already an active bridge task for this conversation
    3. Only starts a new bridge if needed (page refresh scenario)
    """
    try:
        from src.configuration.factories import create_llm_client
        from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
            SqlHITLRequestRepository,
        )

        manager = context.connection_manager

        # Get HITL request from database
        hitl_repo = SqlHITLRequestRepository(context.db)
        hitl_request = await hitl_repo.get_by_id(request_id)

        if not hitl_request:
            logger.warning(f"[WS HITL] Request {request_id} not found in database")
            return

        conversation_id = hitl_request.conversation_id

        if not conversation_id:
            logger.warning(f"[WS HITL] Request {request_id} missing conversation_id")
            return

        # Check if there's already an active bridge task for this conversation
        existing_tasks = manager.bridge_tasks.get(context.session_id, {})
        existing_task = existing_tasks.get(conversation_id)
        if existing_task and not existing_task.done():
            logger.info(
                f"[WS HITL] Bridge task already running for conversation {conversation_id}, "
                f"skipping (normal HITL flow)"
            )
            return

        # No existing bridge - this is likely a page refresh scenario
        logger.info(
            f"[WS HITL] Starting stream bridge for request {request_id}, "
            f"conversation={conversation_id} (page refresh recovery)"
        )

        # Auto-subscribe session to conversation
        await manager.subscribe(context.session_id, conversation_id)

        # Create agent service
        container = context.get_scoped_container()
        llm = create_llm_client(context.tenant_id)
        agent_service = container.agent_service(llm)

        # Import here to avoid circular imports
        from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
            stream_hitl_response_to_websocket,
        )

        # Start streaming in background task
        task = asyncio.create_task(
            stream_hitl_response_to_websocket(
                agent_service=agent_service,
                session_id=context.session_id,
                conversation_id=conversation_id,
                message_id=None,  # Read all new events
            )
        )
        manager.add_bridge_task(context.session_id, conversation_id, task)

    except Exception as e:
        logger.error(f"[WS HITL] Failed to start stream bridge: {e}", exc_info=True)
