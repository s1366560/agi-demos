"""
Subscription Handlers for WebSocket

Handles subscribe and unsubscribe message types for conversation events.
"""

import asyncio
import logging
from typing import Any, override

from src.infrastructure.adapters.primary.web.conversation_access_application_authority_v2 import (
    conversation_access_application_authority_v2,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.base_handler import (
    WebSocketMessageHandler,
)
from src.infrastructure.adapters.primary.web.websocket.handlers.chat_handler import (
    stream_hitl_response_to_websocket,
)
from src.infrastructure.adapters.primary.web.websocket.message_context import MessageContext
from src.infrastructure.plugins.v2.agent_recovery_stream_services import (
    AGENT_RECOVERY_STREAM_SERVICE_V2,
    AgentRecoveryStreamResolverProtocolV2,
)
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_redis_client_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    ForkedAgentOperationV2,
    current_operation_context_v2,
    detached_operation_task_context_v2,
    fork_current_agent_operation_v2,
    pin_agent_turn_operation_v2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.session_event_log import (
    SESSION_EVENT_LOG_SERVICE_V2,
    SessionEventLogServiceV2,
    SessionMessageRecoveryStateV2,
)

logger = logging.getLogger(__name__)

_recovery_reservation_cleanup_tasks: set[asyncio.Task[None]] = set()


def _is_valid_int_cursor(value: object) -> bool:
    """True only for real integers (exclude bool)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _resolve_recovery_cursor(
    recovery_state: SessionMessageRecoveryStateV2,
    requested_time_us: int | None,
    requested_counter: int | None,
) -> tuple[int | None, int | None]:
    """Resolve a client hint or the exact pinned session-log cursor."""
    cursor_time_us = requested_time_us
    cursor_counter = requested_counter
    if cursor_time_us is not None and cursor_counter is None:
        cursor_counter = 0
    if cursor_time_us is not None:
        return cursor_time_us, cursor_counter
    return recovery_state.cursor.event_time_us, recovery_state.cursor.event_counter


def _is_active_running_message(
    recovery_state: SessionMessageRecoveryStateV2,
    conversation_id: str,
    message_id: str,
) -> bool:
    """Validate a V2 Redis running key against its pinned durable state."""
    if not recovery_state.has_events:
        logger.info(
            "[WS] Skip recovery bridge for orphan running key: conv=%s message_id=%s",
            conversation_id,
            message_id,
        )
        return False
    if recovery_state.is_terminal:
        logger.info(
            "[WS] Skip recovery bridge for stale running key: conv=%s message_id=%s",
            conversation_id,
            message_id,
        )
        return False
    return True


def _session_event_log_service_v2() -> SessionEventLogServiceV2:
    """Resolve subscription recovery state from the pinned V2 operation."""
    provider = current_operation_context_v2().require(SESSION_EVENT_LOG_SERVICE_V2)
    if not isinstance(provider, SessionEventLogServiceV2):
        raise RuntimeV2Error(
            "invalid_service_implementation",
            "v2 session event-log service has an invalid implementation",
        )
    return provider


def _agent_recovery_stream_resolver_v2(
    operation: OperationContextV2,
) -> AgentRecoveryStreamResolverProtocolV2:
    resolver = operation.require(AGENT_RECOVERY_STREAM_SERVICE_V2)
    if not isinstance(resolver, AgentRecoveryStreamResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_recovery_stream",
            "v2 Agent recovery stream service has an invalid implementation",
        )
    return resolver


def _finish_recovery_reservation_cleanup(task: asyncio.Task[None]) -> None:
    _recovery_reservation_cleanup_tasks.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning("[WS] Recovery reservation cleanup was cancelled")
    except Exception:
        logger.exception("[WS] Recovery reservation cleanup failed")


def _schedule_recovery_reservation_cleanup(fork: ForkedAgentOperationV2) -> None:
    cleanup = asyncio.create_task(
        fork.release(),
        context=detached_operation_task_context_v2(),
    )
    _recovery_reservation_cleanup_tasks.add(cleanup)
    cleanup.add_done_callback(_finish_recovery_reservation_cleanup)


async def _run_recovery_stream_v2(
    *,
    fork: ForkedAgentOperationV2,
    context: MessageContext,
    conversation_id: str,
    message_id: str | None,
    replay_from_db: bool,
    cursor_time_us: int | None,
    cursor_counter: int | None,
    operation_kind: str,
) -> None:
    async with (
        context.fresh_db_context() as stream_context,
        fork.admit(
            operation_id=f"{operation_kind}:{conversation_id}",
            metadata={
                "kind": operation_kind,
                "channel": "websocket",
                "conversation_id": conversation_id,
                "message_id": message_id,
            },
            services={OPERATION_DB_SESSION_SERVICE_V2: stream_context.db},
        ) as operation,
    ):
        resolver = _agent_recovery_stream_resolver_v2(operation)
        agent_service = await resolver.resolve(operation)
        await stream_hitl_response_to_websocket(
            agent_service=agent_service,
            session_id=stream_context.session_id,
            conversation_id=conversation_id,
            message_id=message_id,
            replay_from_db=replay_from_db,
            from_time_us=cursor_time_us,
            from_counter=cursor_counter,
        )


async def _start_recovery_bridge_task_v2(
    *,
    context: MessageContext,
    conversation_id: str,
    message_id: str | None,
    replay_from_db: bool,
    cursor_time_us: int | None,
    cursor_counter: int | None,
    operation_kind: str,
) -> bool:
    fork = await fork_current_agent_operation_v2()
    task_started = False
    created_task: asyncio.Task[None] | None = None

    async def run_reserved_recovery_stream() -> None:
        nonlocal task_started
        task_started = True
        try:
            await _run_recovery_stream_v2(
                fork=fork,
                context=context,
                conversation_id=conversation_id,
                message_id=message_id,
                replay_from_db=replay_from_db,
                cursor_time_us=cursor_time_us,
                cursor_counter=cursor_counter,
                operation_kind=operation_kind,
            )
        finally:
            await fork.release()

    def create_recovery_task() -> asyncio.Task[None]:
        nonlocal created_task
        task = asyncio.create_task(
            run_reserved_recovery_stream(),
            context=detached_operation_task_context_v2(),
        )

        def release_if_never_started(_task: asyncio.Task[None]) -> None:
            if not task_started:
                _schedule_recovery_reservation_cleanup(fork)

        task.add_done_callback(
            release_if_never_started,
            context=detached_operation_task_context_v2(),
        )
        created_task = task
        return task

    try:
        started = await context.connection_manager.try_start_bridge_task(
            session_id=context.session_id,
            conversation_id=conversation_id,
            bridge_message_id=message_id,
            task_factory=create_recovery_task,
        )
    except BaseException:
        if created_task is None:
            await fork.release()
        else:
            created_task.cancel()
        raise
    if not started:
        await fork.release()
    return started


async def _maybe_start_recovery_bridge(
    context: MessageContext,
    conversation_id: str,
    project_id: str,
    message: dict[str, Any],
) -> None:
    """Start a recovery bridge on subscribe when execution is still running."""
    try:
        async with pin_agent_turn_operation_v2(
            operation_id=f"agent-subscription-recovery:{conversation_id}",
            tenant_id=context.tenant_id,
            project_id=project_id,
            session_id=conversation_id,
            services={
                OPERATION_DB_SESSION_SERVICE_V2: context.db,
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "project_id": project_id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "agent-subscription-recovery",
                    "channel": "websocket",
                    "conversation_id": conversation_id,
                },
            },
        ):
            redis_client = current_agent_worker_redis_client_v2()
            running_raw = await redis_client.get(f"agent:running:{conversation_id}")
            running_message_id: str | None = None
            if isinstance(running_raw, bytes):
                running_message_id = running_raw.decode("utf-8")
            elif isinstance(running_raw, str):
                running_message_id = running_raw

            if not running_message_id:
                return

            recovery_state = await _session_event_log_service_v2().message_recovery_state(
                conversation_id=conversation_id,
                message_id=running_message_id,
            )
            if not _is_active_running_message(
                recovery_state,
                conversation_id,
                running_message_id,
            ):
                return

            from_time_raw = message.get("from_time_us")
            from_counter_raw = message.get("from_counter")
            from_time_us = from_time_raw if _is_valid_int_cursor(from_time_raw) else None
            from_counter = from_counter_raw if _is_valid_int_cursor(from_counter_raw) else None

            cursor_time_us, cursor_counter = _resolve_recovery_cursor(
                recovery_state=recovery_state,
                requested_time_us=from_time_us,
                requested_counter=from_counter,
            )
            started = await _start_recovery_bridge_task_v2(
                context=context,
                conversation_id=conversation_id,
                message_id=running_message_id,
                replay_from_db=False,
                cursor_time_us=cursor_time_us,
                cursor_counter=cursor_counter,
                operation_kind="agent-subscription-recovery-stream",
            )
            if started:
                logger.info(
                    "[WS] Started recovery bridge on subscribe: conv=%s session=%s message_id=%s",
                    conversation_id,
                    context.session_id[:8],
                    running_message_id,
                )
    except Exception:
        logger.exception(
            "[WS] Failed to start recovery bridge for conversation %s",
            conversation_id,
        )


class SubscribeHandler(WebSocketMessageHandler):
    """Handle subscribe: Subscribe to a conversation's events."""

    @property
    @override
    def message_type(self) -> str:
        return "subscribe"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle subscribe: Subscribe to a conversation's events."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        try:
            async with conversation_access_application_authority_v2(
                context,
                conversation_id=conversation_id,
            ) as authority:
                conversation = await authority.service.find_by_id(conversation_id)

                if not conversation:
                    await context.send_error(
                        "Conversation not found",
                        conversation_id=conversation_id,
                    )
                    return

                if (
                    conversation.user_id != context.user_id
                    or conversation.tenant_id != context.tenant_id
                ):
                    await context.send_error(
                        "You do not have permission to access this conversation",
                        conversation_id=conversation_id,
                    )
                    return

                await context.connection_manager.subscribe(context.session_id, conversation_id)
                await _maybe_start_recovery_bridge(
                    context=context,
                    conversation_id=conversation_id,
                    project_id=conversation.project_id,
                    message=message,
                )
                await context.send_ack("subscribe", conversation_id=conversation_id)

        except Exception:
            logger.exception(
                "[WS] Error subscribing",
                extra={
                    "session_id": context.session_id,
                    "conversation_id": conversation_id,
                    "user_id": context.user_id,
                },
            )
            await context.send_error(
                "Failed to subscribe (see server logs)",
                conversation_id=conversation_id,
            )


class UnsubscribeHandler(WebSocketMessageHandler):
    """Handle unsubscribe: Stop receiving events from a conversation."""

    @property
    @override
    def message_type(self) -> str:
        return "unsubscribe"

    @override
    async def handle(self, context: MessageContext, message: dict[str, Any]) -> None:
        """Handle unsubscribe: Stop receiving events from a conversation."""
        conversation_id = message.get("conversation_id")

        if not conversation_id:
            await context.send_error("Missing conversation_id")
            return

        await context.connection_manager.unsubscribe(context.session_id, conversation_id)
        await context.send_ack("unsubscribe", conversation_id=conversation_id)
