"""
HITL (Human-in-the-Loop) Handlers for WebSocket

Handles clarification_respond, decision_respond, env_var_respond, and permission_respond
message types. Uses Redis Streams to communicate with the running Ray Actor.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.domain.model.agent.hitl_request import HITLRequest
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_FACTORY_FALLBACK_WARNED = False


def _resolve_session_factory(
    session_factory: "async_sessionmaker[AsyncSession] | None",
) -> "async_sessionmaker[AsyncSession]":
    """Resolve the async sessionmaker, falling back to the global with a one-shot deprecation log.

    P2-18: Helpers should receive an injected sessionmaker via MessageContext /
    RunContext. The module-level fallback exists only as a transitional shim and
    will be removed once all call sites are migrated.
    """
    if session_factory is not None:
        return session_factory
    global _FACTORY_FALLBACK_WARNED
    if not _FACTORY_FALLBACK_WARNED:
        logger.warning(
            "[WS HITL] session_factory not injected; falling back to global "
            "async_session_factory (deprecated, will be removed)"
        )
        _FACTORY_FALLBACK_WARNED = True
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )

    return async_session_factory


# =============================================================================
# Helper Functions
# =============================================================================


async def _publish_hitl_response_to_redis(
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    message_id: str | None,
    request_id: str,
    hitl_type: str,
    response_data: dict[str, Any],
    user_id: str,
    agent_mode: str,
) -> bool:
    """Publish HITL response to Redis Stream for Ray Actor delivery."""
    try:
        from src.configuration.config import get_settings
        from src.infrastructure.agent.hitl.utils import serialize_hitl_stream_response
        from src.infrastructure.agent.state.agent_worker_state import (
            get_redis_client,
        )

        settings = get_settings()
        if not getattr(settings, "hitl_realtime_enabled", True):
            logger.debug("[WS HITL] Realtime disabled, skipping Redis publish")
            return False

        redis = await get_redis_client()

        stream_key = f"hitl:response:{tenant_id}:{project_id}"
        message_data: dict[str, Any] = {
            "request_id": request_id,
            "hitl_type": hitl_type,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "agent_mode": agent_mode,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        message_data.update(serialize_hitl_stream_response(hitl_type, response_data))

        await redis.xadd(stream_key, {"data": json.dumps(message_data)}, maxlen=1000)

        logger.info(f"[WS HITL] Published response to Redis: {request_id}")
        return True

    except Exception as e:
        logger.warning(f"[WS HITL] Failed to publish to Redis: {e}")
        return False


async def _load_hitl_request(
    request_id: str,
    *,
    session_factory: "async_sessionmaker[AsyncSession] | None" = None,
) -> HITLRequest | None:
    """Load the latest HITL request using a fresh ORM-backed session."""
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    factory = _resolve_session_factory(session_factory)
    try:
        async with factory() as fresh_session:
            repo = SqlHITLRequestRepository(fresh_session)
            hitl_request = await repo.get_by_id(request_id)
    except Exception as e:
        logger.error(f"[WS HITL] Failed to load HITL request: {e}", exc_info=True)
        return None

    if hitl_request is None:
        logger.warning(f"[WS HITL] HITL request {request_id} not found")
        return None

    logger.debug(f"[WS HITL] Found HITL request {request_id} using repository query")
    return hitl_request


async def _user_has_hitl_access(
    *,
    user_id: str,
    tenant_id: str,
    project_id: str | None,
    conversation_id: str,
    session_factory: "async_sessionmaker[AsyncSession] | None" = None,
) -> bool:
    """Return True when the user owns the target conversation in the same tenant."""
    from src.infrastructure.adapters.secondary.persistence.models import Conversation

    factory = _resolve_session_factory(session_factory)
    async with factory() as auth_session:
        conversation_query = select(Conversation.id).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
        conversation_result = await auth_session.execute(
            refresh_select_statement(conversation_query)
        )
        return conversation_result.scalar_one_or_none() is not None


async def _user_has_project_access(
    *,
    user_id: str,
    project_id: str,
    session_factory: "async_sessionmaker[AsyncSession] | None" = None,
) -> bool:
    """Return True when the user belongs to the target project."""
    from src.infrastructure.adapters.secondary.persistence.models import UserProject

    factory = _resolve_session_factory(session_factory)
    async with factory() as auth_session:
        membership_query = select(UserProject.id).where(
            UserProject.user_id == user_id,
            UserProject.project_id == project_id,
        )
        membership_result = await auth_session.execute(refresh_select_statement(membership_query))
        return membership_result.scalar_one_or_none() is not None


def _validate_hitl_response_shape(*, hitl_type: str, response_data: dict[str, Any]) -> str | None:
    """Return an error when the ingress payload shape is invalid."""
    has_cancelled = response_data.get("cancelled") is True
    has_timeout = response_data.get("timeout") is True

    if hitl_type != "env_var" and (has_cancelled or has_timeout):
        return "cancelled/timeout responses are only supported for env_var HITL"

    if hitl_type != "env_var":
        return None

    has_values = "values" in response_data
    variant_count = sum((has_values, has_cancelled, has_timeout))
    if variant_count != 1:
        return "env_var responses must include exactly one of values/cancelled/timeout"

    if has_values and not isinstance(response_data.get("values"), dict):
        return "env_var values must be an object"

    return None


async def _persist_hitl_response(
    request_id: str,
    response_str: str,
    response_metadata: dict[str, Any] | None,
    *,
    session_factory: "async_sessionmaker[AsyncSession] | None" = None,
) -> None:
    """Persist a validated HITL response with a single-winner claim."""
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    factory = _resolve_session_factory(session_factory)
    async with factory() as update_session:
        repo = SqlHITLRequestRepository(update_session)
        updated_request = await repo.update_response(
            request_id,
            response_str,
            response_metadata=response_metadata,
        )
        if updated_request is None:
            raise RuntimeError(f"HITL request {request_id} could not be updated")
        await update_session.commit()


async def _mark_hitl_timeout(
    request_id: str,
    *,
    session_factory: "async_sessionmaker[AsyncSession] | None" = None,
) -> bool:
    """Persist TIMEOUT for an expired request before rejecting late responses."""
    from src.infrastructure.adapters.secondary.persistence.sql_hitl_request_repository import (
        SqlHITLRequestRepository,
    )

    factory = _resolve_session_factory(session_factory)
    async with factory() as update_session:
        repo = SqlHITLRequestRepository(update_session)
        timed_out_request = await repo.mark_timeout(request_id)
        if timed_out_request is None:
            return False
        await update_session.commit()
        return True


async def _load_authorized_pending_hitl_request(
    *,
    context: MessageContext,
    request_id: str,
) -> HITLRequest | None:
    """Load a pending HITL request after tenant/project/conversation authorization."""
    from src.domain.model.agent.hitl_request import HITLRequestStatus

    hitl_request = await _load_hitl_request(request_id, session_factory=context.session_factory)
    if not hitl_request:
        logger.error(f"[WS HITL] HITL request {request_id} not found in database")
        await context.send_error(f"HITL request {request_id} not found")
        return None

    conversation_id = hitl_request.conversation_id
    if hitl_request.tenant_id != context.tenant_id:
        await context.send_error("Access denied", conversation_id=conversation_id)
        return None

    if hitl_request.user_id:
        if hitl_request.user_id != context.user_id:
            await context.send_error("Access denied", conversation_id=conversation_id)
            return None
        has_access = bool(hitl_request.project_id) and await _user_has_project_access(
            user_id=context.user_id,
            project_id=hitl_request.project_id,
            session_factory=context.session_factory,
        )
    else:
        has_access = await _user_has_hitl_access(
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            project_id=hitl_request.project_id,
            conversation_id=conversation_id,
            session_factory=context.session_factory,
        )
    if not has_access:
        await context.send_error("Access denied", conversation_id=conversation_id)
        return None

    expires_at = hitl_request.expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        await _mark_hitl_timeout(request_id, session_factory=context.session_factory)
        await context.send_error(
            f"HITL request {request_id} has expired (status: timeout)",
            conversation_id=conversation_id,
        )
        return None

    if hitl_request.status != HITLRequestStatus.PENDING:
        await context.send_error(
            f"HITL request {request_id} is no longer pending (status: {hitl_request.status.value})",
            conversation_id=conversation_id,
        )
        return None

    return hitl_request


async def _validate_and_summarize_hitl_response(
    *,
    context: MessageContext,
    hitl_request: HITLRequest,
    hitl_type: str,
    response_data: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None] | None:
    """Validate HITL response semantics and return redacted persistence values."""
    from src.domain.model.agent.hitl_types import HITLType
    from src.infrastructure.agent.hitl.coordinator import validate_hitl_response
    from src.infrastructure.agent.hitl.utils import (
        build_hitl_request_data_from_record,
        resolve_trusted_hitl_type,
        summarize_hitl_response,
    )

    conversation_id = hitl_request.conversation_id
    stored_hitl_type = resolve_trusted_hitl_type(hitl_request)
    if stored_hitl_type is None:
        await context.send_error(
            "HITL request has an invalid stored type",
            conversation_id=conversation_id,
        )
        return None

    if hitl_type != stored_hitl_type:
        await context.send_error(
            "HITL type does not match request",
            conversation_id=conversation_id,
        )
        return None

    shape_error = _validate_hitl_response_shape(
        hitl_type=stored_hitl_type,
        response_data=response_data,
    )
    if shape_error is not None:
        await context.send_error(shape_error, conversation_id=conversation_id)
        return None

    is_valid, validation_error = validate_hitl_response(
        hitl_type=HITLType(stored_hitl_type),
        request_data=build_hitl_request_data_from_record(hitl_request),
        response_data=response_data,
        conversation_id=conversation_id,
        tenant_id=hitl_request.tenant_id,
        project_id=hitl_request.project_id,
        message_id=hitl_request.message_id,
        received_tenant_id=context.tenant_id,
        received_project_id=hitl_request.project_id,
        received_conversation_id=conversation_id,
        received_message_id=hitl_request.message_id,
    )
    if not is_valid:
        await context.send_error(
            validation_error or "Invalid HITL response",
            conversation_id=conversation_id,
        )
        return None

    response_str, response_metadata = summarize_hitl_response(stored_hitl_type, response_data)
    return stored_hitl_type, response_str, response_metadata


async def _handle_hitl_response(
    context: MessageContext,
    request_id: str,
    hitl_type: str,
    response_data: dict[str, Any],
    ack_type: str,
) -> None:
    """
    Common handler for all HITL response types.

    Uses Redis Streams to communicate with the running Ray Actor.
    """
    hitl_request = await _load_authorized_pending_hitl_request(
        context=context,
        request_id=request_id,
    )
    if hitl_request is None:
        return

    conversation_id = hitl_request.conversation_id
    validated_response = await _validate_and_summarize_hitl_response(
        context=context,
        hitl_request=hitl_request,
        hitl_type=hitl_type,
        response_data=response_data,
    )
    if validated_response is None:
        return
    stored_hitl_type, response_str, response_metadata = validated_response

    try:
        await _persist_hitl_response(
            request_id=request_id,
            response_str=response_str,
            response_metadata=response_metadata,
            session_factory=context.session_factory,
        )
    except Exception as e:
        logger.error(f"[WS HITL] Failed to update HITL request: {e}", exc_info=True)
        await context.send_error(
            f"Failed to update HITL request: {e!s}",
            conversation_id=conversation_id,
        )
        return

    # Publish to Redis Stream after the single-winner claim has been committed.
    agent_mode = (hitl_request.metadata or {}).get("agent_mode", "default")
    redis_sent = await _publish_hitl_response_to_redis(
        tenant_id=hitl_request.tenant_id,
        project_id=hitl_request.project_id,
        conversation_id=conversation_id,
        message_id=hitl_request.message_id,
        request_id=request_id,
        hitl_type=stored_hitl_type,
        response_data=response_data,
        user_id=context.user_id,
        agent_mode=agent_mode,
    )

    if not redis_sent:
        logger.warning(
            "[WS HITL] Response publish failed after claim: request_id=%s type=%s "
            "keeping_answered_state=true",
            request_id,
            stored_hitl_type,
        )
        await context.send_json(
            {
                "type": ack_type,
                "request_id": request_id,
                "success": True,
                "delivery_pending": True,
                "conversation_id": conversation_id,
            }
        )
        return

    logger.info(
        f"[WS HITL] User {context.user_id} responded to {stored_hitl_type} {request_id} "
        "via Redis Stream"
    )

    await context.send_json(
        {
            "type": ack_type,
            "request_id": request_id,
            "success": True,
            "conversation_id": conversation_id,
        }
    )

    # Start streaming agent events after HITL response
    await _start_hitl_stream_bridge(
        context=context,
        request_id=request_id,
    )


class ClarificationRespondHandler(WebSocketMessageHandler):
    """Handle clarification response via WebSocket using Temporal Signal."""

    @property
    def message_type(self) -> str:
        return "clarification_respond"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
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
            await context.send_error(f"Failed to process clarification response: {e!s}")


class DecisionRespondHandler(WebSocketMessageHandler):
    """Handle decision response via WebSocket using Temporal Signal."""

    @property
    def message_type(self) -> str:
        return "decision_respond"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
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
            await context.send_error(f"Failed to process decision response: {e!s}")


class EnvVarRespondHandler(WebSocketMessageHandler):
    """Handle environment variable response via WebSocket using Temporal Signal."""

    @property
    def message_type(self) -> str:
        return "env_var_respond"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle environment variable response."""
        request_id = message.get("request_id")
        values = message.get("values")
        cancelled = message.get("cancelled") is True
        timeout = message.get("timeout") is True

        choices = [
            option
            for option, enabled in (
                ("values", isinstance(values, dict)),
                ("cancelled", cancelled),
                ("timeout", timeout),
            )
            if enabled
        ]
        if not request_id or len(choices) != 1:
            await context.send_error(
                "Missing required fields: request_id and exactly one of values/cancelled/timeout"
            )
            return

        response_data: dict[str, Any]
        if isinstance(values, dict):
            response_data = {"values": values}
        elif cancelled:
            response_data = {"cancelled": True}
        else:
            response_data = {"timeout": True}

        try:
            await _handle_hitl_response(
                context=context,
                request_id=request_id,
                hitl_type="env_var",
                response_data=response_data,
                ack_type="env_var_response_ack",
            )
        except Exception as e:
            logger.error(f"[WS HITL] Error handling env var response: {e}", exc_info=True)
            await context.send_error(f"Failed to process env var response: {e!s}")


