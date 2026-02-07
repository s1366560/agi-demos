"""Execution helpers for Actor-based project agent runtime."""

from __future__ import annotations

import json
import logging
import time as time_module
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from src.configuration.config import get_settings
from src.domain.model.agent.hitl_types import HITLPendingException
from src.infrastructure.adapters.primary.web.metrics import agent_metrics
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent
from src.infrastructure.adapters.secondary.temporal.agent_worker_state import get_redis_client
from src.infrastructure.agent.actor.state.snapshot_repo import (
    delete_hitl_snapshot,
    load_hitl_snapshot,
    save_hitl_snapshot,
)
from src.infrastructure.agent.actor.state.running_state import (
    clear_agent_running,
    refresh_agent_running_ttl,
    set_agent_running,
)
from src.infrastructure.agent.actor.types import ProjectChatRequest, ProjectChatResult
from src.infrastructure.agent.core.project_react_agent import ProjectReActAgent
from src.infrastructure.agent.hitl.state_store import HITLAgentState, HITLStateStore

logger = logging.getLogger(__name__)


async def execute_project_chat(
    agent: ProjectReActAgent,
    request: ProjectChatRequest,
    hitl_response: Optional[Dict[str, Any]] = None,
) -> ProjectChatResult:
    """Execute a chat request and publish events to Redis/DB."""
    start_time = time_module.time()
    events: List[Dict[str, Any]] = []
    final_content = ""
    is_error = False
    error_message = None

    await set_agent_running(request.conversation_id, request.message_id)

    # Initialize sequence_number from last DB sequence to avoid collisions
    # with events already saved (e.g., user_message saved by agent_service)
    sequence_number = await _get_last_db_sequence(request.conversation_id)

    try:
        redis_client = await _get_redis_client()
        last_refresh = time_module.time()

        async for event in agent.execute_chat(
            conversation_id=request.conversation_id,
            user_message=request.user_message,
            user_id=request.user_id,
            conversation_context=request.conversation_context,
            tenant_id=agent.config.tenant_id,
            message_id=request.message_id,
            hitl_response=hitl_response,
        ):
            sequence_number += 1
            event["seq"] = sequence_number
            events.append(event)

            await _publish_event_to_stream(
                conversation_id=request.conversation_id,
                event=event,
                message_id=request.message_id,
                sequence_number=sequence_number,
                correlation_id=request.correlation_id,
                redis_client=redis_client,
            )

            event_type = event.get("type")
            if event_type == "complete":
                final_content = event.get("data", {}).get("content", "")
            elif event_type == "error":
                is_error = True
                error_message = event.get("data", {}).get("message", "Unknown error")

            now = time_module.time()
            if now - last_refresh > 60:
                await refresh_agent_running_ttl(request.conversation_id)
                last_refresh = now

        await _persist_events(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            events=events,
            correlation_id=request.correlation_id,
        )

        execution_time_ms = (time_module.time() - start_time) * 1000

        agent_metrics.increment(
            "project_agent.chat_total",
            labels={"project_id": agent.config.project_id},
        )
        agent_metrics.observe(
            "project_agent.chat_latency_ms",
            execution_time_ms,
            labels={"project_id": agent.config.project_id},
        )

        if is_error:
            agent_metrics.increment(
                "project_agent.chat_errors",
                labels={"project_id": agent.config.project_id},
            )

        return ProjectChatResult(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            content=final_content,
            sequence_number=sequence_number,
            is_error=is_error,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            event_count=len(events),
        )

    except HITLPendingException as hitl_ex:
        if events:
            await _persist_events(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                events=events,
                correlation_id=request.correlation_id,
            )
        return await handle_hitl_pending(agent, request, hitl_ex, sequence_number)

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        agent_metrics.increment("project_agent.chat_errors")
        logger.error(f"[ActorExecution] Chat error: {e}", exc_info=True)

        try:
            await _publish_error_event(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                error_message=str(e),
                correlation_id=request.correlation_id,
            )
        except Exception as pub_error:
            logger.warning(f"[ActorExecution] Failed to publish error event: {pub_error}")

        return ProjectChatResult(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            content="",
            sequence_number=0,
            is_error=True,
            error_message=str(e),
            execution_time_ms=execution_time_ms,
            event_count=0,
        )
    finally:
        await clear_agent_running(request.conversation_id)


