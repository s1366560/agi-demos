"""
Chat Handlers for WebSocket

Handles send_message and stop_session message types.
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


class SendMessageHandler(WebSocketMessageHandler):
    """Handle send_message: Start agent execution."""

    @property
    def message_type(self) -> str:
        return "send_message"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Handle send_message: Start agent execution."""
        conversation_id = message.get("conversation_id")
        user_message = message.get("message")
        project_id = message.get("project_id")
        attachment_ids = message.get("attachment_ids")

        if not all([conversation_id, user_message, project_id]):
            await context.send_error(
                "Missing required fields: conversation_id, message, project_id"
            )
            return

        try:
            container = context.get_scoped_container()

            # Verify conversation ownership
            conversation_repo = container.conversation_repository()
            conversation = await conversation_repo.find_by_id(conversation_id)

            if not conversation:
                await context.send_error(
                    "Conversation not found", conversation_id=conversation_id
                )
                return

            if conversation.user_id != context.user_id:
                await context.send_error(
                    "You do not have permission to access this conversation",
                    conversation_id=conversation_id,
                )
                return

            # Check for pending HITL requests
            from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
                SqlHITLRequestRepository,
            )

            hitl_repo = SqlHITLRequestRepository(context.db)
            pending_hitl = await hitl_repo.get_pending_by_conversation(
                conversation_id=conversation_id,
                tenant_id=context.tenant_id,
                project_id=project_id,
                exclude_expired=True,
            )

            if pending_hitl:
                pending_types = [r.request_type.value for r in pending_hitl]
                await context.send_error(
                    f"Agent is waiting for your response. Please complete the pending "
                    f"{', '.join(pending_types)} request(s) before sending new messages.",
                    code="HITL_PENDING",
                    conversation_id=conversation_id,
                    extra={
                        "pending_requests": [
                            {
                                "request_id": r.id,
                                "request_type": r.request_type.value,
                                "question": r.question,
                            }
                            for r in pending_hitl
                        ]
                    },
                )
                return

            # Auto-subscribe this session to this conversation
            await context.connection_manager.subscribe(context.session_id, conversation_id)

            # Create LLM and agent service
            from src.configuration.factories import create_llm_client

            llm = create_llm_client(context.tenant_id)
            agent_service = container.agent_service(llm)

            # Send acknowledgment
            await context.send_ack("send_message", conversation_id=conversation_id)

            # Start streaming in background task
            task = asyncio.create_task(
                stream_agent_to_websocket(
                    agent_service=agent_service,
                    context=context,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    project_id=project_id,
                    attachment_ids=attachment_ids,
                )
            )
            context.connection_manager.add_bridge_task(
                context.session_id, conversation_id, task
            )

        except Exception as e:
            logger.error(f"[WS] Error handling send_message: {e}", exc_info=True)
            await context.send_error(str(e), conversation_id=conversation_id)


