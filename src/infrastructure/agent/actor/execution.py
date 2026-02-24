"""Execution helpers for Actor-based project agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import time as time_module
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.model.agent.hitl.hitl_types import HITLPendingException

import redis.asyncio as aioredis

from src.configuration.config import get_settings
from src.domain.model.agent.execution.event_time import EventTimeGenerator
from src.infrastructure.adapters.primary.web.metrics import agent_metrics
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent
from src.infrastructure.agent.actor.state.running_state import (
    clear_agent_running,
    refresh_agent_running_ttl,
    set_agent_running,
)
from src.infrastructure.agent.actor.state.snapshot_repo import (
    delete_hitl_snapshot,
    load_hitl_snapshot,
    save_hitl_snapshot,
)
from src.infrastructure.agent.actor.types import ProjectChatRequest, ProjectChatResult
from src.infrastructure.agent.core.project_react_agent import ProjectReActAgent
from src.infrastructure.agent.hitl.state_store import HITLAgentState, HITLStateStore
from src.infrastructure.agent.state.agent_worker_state import get_redis_client

logger = logging.getLogger(__name__)

# Flush accumulated events to DB every N seconds during streaming,
# so they survive service restarts.
_PERSIST_INTERVAL_SECONDS = 30


def _inject_app_model_context(
    conversation_context: list[dict[str, Any]],
    app_model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Inject MCP App model context as a system message (SEP-1865).

    If the frontend received a ui/update-model-context from an MCP App,
    the context is serialized and prepended as a system message so the
    LLM is aware of the app's state in the next turn.
    """
    if not app_model_context:
        return conversation_context
    context_msg = {
        "role": "system",
        "content": (
            "[MCP App Context]\n"
            "The following context was provided by an active MCP App UI. "
            "Use it to inform your response.\n"
            f"{json.dumps(app_model_context, ensure_ascii=False)}"
        ),
    }
    return [context_msg, *conversation_context]