async def handle_hitl_pending(
    agent: ProjectReActAgent,
    request: ProjectChatRequest,
    hitl_exception: HITLPendingException,
    last_sequence_number: int = 0,
) -> ProjectChatResult:
    """Persist HITL state to Redis and Postgres and return pending result."""
    redis_client = await _get_redis_client()
    state_store = HITLStateStore(redis_client)

    saved_messages = hitl_exception.current_messages or request.conversation_context

    logger.info(
        f"[ActorExecution] Handling HITL pending: request_id={hitl_exception.request_id}, "
        f"type={hitl_exception.hitl_type.value}, "
        f"messages_count={len(saved_messages)}, "
        f"last_sequence_number={last_sequence_number}"
    )

    state = HITLAgentState(
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        tenant_id=agent.config.tenant_id,
        project_id=agent.config.project_id,
        hitl_request_id=hitl_exception.request_id,
        hitl_type=hitl_exception.hitl_type.value,
        hitl_request_data=hitl_exception.request_data,
        messages=list(saved_messages),
        user_message=request.user_message,
        user_id=request.user_id,
        correlation_id=request.correlation_id,
        step_count=getattr(agent, "_step_count", 0),
        timeout_seconds=hitl_exception.timeout_seconds,
        pending_tool_call_id=hitl_exception.tool_call_id,
        last_sequence_number=last_sequence_number,
    )

    await state_store.save_state(state)
    await save_hitl_snapshot(state, agent.config.agent_mode)

    logger.info(
        f"[ActorExecution] HITL state saved: request_id={hitl_exception.request_id}, "
        f"conversation_id={request.conversation_id}"
    )

    return ProjectChatResult(
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        content="",
        sequence_number=last_sequence_number,  # Preserve sequence number for continuity
        is_error=False,
        error_message=None,
        execution_time_ms=0.0,
        event_count=0,
        hitl_pending=True,
        hitl_request_id=hitl_exception.request_id,
    )


