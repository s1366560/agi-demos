"""
HITL (Human-in-the-Loop) Handlers for WebSocket

Handles clarification_respond, decision_respond, and env_var_respond message types.
"""

import asyncio
import logging
from typing import Any, Dict

from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext

logger = logging.getLogger(__name__)


class ClarificationRespondHandler(WebSocketMessageHandler):
    """Handle clarification response via WebSocket."""

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
            from src.infrastructure.agent.tools.clarification import get_clarification_manager

            clarification_manager = get_clarification_manager()
            result = await clarification_manager.respond(request_id, answer)

            if result:
                target_request_id = result if isinstance(result, str) else request_id
                logger.info(
                    f"[WS HITL] User {context.user_id} responded to clarification {request_id}"
                    + (f" (target: {target_request_id})" if target_request_id != request_id else "")
                )
                await context.send_json(
                    {
                        "type": "clarification_response_ack",
                        "request_id": request_id,
                        "target_request_id": target_request_id,
                        "success": True,
                    }
                )

                # Start streaming agent events after HITL response
                await _start_hitl_stream_bridge(
                    context=context,
                    request_id=target_request_id,
                )
            else:
                await context.send_error(
                    f"Clarification request {request_id} not found or already answered"
                )

        except Exception as e:
            logger.error(f"[WS HITL] Error handling clarification response: {e}", exc_info=True)
            await context.send_error(f"Failed to process clarification response: {str(e)}")


class DecisionRespondHandler(WebSocketMessageHandler):
    """Handle decision response via WebSocket."""

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
            from src.infrastructure.agent.tools.decision import get_decision_manager

            decision_manager = get_decision_manager()
            result = await decision_manager.respond(request_id, decision)

            if result:
                target_request_id = result if isinstance(result, str) else request_id
                logger.info(
                    f"[WS HITL] User {context.user_id} responded to decision {request_id}"
                    + (f" (target: {target_request_id})" if target_request_id != request_id else "")
                )
                await context.send_json(
                    {
                        "type": "decision_response_ack",
                        "request_id": request_id,
                        "target_request_id": target_request_id,
                        "success": True,
                    }
                )

                # Start streaming agent events after HITL response
                await _start_hitl_stream_bridge(
                    context=context,
                    request_id=target_request_id,
                )
            else:
                await context.send_error(
                    f"Decision request {request_id} not found or already answered"
                )

        except Exception as e:
            logger.error(f"[WS HITL] Error handling decision response: {e}", exc_info=True)
            await context.send_error(f"Failed to process decision response: {str(e)}")


class EnvVarRespondHandler(WebSocketMessageHandler):
    """Handle environment variable response via WebSocket."""

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
            from src.infrastructure.agent.tools.env_var_tools import get_env_var_manager

            env_var_manager = get_env_var_manager()
            result = await env_var_manager.respond(request_id, values)

            if result:
                target_request_id = result if isinstance(result, str) else request_id
                logger.info(
                    f"[WS HITL] User {context.user_id} provided env vars for request {request_id}: "
                    f"{list(values.keys())}"
                    + (f" (target: {target_request_id})" if target_request_id != request_id else "")
                )
                await context.send_json(
                    {
                        "type": "env_var_response_ack",
                        "request_id": request_id,
                        "target_request_id": target_request_id,
                        "success": True,
                        "variable_names": list(values.keys()),
                    }
                )

                # Start streaming agent events after HITL response
                await _start_hitl_stream_bridge(
                    context=context,
                    request_id=target_request_id,
                )
            else:
                await context.send_error(
                    f"Env var request {request_id} not found or already answered"
                )

        except Exception as e:
            logger.error(f"[WS HITL] Error handling env var response: {e}", exc_info=True)
            await context.send_error(f"Failed to process env var response: {str(e)}")


# =============================================================================
# Helper Functions
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
        from src.configuration.factories import create_langchain_llm
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
        llm = create_langchain_llm(context.tenant_id)
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