async def execute_project_chat(
    agent: ProjectReActAgent,
    request: ProjectChatRequest,
    abort_signal: asyncio.Event | None = None,
) -> ProjectChatResult:
    """Execute a chat request and publish events to Redis/DB."""
    start_time = time_module.time()
    events: list[dict[str, Any]] = []
    final_content = ""
    is_error = False
    error_message = None
    summary_save_data: dict[str, Any] | None = None

    await set_agent_running(request.conversation_id, request.message_id)

    # Initialize EventTimeGenerator from last DB event time to avoid collisions
    last_time_us, last_counter = await _get_last_db_event_time(request.conversation_id)
    time_gen = EventTimeGenerator(last_time_us, last_counter)

    try:
        redis_client = await _get_redis_client()
        last_refresh = time_module.time()
        last_persist = time_module.time()
        persisted_count = 0

        async for event in agent.execute_chat(
            conversation_id=request.conversation_id,
            user_message=request.user_message,
            user_id=request.user_id,
            conversation_context=_inject_app_model_context(
                request.conversation_context, request.app_model_context
            ),
            tenant_id=agent.config.tenant_id,
            message_id=request.message_id,
            abort_signal=abort_signal,
            file_metadata=request.file_metadata,
            forced_skill_name=request.forced_skill_name,
            context_summary_data=request.context_summary_data,
            plan_mode=request.plan_mode,
        ):
            evt_time_us, evt_counter = time_gen.next()
            event["event_time_us"] = evt_time_us
            event["event_counter"] = evt_counter
            events.append(event)

            await _publish_event_to_stream(
                conversation_id=request.conversation_id,
                event=event,
                message_id=request.message_id,
                event_time_us=evt_time_us,
                event_counter=evt_counter,
                correlation_id=request.correlation_id,
                redis_client=redis_client,
            )

            event_type = event.get("type")
            if event_type == "complete":
                final_content = event.get("data", {}).get("content", "")
            elif event_type == "error":
                is_error = True
                error_message = event.get("data", {}).get("message", "Unknown error")
            elif event_type == "context_summary_generated":
                summary_save_data = event.get("data")
            elif event_type == "mcp_app_result":
                # Persist agent-generated HTML to DB so page refreshes can load it (D2 fix)
                event_data = event.get("data", {})
                _app_id = event_data.get("app_id")
                _resource_html = event_data.get("resource_html", "")
                _resource_uri = event_data.get("resource_uri", "")
                if _app_id and _resource_html:
                    asyncio.create_task(
                        _save_mcp_app_html(_app_id, _resource_uri, _resource_html)
                    )

            now = time_module.time()
            if now - last_refresh > 60:
                await refresh_agent_running_ttl(request.conversation_id)
                last_refresh = now

            # Incremental persistence: flush to DB periodically so events
            # survive service restarts mid-stream.
            if now - last_persist > _PERSIST_INTERVAL_SECONDS:
                batch = events[persisted_count:]
                if batch:
                    await _persist_events(
                        conversation_id=request.conversation_id,
                        message_id=request.message_id,
                        events=batch,
                        correlation_id=request.correlation_id,
                    )
                    persisted_count = len(events)
                last_persist = now

        # Final flush for any remaining events
        remaining = events[persisted_count:]
        if remaining:
            await _persist_events(
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                events=remaining,
                correlation_id=request.correlation_id,
            )

        # Save context summary if compression generated one
        if summary_save_data and not is_error:
            await _save_context_summary(
                conversation_id=request.conversation_id,
                summary_data=summary_save_data,
                last_event_time_us=time_gen.last_time_us,
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
            last_event_time_us=time_gen.last_time_us,
            last_event_counter=time_gen.last_counter,
            is_error=is_error,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            event_count=len(events),
        )

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        agent_metrics.increment("project_agent.chat_errors")
        logger.error(f"[ActorExecution] Chat error: {e}", exc_info=True)

        # Persist events collected before the error so they survive restarts
        remaining = events[persisted_count:] if events else []
        if remaining:
            try:
                await _persist_events(
                    conversation_id=request.conversation_id,
                    message_id=request.message_id,
                    events=remaining,
                    correlation_id=request.correlation_id,
                )
            except Exception as persist_err:
                logger.warning(f"[ActorExecution] Failed to persist events on error: {persist_err}")

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
            last_event_time_us=0,
            last_event_counter=0,
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
    last_event_time_us: int = 0,
    last_event_counter: int = 0,
) -> ProjectChatResult:
    """Persist HITL state to Redis and Postgres and return pending result.

    NOTE: This is kept for backward compatibility with Temporal activities.
    The primary HITL flow now uses HITLCoordinator with Future-based pausing.
    hitl_exception is expected to be a HITLPendingException instance.
    """
    redis_client = await _get_redis_client()
    state_store = HITLStateStore(redis_client)

    saved_messages = hitl_exception.current_messages or request.conversation_context

    logger.info(
        f"[ActorExecution] Handling HITL pending: request_id={hitl_exception.request_id}, "
        f"type={hitl_exception.hitl_type.value}, "
        f"messages_count={len(saved_messages)}, "
        f"last_event_time_us={last_event_time_us}, last_event_counter={last_event_counter}"
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
        last_event_time_us=last_event_time_us,
        last_event_counter=last_event_counter,
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
        last_event_time_us=last_event_time_us,
        last_event_counter=last_event_counter,
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
    response_data: dict[str, Any],
) -> ProjectChatResult:
    """Resume an HITL-paused chat using stored state."""
    start_time = time_module.time()
    events: list[dict[str, Any]] = []
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
        logger.error(f"[ActorExecution] HITL state not found for request_id={request_id}")
        return ProjectChatResult(
            conversation_id="",
            message_id="",
            content="",
            last_event_time_us=0,
            last_event_counter=0,
            is_error=True,
            error_message="HITL state not found or expired",
            execution_time_ms=(time_module.time() - start_time) * 1000,
            event_count=0,
        )

    logger.info(
        f"[ActorExecution] Loaded HITL state: conversation_id={state.conversation_id}, "
        f"hitl_type={state.hitl_type}, messages_count={len(state.messages)}, "
        f"last_event_time_us={state.last_event_time_us}, "
        f"last_event_counter={state.last_event_counter}"
    )

    # Use the greater of HITL state event time and actual DB event time
    # to avoid collisions with events saved by other paths
    db_last_time_us, db_last_counter = await _get_last_db_event_time(state.conversation_id)
    if db_last_time_us > state.last_event_time_us or (
        db_last_time_us == state.last_event_time_us and db_last_counter > state.last_event_counter
    ):
        init_time_us, init_counter = db_last_time_us, db_last_counter
    else:
        init_time_us, init_counter = state.last_event_time_us, state.last_event_counter
    time_gen = EventTimeGenerator(init_time_us, init_counter)
    await set_agent_running(state.conversation_id, state.message_id)

    try:
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
        last_persist = time_module.time()
        persisted_count = 0

        async for event in agent.execute_chat(
            conversation_id=state.conversation_id,
            user_message=state.user_message,
            user_id=state.user_id,
            conversation_context=conversation_context,
            tenant_id=state.tenant_id,
            message_id=state.message_id,
        ):
            evt_time_us, evt_counter = time_gen.next()
            event["event_time_us"] = evt_time_us
            event["event_counter"] = evt_counter
            events.append(event)

            await _publish_event_to_stream(
                conversation_id=state.conversation_id,
                event=event,
                message_id=state.message_id,
                event_time_us=evt_time_us,
                event_counter=evt_counter,
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

            if now - last_persist > _PERSIST_INTERVAL_SECONDS:
                batch = events[persisted_count:]
                if batch:
                    await _persist_events(
                        conversation_id=state.conversation_id,
                        message_id=state.message_id,
                        events=batch,
                        correlation_id=state.correlation_id,
                    )
                    persisted_count = len(events)
                last_persist = now

        remaining = events[persisted_count:]
        if remaining:
            await _persist_events(
                conversation_id=state.conversation_id,
                message_id=state.message_id,
                events=remaining,
                correlation_id=state.correlation_id,
            )

        execution_time_ms = (time_module.time() - start_time) * 1000

        return ProjectChatResult(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            content=final_content,
            last_event_time_us=time_gen.last_time_us,
            last_event_counter=time_gen.last_counter,
            is_error=is_error,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
            event_count=len(events),
        )

    except Exception as e:
        execution_time_ms = (time_module.time() - start_time) * 1000
        logger.error(f"[ActorExecution] Continue chat error: {e}", exc_info=True)

        remaining = events[persisted_count:] if events else []
        if remaining:
            try:
                await _persist_events(
                    conversation_id=state.conversation_id,
                    message_id=state.message_id,
                    events=remaining,
                    correlation_id=state.correlation_id,
                )
            except Exception as persist_err:
                logger.warning(f"[ActorExecution] Failed to persist events on error: {persist_err}")

        return ProjectChatResult(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            content="",
            last_event_time_us=0,
            last_event_counter=0,
            is_error=True,
            error_message=str(e),
            execution_time_ms=execution_time_ms,
            event_count=0,
        )
    finally:
        await clear_agent_running(state.conversation_id)


async def _get_last_db_event_time(conversation_id: str) -> tuple[int, int]:
    """Get the last (event_time_us, event_counter) for a conversation from DB."""
    from sqlalchemy import select

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(
                    AgentExecutionEvent.event_time_us,
                    AgentExecutionEvent.event_counter,
                )
                .where(AgentExecutionEvent.conversation_id == conversation_id)
                .order_by(
                    AgentExecutionEvent.event_time_us.desc(),
                    AgentExecutionEvent.event_counter.desc(),
                )
                .limit(1)
            )
            row = result.one_or_none()
            if row is None:
                return (0, 0)
            return (row[0], row[1])
    except Exception as e:
        logger.warning(f"[ActorExecution] Failed to get last DB event time: {e}")
        return (0, 0)