async def continue_project_chat(
    agent: ProjectReActAgent,
    request_id: str,
    response_data: Dict[str, Any],
) -> ProjectChatResult:
    """Resume an HITL-paused chat using stored state."""
    start_time = time_module.time()
    sequence_number = 0
    events: List[Dict[str, Any]] = []
    final_content = ""
    is_error = False
    error_message = None

    redis_client = await _get_redis_client()
    state_store = HITLStateStore(redis_client)

    logger.info(
        f"[ActorExecution] Continuing chat: request_id={request_id}, "
        f"response_keys={list(response_data.keys()) if response_data else 'None'}"
    )

    state = None
    for attempt in range(10):
        state = await state_store.load_state_by_request(request_id)
        if not state:
            state = await load_hitl_snapshot(request_id)
        if state:
            break
        if attempt < 9:
            await asyncio.sleep(0.2)

    if not state:
        logger.error(
            f"[ActorExecution] HITL state not found for request_id={request_id}"
        )
        return ProjectChatResult(
            conversation_id="",
            message_id="",
            content="",
            sequence_number=0,
            is_error=True,
            error_message="HITL state not found or expired",
            execution_time_ms=(time_module.time() - start_time) * 1000,
            event_count=0,
        )

    logger.info(
        f"[ActorExecution] Loaded HITL state: conversation_id={state.conversation_id}, "
        f"hitl_type={state.hitl_type}, messages_count={len(state.messages)}, "
        f"last_sequence_number={state.last_sequence_number}"
    )

    # Use the greater of HITL state sequence and actual DB sequence
    # to avoid collisions with events saved by other paths
    db_last_seq = await _get_last_db_sequence(state.conversation_id)
    sequence_number = max(sequence_number, state.last_sequence_number, db_last_seq)
    await set_agent_running(state.conversation_id, state.message_id)

    try:
        hitl_response_for_agent = {
            "request_id": request_id,
            "hitl_type": state.hitl_type,
            "response_data": response_data,
        }

        conversation_context = list(state.messages)
        if state.pending_tool_call_id:
            tool_result_content = _format_hitl_response_as_tool_result(
                hitl_type=state.hitl_type,
                response_data=response_data,
            )
            conversation_context = [
                *conversation_context,
                {
                    "role": "tool",
                    "tool_call_id": state.pending_tool_call_id,
                    "content": tool_result_content,
                },
            ]

        await state_store.delete_state_by_request(request_id)
        await delete_hitl_snapshot(request_id)

        last_refresh = time_module.time()

        try:
            async for event in agent.execute_chat(
                conversation_id=state.conversation_id,
                user_message=state.user_message,
                user_id=state.user_id,
                conversation_context=conversation_context,
                tenant_id=state.tenant_id,
                message_id=state.message_id,
                hitl_response=hitl_response_for_agent,
            ):
                sequence_number += 1
                event["seq"] = sequence_number
                events.append(event)

                await _publish_event_to_stream(
                    conversation_id=state.conversation_id,
                    event=event,
                    message_id=state.message_id,
                    sequence_number=sequence_number,
                    correlation_id=state.correlation_id,
                    redis_client=redis_client,
                )

                event_type = event.get("type")
                if event_type == "complete":
                    final_content = event.get("data", {}).get("content", "")
                elif event_type == "error":
                    is_error = True
                    error_message = event.get("data", {}).get("message", "Unknown error")

                now = time_module.time()
                if now - last_refresh > 60:
                    await refresh_agent_running_ttl(state.conversation_id)
                    last_refresh = now
        except HITLPendingException as hitl_ex:
            logger.info(
                f"[ActorExecution] Second HITL detected during continue: "
                f"first_request_id={request_id}, "
                f"second_request_id={hitl_ex.request_id}, "
                f"events_emitted={len(events)}, "
                f"sequence_number={sequence_number}"
            )
            if events:
                await _persist_events(
                    conversation_id=state.conversation_id,
                    message_id=state.message_id,
                    events=events,
                    correlation_id=state.correlation_id,
                )
            resume_request = ProjectChatRequest(
                conversation_id=state.conversation_id,
                message_id=state.message_id,
                user_message=state.user_message,
                user_id=state.user_id,
                conversation_context=conversation_context,
                correlation_id=state.correlation_id,
            )
            return await handle_hitl_pending(agent, resume_request, hitl_ex, sequence_number)

        await _persist_events(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            events=events,
            correlation_id=state.correlation_id,
        )

        execution_time_ms = (time_module.time() - start_time) * 1000

        return ProjectChatResult(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            content=final_content,
            sequence_number=sequence_number,
            is_error=is_error,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            event_count=len(events),
        )

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        logger.error(f"[ActorExecution] Continue chat error: {e}", exc_info=True)
        return ProjectChatResult(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            content="",
            sequence_number=0,
            is_error=True,
            error_message=str(e),
            execution_time_ms=execution_time_ms,
            event_count=0,
        )
    finally:
        await clear_agent_running(state.conversation_id)


async def _get_last_db_sequence(conversation_id: str) -> int:
    """Get the last sequence number for a conversation from DB."""
    from sqlalchemy import func, select

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(func.max(AgentExecutionEvent.sequence_number)).where(
                    AgentExecutionEvent.conversation_id == conversation_id
                )
            )
            last_seq = result.scalar()
            return last_seq if last_seq is not None else 0
    except Exception as e:
        logger.warning(f"[ActorExecution] Failed to get last DB sequence: {e}")
        return 0