class PermissionRespondHandler(WebSocketMessageHandler):
    """Handle permission response via WebSocket using Redis Streams."""

    @property
    def message_type(self) -> str:
        return "permission_respond"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle permission response."""
        request_id = message.get("request_id")
        granted = message.get("granted")

        if not request_id or granted is None:
            await context.send_error("Missing required fields: request_id, granted")
            return

        try:
            action = "allow" if granted else "deny"
            await _handle_hitl_response(
                context=context,
                request_id=request_id,
                hitl_type="permission",
                response_data={"granted": granted, "action": action},
                ack_type="permission_response_ack",
            )
        except Exception as e:
            logger.error(f"[WS HITL] Error handling permission response: {e}", exc_info=True)
            await context.send_error(f"Failed to process permission response: {e!s}")


class A2UIActionRespondHandler(WebSocketMessageHandler):
    """Handle A2UI action response via WebSocket using Redis Streams."""

    @property
    def message_type(self) -> str:
        return "a2ui_action_respond"

    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle A2UI action response."""
        request_id = message.get("request_id")
        action_name = message.get("action_name")
        source_component_id = message.get("source_component_id", "")
        action_context = message.get("context", {})

        if not request_id or action_name is None:
            await context.send_error("Missing required fields: request_id, action_name")
            return

        try:
            await _handle_hitl_response(
                context=context,
                request_id=request_id,
                hitl_type="a2ui_action",
                response_data={
                    "action_name": action_name,
                    "source_component_id": source_component_id,
                    "context": action_context,
                },
                ack_type="a2ui_action_response_ack",
            )
        except Exception as e:
            logger.error(f"[WS HITL] Error handling A2UI action response: {e}", exc_info=True)
            await context.send_error(f"Failed to process A2UI action response: {e!s}")


