"""
HITL (Human-in-the-Loop) Handlers for WebSocket

Handles clarification_respond, decision_respond, and env_var_respond message types.
Uses Temporal Signals to communicate with the running workflow.
"""

import asyncio
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


async def _send_hitl_signal_to_workflow(
    tenant_id: str,
    project_id: str,
    request_id: str,
    hitl_type: str,
    response_data: dict,
    user_id: str,
) -> bool:
    """Send HITL response signal to the Temporal workflow."""
    try:
        from temporalio.client import Client

        from src.configuration.temporal_config import get_temporal_settings
        from src.domain.model.agent.hitl_types import HITL_RESPONSE_SIGNAL
        from src.infrastructure.adapters.secondary.temporal.workflows.project_agent_workflow import (
            get_project_agent_workflow_id,
        )

        temporal_settings = get_temporal_settings()

        # Get Temporal client
        client = await Client.connect(
            temporal_settings.temporal_host,
            namespace=temporal_settings.temporal_namespace,
        )

        # Get workflow ID
        workflow_id = get_project_agent_workflow_id(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # Build signal payload
        signal_payload = {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "response_data": response_data,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Get workflow handle and send signal
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(HITL_RESPONSE_SIGNAL, signal_payload)

        logger.info(f"[WS HITL] Sent Temporal Signal to workflow {workflow_id}: {request_id}")
        return True

    except Exception as e:
        logger.warning(f"[WS HITL] Failed to send Temporal Signal: {e}")
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
    
    Uses Temporal Signals to communicate with the running workflow.
    """
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    # Use a fresh session to ensure we see the latest data from other processes
    # (the HITL request was created by the agent worker in a different process)
    async with async_session_factory() as session:
        repo = SqlHITLRequestRepository(session)
        hitl_request = await repo.get_by_id(request_id)

        if not hitl_request:
            await context.send_error(f"HITL request {request_id} not found")
            return

        # Check if already answered
        from src.domain.model.agent.hitl_request import HITLRequestStatus

        if hitl_request.status != HITLRequestStatus.PENDING:
            await context.send_error(
                f"HITL request {request_id} is no longer pending (status: {hitl_request.status.value})"
            )
            return

        # Send Temporal Signal
        signal_sent = await _send_hitl_signal_to_workflow(
            tenant_id=hitl_request.tenant_id,
            project_id=hitl_request.project_id,
            request_id=request_id,
            hitl_type=hitl_type,
            response_data=response_data,
            user_id=context.user_id,
        )

        if signal_sent:
            # Update database record
            response_str = (
                response_data.get("answer")
                or response_data.get("decision")
                or str(response_data.get("values", {}))
            )
            await repo.update_response(request_id, response_str)
            await repo.mark_completed(request_id)
            await session.commit()

            logger.info(
                f"[WS HITL] User {context.user_id} responded to {hitl_type} {request_id} "
                "via Temporal Signal"
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
        else:
            await context.send_error(
                f"Failed to send HITL response for {request_id}. "
                "The agent workflow may have terminated."
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