async def _persist_events(
    conversation_id: str,
    message_id: str,
    events: List[Dict[str, Any]],
    correlation_id: Optional[str] = None,
) -> int:
    """Persist agent events to database."""
    from sqlalchemy.dialects.postgresql import insert

    SKIP_EVENT_TYPES = {
        "thought_delta",
        "text_delta",
        "text_start",
        "text_end",
    }

    sequence_number = 0

    async with async_session_factory() as session:
        async with session.begin():
            for idx, event in enumerate(events):
                event_type = event.get("type", "unknown")
                event_data = event.get("data", {})
                sequence_number = event.get("seq", idx + 1)

                if event_type in SKIP_EVENT_TYPES:
                    continue

                if event_type == "complete":
                    content = event_data.get("content", "")
                    if content:
                        event_type = "assistant_message"
                        event_data = {
                            "content": content,
                            "message_id": str(uuid.uuid4()),
                            "role": "assistant",
                        }
                        if event.get("data", {}).get("artifacts"):
                            event_data["artifacts"] = event["data"]["artifacts"]
                    else:
                        continue

                stmt = (
                    insert(AgentExecutionEvent)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type=event_type,
                        event_data=event_data,
                        sequence_number=sequence_number,
                        correlation_id=correlation_id,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
                )
                await session.execute(stmt)

    return sequence_number


async def _publish_error_event(
    conversation_id: str,
    message_id: str,
    error_message: str,
    correlation_id: Optional[str] = None,
) -> None:
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url)
    stream_key = f"agent:events:{conversation_id}"

    error_event = {
        "type": "error",
        "seq": 0,
        "data": {
            "message": error_message,
            "message_id": message_id,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "message_id": message_id,
    }
    if correlation_id:
        error_event["correlation_id"] = correlation_id

    await redis_client.xadd(stream_key, {"data": json.dumps(error_event)}, maxlen=1000)
    await redis_client.close()


async def _publish_event_to_stream(
    conversation_id: str,
    event: Dict[str, Any],
    message_id: str,
    sequence_number: int,
    correlation_id: Optional[str] = None,
    redis_client: Optional[aioredis.Redis] = None,
) -> None:
    event_type = event.get("type", "unknown")
    event_data = event.get("data", {})

    if event_type == "text_delta" and isinstance(event_data, str):
        event_data_with_meta = {"content": event_data, "message_id": message_id}
    else:
        event_data_with_meta = {**event_data, "message_id": message_id}

    stream_event_payload = {
        "type": event_type,
        "seq": sequence_number,
        "data": event_data_with_meta,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": conversation_id,
        "message_id": message_id,
    }
    if correlation_id:
        stream_event_payload["correlation_id"] = correlation_id

    redis_message = {"data": json.dumps(stream_event_payload)}

    if redis_client is None:
        redis_client = await _get_redis_client()

    try:
        stream_key = f"agent:events:{conversation_id}"
        await redis_client.xadd(stream_key, redis_message, maxlen=1000)
    except Exception as e:
        logger.warning(f"[ActorExecution] Failed to publish event to Redis: {e}")


async def _get_redis_client() -> aioredis.Redis:
    return await get_redis_client()


def _format_hitl_response_as_tool_result(
    hitl_type: str,
    response_data: Dict[str, Any],
) -> str:
    """Format HITL response data as a tool result content string."""
    if response_data.get("cancelled") or response_data.get("timeout"):
        return f"User did not complete {hitl_type} request"

    if hitl_type == "clarification":
        selected = (
            response_data.get("selected_option_id")
            or response_data.get("selected_options")
            or response_data.get("answer")
        )
        custom = response_data.get("custom_input") or response_data.get("answer")
        if custom:
            return f"User clarification: {custom}"
        if selected:
            if isinstance(selected, list):
                return f"User selected options: {', '.join(selected)}"
            return f"User selected: {selected}"
        return "User provided clarification (no specific selection)"

    if hitl_type == "decision":
        selected = response_data.get("selected_option_id") or response_data.get("decision")
        custom = response_data.get("custom_input") or response_data.get("decision")
        if custom:
            return f"User decision (custom): {custom}"
        if selected:
            return f"User chose: {selected}"
        return "User made a decision (no specific selection)"

    if hitl_type == "env_var":
        values = response_data.get("values", {})
        provided_vars = list(values.keys()) if values else []
        if provided_vars:
            return f"User provided environment variables: {', '.join(provided_vars)}"
        return "User provided environment variable values"

    if hitl_type == "permission":
        granted = response_data.get("granted")
        if granted is None:
            granted = response_data.get("action") == "allow"
        scope = response_data.get("scope", "once")
        if granted:
            return f"User granted permission (scope: {scope})"
        return "User denied permission"

    return f"User responded to {hitl_type} request"