# =============================================================================
# Stream Bridge Helper
# =============================================================================


async def _start_hitl_stream_bridge(
    context: MessageContext,
    request_id: str,
) -> None:
    """
    Start streaming agent events after HITL response (crash recovery only).

    In the Future-based HITL architecture, the original bridge task (from
    stream_agent_to_websocket) stays alive during HITL pauses and naturally
    picks up events after the Future resolves. A new bridge is only needed
    for crash recovery (page refresh, reconnect) when the original bridge
    is dead.
    """
    try:
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

        # If there's already an active bridge for this conversation, the
        # original stream_agent_to_websocket task is still running and will
        # deliver post-HITL events. No need for a second bridge.
        existing_tasks = manager.bridge_tasks.get(context.session_id, {})
        existing_task = existing_tasks.get(conversation_id)
        if existing_task and not existing_task.done():
            logger.info(
                f"[WS HITL] Original bridge still alive for conversation {conversation_id}, "
                f"skipping HITL bridge (Future-based architecture)"
            )
            return

        # Original bridge is dead (crash recovery / page refresh).
        # Start a new bridge to stream post-HITL events.
        logger.info(
            f"[WS HITL] Starting recovery bridge for request {request_id}, "
            f"conversation={conversation_id}"
        )

        # Auto-subscribe session to conversation
        await manager.subscribe(context.session_id, conversation_id)

        # Import here to avoid circular imports
        from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
            stream_hitl_response_to_websocket,
        )

        async def _run_hitl_recovery_stream() -> None:
            from src.configuration.factories import create_llm_client

            async with context.fresh_db_context() as stream_context:
                llm = await create_llm_client(stream_context.tenant_id)
                agent_service = stream_context.get_scoped_container().agent_service(llm)
                await stream_hitl_response_to_websocket(
                    agent_service=agent_service,
                    session_id=stream_context.session_id,
                    conversation_id=conversation_id,
                    message_id=None,  # Read all new events
                )

        task = asyncio.create_task(_run_hitl_recovery_stream())
        manager.add_bridge_task(context.session_id, conversation_id, task)

    except Exception as e:
        logger.error(f"[WS HITL] Failed to start stream bridge: {e}", exc_info=True)