class StopSessionHandler(WebSocketMessageHandler):
    """Handle stop_session: Cancel ongoing agent execution."""

    @property
    def message_type(self) -> str:
        return "stop_session"

    async def handle(self, context: MessageContext, message: Dict[str, Any]) -> None:
        """Handle stop_session: Cancel ongoing agent execution."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        try:
            manager = context.connection_manager

            # Cancel the bridge task if exists for this session
            if (
                context.session_id in manager.bridge_tasks
                and conversation_id in manager.bridge_tasks[context.session_id]
            ):
                task = manager.bridge_tasks[context.session_id][conversation_id]
                task.cancel()
                del manager.bridge_tasks[context.session_id][conversation_id]
                logger.info(f"[WS] Cancelled stream task for conversation {conversation_id}")

            # Cancel Ray Actor execution
            try:
                from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
                    SqlConversationRepository,
                )
                from src.infrastructure.adapters.secondary.ray.client import await_ray
                from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

                conv_repo = SqlConversationRepository(context.db)
                conversation = await conv_repo.find_by_id(conversation_id)
                if not conversation:
                    await context.send_error("Conversation not found", conversation_id=conversation_id)
                    return
                if conversation.tenant_id != context.tenant_id:
                    await context.send_error("Access denied", conversation_id=conversation_id)
                    return

                actor = await get_actor_if_exists(
                    tenant_id=conversation.tenant_id,
                    project_id=conversation.project_id,
                    agent_mode="default",
                )
                if actor:
                    await await_ray(actor.cancel.remote(conversation_id))
                    logger.info(
                        "[WS] Cancelled Ray actor execution for conversation %s",
                        conversation_id,
                    )
            except Exception as e:
                logger.warning(f"[WS] Failed to cancel Ray actor: {e}")

            # Send acknowledgment
            await context.send_ack("stop_session", conversation_id=conversation_id)

        except Exception as e:
            logger.error(f"[WS] Error stopping session: {e}", exc_info=True)
            await context.send_error(str(e), conversation_id=conversation_id)


# =============================================================================
# Helper Functions
# =============================================================================


async def stream_agent_to_websocket(
    agent_service: Any,
    context: MessageContext,
    conversation_id: str,
    user_message: str,
    project_id: str,
    attachment_ids: Optional[list] = None,
) -> None:
    """
    Stream agent events to WebSocket.

    Events are broadcast to ALL sessions subscribed to this conversation,
    allowing multiple browser tabs to receive the same messages in real-time.
    """
    manager = context.connection_manager
    event_count = 0

    try:
        async for event in agent_service.stream_chat_v2(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            attachment_ids=attachment_ids,
        ):
            event_count += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # DEBUG: Log every event received from agent_service
            logger.warning(
                f"[WS Bridge] Event #{event_count}: type={event_type}, conv={conversation_id}"
            )

            # Check if session is still subscribed
            if not manager.is_subscribed(context.session_id, conversation_id):
                logger.info(
                    f"[WS] Session {context.session_id[:8]}... unsubscribed, stopping stream"
                )
                break

            # Add conversation_id to event for routing
            ws_event = {
                "type": event.get("type"),
                "conversation_id": conversation_id,
                "data": event_data,
                "seq": event.get("id"),
                "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
                "event_time_us": event.get("event_time_us"),
                "event_counter": event.get("event_counter"),
            }

            # Broadcast to ALL sessions subscribed to this conversation
            await manager.broadcast_to_conversation(conversation_id, ws_event)

    except asyncio.CancelledError:
        logger.info(f"[WS] Stream cancelled for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"[WS] Error streaming to websocket: {e}", exc_info=True)
        # Send error only to the initiating session
        await manager.send_to_session(
            context.session_id,
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            },
        )


async def stream_hitl_response_to_websocket(
    agent_service: Any,
    session_id: str,
    conversation_id: str,
    message_id: Optional[str] = None,
) -> None:
    """
    Stream agent events after HITL response to WebSocket.

    Called after a HITL response (clarification, decision, env_var)
    to continue streaming agent events to the frontend.
    """
    from src.infrastructure.adapters.primary.web.websocket.connection_manager import (
        get_connection_manager,
    )

    manager = get_connection_manager()
    event_count = 0

    try:
        logger.info(
            f"[WS HITL Bridge] Starting stream for conversation {conversation_id}, "
            f"message_id={message_id or 'ALL'}"
        )

        async for event in agent_service.connect_chat_stream(
            conversation_id=conversation_id,
            message_id=message_id,
        ):
            event_count += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # DEBUG: Log events
            if event_count <= 20:
                logger.warning(
                    f"[WS HITL Bridge] Event #{event_count}: type={event_type}, "
                    f"conv={conversation_id}"
                )

            # Check if session is still subscribed
            if not manager.is_subscribed(session_id, conversation_id):
                logger.info(
                    f"[WS HITL] Session {session_id[:8]}... unsubscribed, stopping stream"
                )
                break

            # Add conversation_id to event for routing
            ws_event = {
                "type": event_type,
                "conversation_id": conversation_id,
                "data": event_data,
                "seq": event.get("id"),
                "timestamp": event.get("timestamp", datetime.utcnow().isoformat()),
                "event_time_us": event.get("event_time_us"),
                "event_counter": event.get("event_counter"),
            }

            # Broadcast to ALL sessions subscribed to this conversation
            await manager.broadcast_to_conversation(conversation_id, ws_event)

            # Stop after completion or when agent pauses for another HITL request.
            # HITL-asked events mean the agent has paused again waiting for user input,
            # so the bridge should stop and let _start_hitl_stream_bridge create a new
            # one when the user responds to the next HITL request.
            HITL_ASKED_EVENTS = {
                "clarification_asked", "decision_asked",
                "env_var_requested", "permission_asked",
            }
            if event_type in ("complete", "error"):
                logger.info(f"[WS HITL Bridge] Stream completed: type={event_type}")
                break
            if event_type in HITL_ASKED_EVENTS:
                logger.info(
                    f"[WS HITL Bridge] Agent paused for another HITL: type={event_type}, "
                    f"stopping bridge for conversation {conversation_id}"
                )
                break

    except asyncio.CancelledError:
        logger.info(f"[WS HITL] Stream cancelled for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"[WS HITL] Error streaming to websocket: {e}", exc_info=True)
        await manager.send_to_session(
            session_id,
            {
                "type": "error",
                "conversation_id": conversation_id,
                "data": {"message": str(e)},
            },
        )