async def _persist_events(
    conversation_id: str,
    message_id: str,
    events: list[dict[str, Any]],
    correlation_id: str | None = None,
) -> None:
    """Persist agent events to database."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    SKIP_EVENT_TYPES = {
        "thought_delta",
        "text_delta",
        "text_start",
    }

    try:
        has_text_end_messages = False
        async with async_session_factory() as session, session.begin():
            existing_assistant_result = await session.execute(
                select(AgentExecutionEvent.event_data)
                .where(
                    AgentExecutionEvent.conversation_id == conversation_id,
                    AgentExecutionEvent.message_id == message_id,
                    AgentExecutionEvent.event_type == "assistant_message",
                )
            )
            has_complete_assistant_message = any(
                isinstance(existing_event_data, dict)
                and existing_event_data.get("source") == "complete"
                for existing_event_data in existing_assistant_result.scalars().all()
            )

            for event in events:
                event_type = event.get("type", "unknown")
                event_data = event.get("data", {})
                evt_time_us = event.get("event_time_us", 0)
                evt_counter = event.get("event_counter", 0)

                if event_type in SKIP_EVENT_TYPES:
                    continue

                # Persist text_end as assistant_message so intermediate
                # text between tool calls survives in history.
                if event_type == "text_end":
                    full_text = event_data.get("full_text", "")
                    if full_text and full_text.strip():
                        event_type = "assistant_message"
                        event_data = {
                            "content": full_text,
                            "message_id": str(uuid.uuid4()),
                            "role": "assistant",
                            "source": "text_end",
                        }
                        has_text_end_messages = True
                    else:
                        continue

                if event_type == "complete":
                    # Skip if text_end events already cover the text content
                    if has_text_end_messages or has_complete_assistant_message:
                        continue
                    content = event_data.get("content", "")
                    if content:
                        event_type = "assistant_message"
                        event_data = {
                            "content": content,
                            "message_id": str(uuid.uuid4()),
                            "role": "assistant",
                            "source": "complete",
                        }
                        if event.get("data", {}).get("artifacts"):
                            event_data["artifacts"] = event["data"]["artifacts"]
                        has_complete_assistant_message = True
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
                        event_time_us=evt_time_us,
                        event_counter=evt_counter,
                        correlation_id=correlation_id,
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["conversation_id", "event_time_us", "event_counter"]
                    )
                )
                await session.execute(stmt)
    except Exception as e:
        logger.error(
            f"[ActorExecution] Failed to persist {len(events)} events "
            f"for conversation {conversation_id}: {e}",
            exc_info=True,
        )


async def _save_context_summary(
    conversation_id: str,
    summary_data: dict[str, Any],
    last_event_time_us: int,
) -> None:
    """Save context summary to conversation metadata."""
    try:
        from src.domain.model.agent.conversation.context_summary import ContextSummary
        from src.infrastructure.adapters.secondary.persistence.sql_context_summary_adapter import (
            SqlContextSummaryAdapter,
        )

        summary = ContextSummary(
            summary_text=summary_data.get("summary_text", ""),
            summary_tokens=summary_data.get("summary_tokens", 0),
            messages_covered_up_to=last_event_time_us,
            messages_covered_count=summary_data.get("messages_covered_count", 0),
            compression_level=summary_data.get("compression_level", "summarize"),
        )

        async with async_session_factory() as session, session.begin():
            adapter = SqlContextSummaryAdapter(session)
            await adapter.save_summary(conversation_id, summary)

        logger.info(
            f"[ActorExecution] Saved context summary for {conversation_id}: "
            f"{summary.messages_covered_count} messages covered"
        )
    except Exception as e:
        logger.warning(
            f"[ActorExecution] Failed to save context summary for {conversation_id}: {e}"
        )


async def _publish_error_event(
    conversation_id: str,
    message_id: str,
    error_message: str,
    correlation_id: str | None = None,
) -> None:
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url)
    stream_key = f"agent:events:{conversation_id}"

    now = datetime.now(UTC)
    now_us = int(now.timestamp() * 1_000_000)

    error_event = {
        "type": "error",
        "event_time_us": now_us,
        "event_counter": 0,
        "data": {
            "message": error_message,
            "message_id": message_id,
        },
        "timestamp": now.isoformat(),
        "conversation_id": conversation_id,
        "message_id": message_id,
    }
    if correlation_id:
        error_event["correlation_id"] = correlation_id

    await redis_client.xadd(stream_key, {"data": json.dumps(error_event)}, maxlen=1000)
    await redis_client.close()


async def _publish_event_to_stream(
    conversation_id: str,
    event: dict[str, Any],
    message_id: str,
    event_time_us: int,
    event_counter: int,
    correlation_id: str | None = None,
    redis_client: aioredis.Redis | None = None,
) -> None:
    event_type = event.get("type", "unknown")
    event_data = event.get("data", {})

    if event_type == "text_delta" and isinstance(event_data, str):
        event_data_with_meta = {"content": event_data, "message_id": message_id}
    else:
        event_data_with_meta = {**event_data, "message_id": message_id}

    stream_event_payload = {
        "type": event_type,
        "event_time_us": event_time_us,
        "event_counter": event_counter,
        "data": event_data_with_meta,
        "timestamp": datetime.now(UTC).isoformat(),
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
        if event_type in ("task_list_updated", "task_updated"):
            task_count = len(event_data.get("tasks", []))
            logger.info(
                f"[ActorExecution] Published {event_type} to Redis: "
                f"conversation={conversation_id}, tasks={task_count}"
            )
    except Exception as e:
        logger.warning(f"[ActorExecution] Failed to publish event to Redis: {e}")


async def _get_redis_client() -> aioredis.Redis:
    return await get_redis_client()


def _format_hitl_response_as_tool_result(
    hitl_type: str,
    response_data: dict[str, Any],
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


async def _save_mcp_app_html(app_id: str, resource_uri: str, html_content: str) -> None:
    """Persist agent-generated MCPApp HTML to the database (D2 fix).

    Called as a fire-and-forget background task when the agent emits a
    `mcp_app_result` event with non-empty `resource_html`. Persisting the
    HTML ensures the app can be loaded after page refreshes without requiring
    a live sandbox round-trip.

    Args:
        app_id: MCPApp ID to update.
        resource_uri: The ui:// URI of the resource.
        html_content: HTML content to persist.
    """
    try:
        from src.domain.model.mcp.app import MCPAppResource
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
            SqlMCPAppRepository,
        )

        async with async_session_factory() as session:
            repo = SqlMCPAppRepository(session)
            app = await repo.find_by_id(app_id)
            if not app:
                logger.warning("[ActorExecution] MCPApp not found for html persist: %s", app_id)
                return
            resource = MCPAppResource(
                uri=resource_uri,
                html_content=html_content,
                size_bytes=len(html_content.encode("utf-8")),
            )
            app.mark_ready(resource)
            await repo.save(app)
            await session.commit()
            logger.info(
                "[ActorExecution] Persisted MCPApp html: app_id=%s, size=%d bytes",
                app_id,
                resource.size_bytes,
            )
    except Exception as e:
        logger.warning("[ActorExecution] Failed to persist MCPApp html: %s", e)
