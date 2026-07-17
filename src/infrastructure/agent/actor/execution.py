"""Execution helpers for Actor-based project agent runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import time as time_module
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.application.services.automation_runtime_projection_service import (
        AutomationRuntimeIdentity,
    )
    from src.domain.model.agent.hitl.hitl_types import HITLPendingException

import redis.asyncio as aioredis

from src.domain.model.agent.execution.event_time import EventTimeGenerator
from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.ports.services.agent_message_bus_port import AgentMessageType
from src.infrastructure.adapters.primary.web.metrics import agent_metrics
from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
    RedisAgentMessageBusAdapter,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    _sanitize_event_data_for_postgres,
    apply_conversation_event_projection_delta,
)
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
from src.infrastructure.agent.events.converter import normalize_event_dict
from src.infrastructure.agent.hitl.state_store import HITLAgentState, HITLStateStore
from src.infrastructure.agent.state.agent_worker_state import get_redis_client
from src.infrastructure.agent.subagent.announce_service import AnnounceService

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[Any]] = set()


async def _run_session_lifecycle(project_id: str) -> None:
    """Fire-and-forget: run session lifecycle maintenance."""
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_message_repository import (
            SqlMessageRepository,
        )
        from src.infrastructure.agent.session.lifecycle import (
            SessionLifecycleManager,
        )

        async with async_session_factory() as session:
            conversation_repo = SqlConversationRepository(session)
            message_repo = SqlMessageRepository(session)
            manager = SessionLifecycleManager(
                conversation_repo=conversation_repo,
                message_repo=message_repo,
            )
            result = await manager.run_lifecycle(project_id)
            await session.commit()
            logger.info(
                "[Lifecycle] project=%s trimmed=%d archived=%d gc=%d",
                project_id,
                sum(t.messages_before - t.messages_after for t in result.trim_results),
                result.archive_result.archived_count if result.archive_result else 0,
                result.gc_result.deleted_count if result.gc_result else 0,
            )
    except Exception:
        logger.exception(
            "[Lifecycle] Failed for project=%s",
            project_id,
        )


async def _update_spawn_status(
    *,
    child_session_id: str,
    status: str,
    parent_session_id: str,
) -> None:
    """Best-effort mirror of spawned child execution status to the orchestrator."""
    try:
        from src.infrastructure.agent.state.agent_worker_state import get_agent_orchestrator

        orchestrator = get_agent_orchestrator()
        if orchestrator is None:
            return
        await orchestrator.update_spawn_status(
            child_session_id=child_session_id,
            new_status=status,
            conversation_id=parent_session_id,
        )
    except Exception:
        logger.warning(
            "Failed to update spawn status: child_session=%s status=%s parent_session=%s",
            child_session_id,
            status,
            parent_session_id,
            exc_info=True,
        )


async def _resolve_child_terminal_status(
    *,
    child_session_id: str,
    success: bool,
) -> str | None:
    """Resolve the spawn status to mirror after a child turn finishes."""
    default_status = "completed" if success else "failed"
    try:
        from src.infrastructure.agent.state.agent_worker_state import get_agent_orchestrator

        orchestrator = get_agent_orchestrator()
        if orchestrator is None:
            return default_status
        record = await orchestrator.get_spawn_record(child_session_id)
        if record is None or record.mode != SpawnMode.SESSION:
            return default_status
        if record.status in {"stopped", "cancelled"}:
            return None
        return "running"
    except Exception:
        logger.warning(
            "Failed to resolve child terminal spawn status: child_session=%s",
            child_session_id,
            exc_info=True,
        )
        return default_status


async def _resolve_chat_runtime_overrides(
    request: ProjectChatRequest,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve persisted and app-provided LLM overrides for a chat request."""
    llm_overrides: dict[str, Any] | None = None
    model_override: str | None = None

    if _is_workspace_runtime_context(request.app_model_context):
        logger.info(
            "[ActorExecution] Ignoring conversation LLM overrides for workspace runtime "
            "conversation %s so the selected agent definition remains authoritative",
            request.conversation_id,
        )
        return None, None

    persisted_config = await _load_persisted_agent_config(request.conversation_id)
    if persisted_config:
        raw_persisted_model = persisted_config.get("llm_model_override")
        if isinstance(raw_persisted_model, str) and raw_persisted_model.strip():
            model_override = raw_persisted_model.strip()
        raw_persisted_llm = persisted_config.get("llm_overrides")
        if isinstance(raw_persisted_llm, dict):
            llm_overrides = raw_persisted_llm

    if request.app_model_context:
        raw_llm_overrides = request.app_model_context.get("llm_overrides")
        if isinstance(raw_llm_overrides, dict):
            llm_overrides = raw_llm_overrides
        raw_model_override = request.app_model_context.get("llm_model_override")
        if isinstance(raw_model_override, str) and raw_model_override.strip():
            model_override = raw_model_override.strip()

    # Normalize the "auto" sentinel so downstream pooled clients can
    # dispatch case-insensitively regardless of UI / persisted casing.
    if isinstance(model_override, str) and model_override.lower() == "auto":
        model_override = "auto"

    return llm_overrides, model_override


def _is_workspace_runtime_context(app_model_context: dict[str, Any] | None) -> bool:
    """Return True when this turn is governed by workspace agent configuration."""
    if not isinstance(app_model_context, dict):
        return False
    if app_model_context.get("context_type") == "workspace_worker_runtime":
        return True
    workspace_binding = app_model_context.get("workspace_binding")
    return isinstance(workspace_binding, dict) and bool(workspace_binding.get("workspace_id"))


# Flush accumulated events to DB every N seconds during streaming,
# so they survive service restarts.
_PERSIST_INTERVAL_SECONDS = 30

# TTL refresh interval for agent running state (seconds).
_TTL_REFRESH_INTERVAL_SECONDS = 60

_SKIP_PERSIST_EVENT_TYPES = {
    "thought_start",
    "thought_delta",
    "text_delta",
    "text_start",
}
_MESSAGE_EVENT_TYPES = {"user_message", "assistant_message"}
_HITL_REQUEST_EVENT_TYPES = frozenset(
    {
        "clarification_asked",
        "decision_asked",
        "env_var_requested",
        "permission_asked",
    }
)
_TERMINAL_WORKSPACE_STATUS_MESSAGES = {
    "goal_achieved:workspace_contract_submitted": "Workspace contract submitted.",
    "goal_achieved:workspace_terminal_report": "Workspace terminal report submitted.",
}


# ---------------------------------------------------------------------------
# Shared dataclass / helpers used by both execute_ and continue_ flows
# ---------------------------------------------------------------------------


@dataclass
class _EventSideEffects:
    """Side effects extracted from a single streaming event."""

    final_content: str | None = None
    is_error: bool = False
    error_message: str | None = None
    summary_data: dict[str, Any] | None = None
    should_flush_events: bool = False


@dataclass
class _StreamState:
    """Mutable accumulator for the streaming event loop."""

    events: list[dict[str, Any]] = field(default_factory=list)
    final_content: str = ""
    is_error: bool = False
    error_message: str | None = None
    summary_save_data: dict[str, Any] | None = None
    persisted_count: int = 0
    last_refresh: float = 0.0
    last_persist: float = 0.0

    def apply_side_effects(self, side: _EventSideEffects) -> None:
        """Merge side effects from a single event into the accumulator."""
        if side.final_content is not None:
            self.final_content = side.final_content
        if side.is_error:
            self.is_error = True
            self.error_message = side.error_message
        if side.summary_data is not None:
            self.summary_save_data = side.summary_data


@dataclass(frozen=True)
class _PersistableEvent:
    """Normalized event payload ready for database persistence."""

    event_type: str
    event_data: dict[str, Any]
    event_time_us: int
    event_counter: int


def _sanitize_persistable_event(event: _PersistableEvent | None) -> _PersistableEvent | None:
    """Redact sensitive payload values before stream events leave actor memory."""
    if event is None:
        return None
    return _PersistableEvent(
        event_type=event.event_type,
        event_data=dict(_sanitize_event_data_for_postgres(event.event_data)),
        event_time_us=event.event_time_us,
        event_counter=event.event_counter,
    )


def _terminal_workspace_status_event(
    event_data: dict[str, Any],
    *,
    event_time_us: int,
    event_counter: int,
    has_assistant_message: bool,
) -> tuple[_PersistableEvent | None, bool]:
    """Build a visible history item for terminal workspace status events."""
    status = str(event_data.get("status", ""))
    content = _TERMINAL_WORKSPACE_STATUS_MESSAGES.get(status)
    if not content or has_assistant_message:
        return None, False
    return (
        _PersistableEvent(
            event_type="assistant_message",
            event_data={
                "content": content,
                "message_id": str(uuid.uuid4()),
                "role": "assistant",
                "source": "terminal_workspace_status",
                "status": status,
            },
            event_time_us=event_time_us,
            event_counter=event_counter,
        ),
        True,
    )


def _complete_event_for_persistence(
    raw_event_data: dict[str, Any],
    event_data: dict[str, Any],
    *,
    event_time_us: int,
    event_counter: int,
    has_text_end_messages: bool,
    has_complete_assistant_message: bool,
) -> tuple[_PersistableEvent | None, bool]:
    """Build persistence payload for complete events."""
    if not (has_text_end_messages or has_complete_assistant_message):
        content = str(event_data.get("content", "")).strip()
        has_completion_metadata = any(
            raw_event_data.get(field) for field in ("artifacts", "trace_url", "execution_summary")
        )
        if not (content or has_completion_metadata):
            return None, False
        complete_event_data: dict[str, Any] = {
            "content": content,
            "message_id": str(uuid.uuid4()),
            "role": "assistant",
            "source": "complete",
        }
        if raw_event_data.get("artifacts"):
            complete_event_data["artifacts"] = raw_event_data["artifacts"]
        if raw_event_data.get("trace_url"):
            complete_event_data["trace_url"] = raw_event_data["trace_url"]
        if raw_event_data.get("execution_summary"):
            complete_event_data["execution_summary"] = raw_event_data["execution_summary"]
        return (
            _PersistableEvent(
                event_type="assistant_message",
                event_data=complete_event_data,
                event_time_us=event_time_us,
                event_counter=event_counter,
            ),
            True,
        )
    if has_text_end_messages:
        return (
            _PersistableEvent(
                event_type="complete",
                event_data=event_data,
                event_time_us=event_time_us,
                event_counter=event_counter,
            ),
            False,
        )
    return None, False


def _extract_event_side_effects(event: dict[str, Any]) -> _EventSideEffects:
    """Extract side-effect information from a streaming event.

    Also fires a background task when an ``mcp_app_result`` event
    carries HTML content that should be persisted.
    """
    side = _EventSideEffects()
    event_type = event.get("type")

    if event_type == "complete":
        side.final_content = event.get("data", {}).get("content", "")
    elif event_type == "error":
        side.is_error = True
        side.error_message = event.get("data", {}).get("message", "Unknown error")
    elif event_type == "status":
        status = event.get("data", {}).get("status")
        side.should_flush_events = status in _TERMINAL_WORKSPACE_STATUS_MESSAGES
    elif event_type == "context_summary_generated":
        side.summary_data = event.get("data")
    elif event_type == "mcp_app_result":
        _maybe_persist_mcp_app_html(event)

    return side


def _maybe_persist_mcp_app_html(event: dict[str, Any]) -> None:
    """Fire-and-forget background task to persist MCP App HTML (D2 fix)."""
    event_data = event.get("data", {})
    app_id = event_data.get("app_id")
    resource_html = event_data.get("resource_html", "")
    resource_uri = event_data.get("resource_uri", "")
    if app_id and resource_html:
        task = asyncio.create_task(_save_mcp_app_html(app_id, resource_uri, resource_html))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def _maybe_refresh_ttl(
    now: float,
    last_refresh: float,
    conversation_id: str,
) -> float:
    """Refresh agent-running TTL if sufficient time has elapsed.

    Returns the (possibly updated) ``last_refresh`` timestamp.
    """
    if now - last_refresh > _TTL_REFRESH_INTERVAL_SECONDS:
        await refresh_agent_running_ttl(conversation_id)
        return now
    return last_refresh


async def _maybe_incremental_persist(
    now: float,
    last_persist: float,
    events: list[dict[str, Any]],
    persisted_count: int,
    conversation_id: str,
    message_id: str,
    correlation_id: str | None,
) -> tuple[int, float]:
    """Persist events to DB if the persist interval has elapsed.

    Returns ``(new_persisted_count, new_last_persist)``.
    """
    if now - last_persist > _PERSIST_INTERVAL_SECONDS:
        batch = events[persisted_count:]
        if batch:
            await _persist_events(
                conversation_id=conversation_id,
                message_id=message_id,
                events=batch,
                correlation_id=correlation_id,
            )
            persisted_count = len(events)
        last_persist = now
    return persisted_count, last_persist


async def _flush_remaining_events(
    events: list[dict[str, Any]],
    persisted_count: int,
    conversation_id: str,
    message_id: str,
    correlation_id: str | None,
) -> None:
    """Persist any events not yet flushed to DB."""
    remaining = events[persisted_count:]
    if remaining:
        await _persist_events(
            conversation_id=conversation_id,
            message_id=message_id,
            events=remaining,
            correlation_id=correlation_id,
        )


async def _flush_if_requested(
    side_effects: _EventSideEffects,
    state: _StreamState,
    *,
    conversation_id: str,
    message_id: str,
    correlation_id: str | None,
    last_persist: float,
) -> None:
    """Persist terminal events immediately so cancellation cannot hide them."""
    if not side_effects.should_flush_events or state.persisted_count >= len(state.events):
        return
    await _flush_remaining_events(
        state.events,
        state.persisted_count,
        conversation_id,
        message_id,
        correlation_id,
    )
    state.persisted_count = len(state.events)
    state.last_persist = last_persist


def _record_chat_metrics(
    project_id: str,
    execution_time_ms: float,
    is_error: bool,
) -> None:
    """Record Prometheus-style metrics for a completed chat."""
    agent_metrics.increment(
        "project_agent.chat_total",
        labels={"project_id": project_id},
    )
    agent_metrics.observe(
        "project_agent.chat_latency_ms",
        execution_time_ms,
        labels={"project_id": project_id},
    )
    if is_error:
        agent_metrics.increment(
            "project_agent.chat_errors",
            labels={"project_id": project_id},
        )


def _automation_runtime_identity(
    *,
    tenant_id: str,
    project_id: str,
    conversation_id: str,
    message_id: str,
    automation_run_id: str | None,
) -> AutomationRuntimeIdentity | None:
    """Build trusted runtime correlation only when run ID and message ID agree."""
    if automation_run_id is None:
        return None
    if automation_run_id != message_id:
        logger.warning(
            "[AutomationRuntime] Ignoring mismatched run/message correlation: project=%s",
            project_id,
        )
        return None
    from src.application.services.automation_runtime_projection_service import (
        AutomationRuntimeIdentity,
    )

    return AutomationRuntimeIdentity(
        tenant_id=tenant_id,
        project_id=project_id,
        runtime_execution_id=automation_run_id,
        conversation_id=conversation_id,
    )


async def _project_automation_runtime_running(
    identity: AutomationRuntimeIdentity | None,
) -> None:
    """Best-effort CAS projection; unmatched ordinary chats are a no-op."""
    if identity is None:
        return
    try:
        from src.application.services.automation_runtime_projection_service import (
            AutomationRuntimeProjectionService,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_automation_runtime_projection_repository import (
            SqlAutomationRuntimeProjectionRepository,
        )

        async with async_session_factory() as session:
            service = AutomationRuntimeProjectionService(
                SqlAutomationRuntimeProjectionRepository(session)
            )
            _ = await service.mark_running(identity=identity, observed_at=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception(
            "[AutomationRuntime] Failed to project running state: runtime_execution_id=%s",
            identity.runtime_execution_id,
        )


async def _project_automation_runtime_waiting_human(
    identity: AutomationRuntimeIdentity | None,
) -> None:
    """Persist structured HITL waiting state without holding the Agent transaction."""
    if identity is None:
        return
    try:
        from src.application.services.automation_runtime_projection_service import (
            AutomationRuntimeProjectionService,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_automation_runtime_projection_repository import (
            SqlAutomationRuntimeProjectionRepository,
        )

        async with async_session_factory() as session:
            service = AutomationRuntimeProjectionService(
                SqlAutomationRuntimeProjectionRepository(session)
            )
            _ = await service.mark_waiting_human(identity=identity, observed_at=datetime.now(UTC))
            await session.commit()
    except Exception:
        logger.exception(
            "[AutomationRuntime] Failed to project HITL wait: runtime_execution_id=%s",
            identity.runtime_execution_id,
        )


async def _project_automation_runtime_terminal(
    identity: AutomationRuntimeIdentity | None,
    *,
    outcome: str,
    execution_time_ms: float,
    event_count: int,
) -> None:
    """Persist one closed terminal outcome and reconcile the delivery operation."""
    if identity is None:
        return
    try:
        from src.application.services.automation_runtime_projection_service import (
            AutomationRuntimeOutcome,
            AutomationRuntimeProjectionService,
            AutomationRuntimeTerminal,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_automation_runtime_projection_repository import (
            SqlAutomationRuntimeProjectionRepository,
        )

        terminal = AutomationRuntimeTerminal(
            outcome=AutomationRuntimeOutcome(outcome),
            observed_at=datetime.now(UTC),
            execution_time_ms=max(0.0, execution_time_ms),
            event_count=max(0, event_count),
        )
        async with async_session_factory() as session:
            service = AutomationRuntimeProjectionService(
                SqlAutomationRuntimeProjectionRepository(session)
            )
            projection = await service.project_terminal(identity=identity, terminal=terminal)
            await session.commit()
        if projection.delivery_ack_pending:
            logger.info(
                "[AutomationRuntime] Terminal run awaits delivery acknowledgement: runtime=%s",
                identity.runtime_execution_id,
            )
    except Exception:
        logger.exception(
            "[AutomationRuntime] Failed to project terminal state: runtime_execution_id=%s",
            identity.runtime_execution_id,
        )


async def _project_automation_stream_terminal(
    identity: AutomationRuntimeIdentity | None,
    *,
    outcome: str,
    state: _StreamState,
    start_time: float,
) -> None:
    await _project_automation_runtime_terminal(
        identity,
        outcome=outcome,
        execution_time_ms=(time_module.time() - start_time) * 1000,
        event_count=len(state.events),
    )


async def _handle_chat_error(
    error: Exception,
    events: list[dict[str, Any]],
    persisted_count: int,
    conversation_id: str,
    message_id: str,
    correlation_id: str | None,
    start_time: float,
    *,
    publish_error: bool = True,
    agent_id: str | None = None,
    parent_session_id: str | None = None,
) -> ProjectChatResult:
    """Handle an exception during chat execution.

    Persists remaining events, optionally publishes an error event to
    Redis, and returns an error ``ProjectChatResult``.
    """
    execution_time_ms = (time_module.time() - start_time) * 1000
    agent_metrics.increment("project_agent.chat_errors")
    logger.error(f"[ActorExecution] Chat error: {error}", exc_info=True)

    remaining = events[persisted_count:] if events else []
    if remaining:
        try:
            await _persist_events(
                conversation_id=conversation_id,
                message_id=message_id,
                events=remaining,
                correlation_id=correlation_id,
            )
        except Exception as persist_err:
            logger.warning(f"[ActorExecution] Failed to persist events on error: {persist_err}")

    if publish_error:
        try:
            await _publish_error_event(
                conversation_id=conversation_id,
                message_id=message_id,
                error_message=str(error),
                correlation_id=correlation_id,
            )
        except Exception as pub_error:
            logger.warning(f"[ActorExecution] Failed to publish error event: {pub_error}")

    if agent_id and parent_session_id:
        await _finalize_child_session_result(
            agent_id=agent_id,
            child_session_id=conversation_id,
            request_message_id=message_id,
            parent_session_id=parent_session_id,
            result_content="",
            success=False,
            event_count=len(events),
            execution_time_ms=execution_time_ms,
            error_message=str(error),
        )

    return ProjectChatResult(
        conversation_id=conversation_id,
        message_id=message_id,
        content="",
        last_event_time_us=0,
        last_event_counter=0,
        is_error=True,
        error_message=str(error),
        execution_time_ms=execution_time_ms,
        event_count=0,
    )


# ---------------------------------------------------------------------------
# Helpers specific to continue_project_chat
# ---------------------------------------------------------------------------


async def _load_hitl_state(
    state_store: HITLStateStore,
    request_id: str,
) -> HITLAgentState | None:
    """Load HITL state with retry, checking both Redis and snapshot."""
    state: HITLAgentState | None = None
    for attempt in range(10):
        state = await state_store.load_state_by_request(request_id)
        if not state:
            state = await load_hitl_snapshot(request_id)
        if state:
            break
        if attempt < 9:
            await asyncio.sleep(0.2)
    return state


def _hitl_state_not_found_result(start_time: float) -> ProjectChatResult:
    """Build an error result when HITL state cannot be found."""
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


def _init_continue_time_gen(
    state: HITLAgentState,
    db_event_time: tuple[int, int],
) -> EventTimeGenerator:
    """Create an EventTimeGenerator from the max of state and DB times."""
    db_time_us, db_counter = db_event_time
    if db_time_us > state.last_event_time_us or (
        db_time_us == state.last_event_time_us and db_counter > state.last_event_counter
    ):
        return EventTimeGenerator(db_time_us, db_counter)
    return EventTimeGenerator(state.last_event_time_us, state.last_event_counter)


def _coerce_event_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _build_hitl_context(
    state: HITLAgentState,
    response_data: object,
) -> list[dict[str, Any]]:
    """Build conversation context with HITL tool result appended."""
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
    return conversation_context


def _validate_hitl_resume_request(
    *,
    state: HITLAgentState,
    response_data: object,
    tenant_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    message_id: str | None,
) -> str | None:
    """Validate a resumed HITL response against the persisted request binding."""
    from src.domain.model.agent.hitl_types import HITLType
    from src.infrastructure.agent.hitl.coordinator import validate_hitl_response

    try:
        hitl_type = HITLType(state.hitl_type)
    except ValueError:
        return f"Unsupported HITL type: {state.hitl_type}"

    is_valid, validation_error = validate_hitl_response(
        hitl_type=hitl_type,
        request_data=state.hitl_request_data,
        response_data=response_data,
        conversation_id=state.conversation_id,
        tenant_id=state.tenant_id,
        project_id=state.project_id,
        message_id=state.message_id,
        received_tenant_id=tenant_id,
        received_project_id=project_id,
        received_conversation_id=conversation_id,
        received_message_id=message_id,
    )
    return None if is_valid else validation_error


# ---------------------------------------------------------------------------
# Public API entry points
# ---------------------------------------------------------------------------


def _inject_app_model_context(
    conversation_context: list[dict[str, Any]],
    app_model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Inject app-provided model context as a system message (SEP-1865).

    If the frontend received a ui/update-model-context from an MCP App,
    the context is serialized and prepended as a system message so the
    LLM is aware of the app's state in the next turn. Workspace worker
    launches also use this path for operational context that should not be
    persisted as a visible user task brief.
    """
    if not app_model_context:
        return conversation_context
    if app_model_context.get("context_type") == "workspace_worker_runtime":
        header = "".join(
            (
                "[Workspace Runtime Context]\n",
                "The following context is system-level workspace execution metadata. ",
                "Follow it as execution policy, do not quote or summarize it for the user, ",
                "and use native tool calls for tool use. Never print textual tool-call ",
                "markup such as [TOOL_CALL]...[/TOOL_CALL], JSON/function-call stubs, ",
                "shell command code blocks, <minimax:tool_call>, or <invoke name=...> ",
                "as a substitute for calling a tool.\n",
            )
        )
    else:
        header = "".join(
            (
                "[MCP App Context]\n",
                "The following context was provided by an active MCP App UI. ",
                "Use it to inform your response.\n",
            )
        )
    context_msg = {
        "role": "system",
        "content": f"{header}{json.dumps(app_model_context, ensure_ascii=False)}",
    }
    return [context_msg, *conversation_context]


def _inject_preferred_language_context(
    conversation_context: list[dict[str, Any]],
    preferred_language: str | None,
) -> list[dict[str, Any]]:
    """Prepend a `[Response Language]` system message when a preference is set.

    Delegates language normalization and directive rendering to the shared
    resolver in :mod:`src.infrastructure.agent.i18n` so workspace runtime,
    main ReAct loop, and future agent entry points stay aligned.
    """
    from src.infrastructure.agent.i18n import (
        directive_for,
        normalize_language,
        resolve_response_language,
    )

    if normalize_language(preferred_language) is None:
        return conversation_context

    language = resolve_response_language(runtime_override=preferred_language)
    return [
        {"role": "system", "content": directive_for(language)},
        *conversation_context,
    ]


async def _load_persisted_agent_config(conversation_id: str) -> dict[str, Any] | None:
    """Load persisted agent_config from the conversation record.

    Returns the config dict, or ``None`` when the conversation is not found or
    the config is empty.  Runs in its own short-lived DB session so it never
    interferes with the main request transaction.
    """
    try:
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )

        async with async_session_factory() as session:
            repo = SqlConversationRepository(session)
            conversation = await repo.find_by_id(conversation_id)
            if conversation and conversation.agent_config:
                return dict(conversation.agent_config)
    except Exception:
        logger.warning(
            "Failed to load persisted agent_config for conversation %s",
            conversation_id,
            exc_info=True,
        )
    return None


async def execute_project_chat(
    agent: ProjectReActAgent,
    request: ProjectChatRequest,
    abort_signal: asyncio.Event | None = None,
) -> ProjectChatResult:
    """Execute a chat request and publish events to Redis/DB."""
    start_time = time_module.time()
    ss = _StreamState(last_refresh=time_module.time(), last_persist=time_module.time())

    automation_identity = _automation_runtime_identity(
        tenant_id=agent.config.tenant_id,
        project_id=agent.config.project_id,
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        automation_run_id=request.automation_run_id,
    )

    await set_agent_running(request.conversation_id, request.message_id)
    await _project_automation_runtime_running(automation_identity)

    last_time_us, last_counter = await _get_last_db_event_time(request.conversation_id)
    time_gen = EventTimeGenerator(last_time_us, last_counter)
    llm_overrides, model_override = await _resolve_chat_runtime_overrides(request)

    try:
        redis_client = await _get_redis_client()
        pending_delta_events: list[tuple[dict[str, Any], int, int]] = []
        last_delta_flush = time_module.time()

        if request.agent_id and request.parent_session_id:
            await _update_spawn_status(
                child_session_id=request.conversation_id,
                status="running",
                parent_session_id=request.parent_session_id,
            )

        async for event in agent.execute_chat(
            conversation_id=request.conversation_id,
            user_message=request.user_message,
            user_id=request.user_id,
            conversation_context=_inject_preferred_language_context(
                _inject_app_model_context(request.conversation_context, request.app_model_context),
                request.preferred_language,
            ),
            tenant_id=agent.config.tenant_id,
            message_id=request.message_id,
            abort_signal=abort_signal,
            file_metadata=request.file_metadata,
            forced_skill_name=request.forced_skill_name,
            context_summary_data=request.context_summary_data,
            plan_mode=request.plan_mode,
            llm_overrides=llm_overrides,
            model_override=model_override,
            image_attachments=request.image_attachments,
            agent_id=request.agent_id,
            tenant_agent_config_data=request.tenant_agent_config,
            preferred_language=request.preferred_language,
            api_auth_token=request.api_auth_token,
        ):
            evt_time_us, evt_counter = time_gen.next()
            event["event_time_us"] = evt_time_us
            event["event_counter"] = evt_counter
            ss.events.append(event)

            last_delta_flush = await _stream_publish_event(
                event=event,
                event_time_us=evt_time_us,
                event_counter=evt_counter,
                pending_deltas=pending_delta_events,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                correlation_id=request.correlation_id,
                redis_client=redis_client,
                last_delta_flush=last_delta_flush,
            )

            side_effects = _extract_event_side_effects(event)
            ss.apply_side_effects(side_effects)
            if event.get("type") in _HITL_REQUEST_EVENT_TYPES:
                await _project_automation_runtime_waiting_human(automation_identity)

            now = time_module.time()
            ss.last_refresh = await _maybe_refresh_ttl(
                now,
                ss.last_refresh,
                request.conversation_id,
            )
            ss.persisted_count, ss.last_persist = await _maybe_incremental_persist(
                now,
                ss.last_persist,
                ss.events,
                ss.persisted_count,
                request.conversation_id,
                request.message_id,
                request.correlation_id,
            )
            await _flush_if_requested(
                side_effects,
                ss,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                correlation_id=request.correlation_id,
                last_persist=now,
            )

        await _flush_pending_delta_events(
            pending_delta_events,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            correlation_id=request.correlation_id,
            redis_client=redis_client,
        )
        await _flush_remaining_events(
            ss.events,
            ss.persisted_count,
            request.conversation_id,
            request.message_id,
            request.correlation_id,
        )

        if ss.summary_save_data and not ss.is_error:
            await _save_context_summary(
                conversation_id=request.conversation_id,
                summary_data=ss.summary_save_data,
                last_event_time_us=time_gen.last_time_us,
            )

        execution_time_ms = (time_module.time() - start_time) * 1000
        _record_chat_metrics(agent.config.project_id, execution_time_ms, ss.is_error)

        # Fire-and-forget: session lifecycle maintenance
        _task = asyncio.create_task(_run_session_lifecycle(agent.config.project_id))
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)

        if request.agent_id and request.parent_session_id:
            await _finalize_child_session_result(
                agent_id=request.agent_id,
                child_session_id=request.conversation_id,
                request_message_id=request.message_id,
                parent_session_id=request.parent_session_id,
                result_content=ss.final_content,
                success=not ss.is_error,
                event_count=len(ss.events),
                execution_time_ms=execution_time_ms,
                error_message=ss.error_message,
            )

        await _project_automation_stream_terminal(
            automation_identity,
            outcome="failed" if ss.is_error else "success",
            state=ss,
            start_time=start_time,
        )

        return ProjectChatResult(
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            content=ss.final_content,
            last_event_time_us=time_gen.last_time_us,
            last_event_counter=time_gen.last_counter,
            is_error=ss.is_error,
            error_message=ss.error_message,
            execution_time_ms=execution_time_ms,
            event_count=len(ss.events),
        )

    except asyncio.CancelledError:
        await _project_automation_stream_terminal(
            automation_identity,
            outcome="cancelled",
            state=ss,
            start_time=start_time,
        )
        raise
    except Exception as e:
        await _project_automation_stream_terminal(
            automation_identity,
            outcome="timeout" if isinstance(e, TimeoutError) else "failed",
            state=ss,
            start_time=start_time,
        )
        return await _handle_chat_error(
            e,
            ss.events,
            ss.persisted_count,
            request.conversation_id,
            request.message_id,
            request.correlation_id,
            start_time,
            agent_id=request.agent_id,
            parent_session_id=request.parent_session_id,
        )
    finally:
        await clear_agent_running(request.conversation_id, request.message_id)


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
        automation_run_id=request.automation_run_id,
        agent_id=request.agent_id,
        parent_session_id=request.parent_session_id,
        step_count=getattr(agent, "_step_count", 0),
        timeout_seconds=hitl_exception.timeout_seconds,
        pending_tool_call_id=hitl_exception.tool_call_id,
        last_event_time_us=last_event_time_us,
        last_event_counter=last_event_counter,
    )

    await state_store.save_state(state)
    await save_hitl_snapshot(state, agent.config.agent_mode)
    await _project_automation_runtime_waiting_human(
        _automation_runtime_identity(
            tenant_id=agent.config.tenant_id,
            project_id=agent.config.project_id,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            automation_run_id=request.automation_run_id,
        )
    )

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


async def continue_project_chat(  # noqa: PLR0915
    agent: ProjectReActAgent,
    request_id: str,
    response_data: object,
    *,
    lease_owner: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    message_id: str | None = None,
) -> ProjectChatResult:
    """Resume an HITL-paused chat using stored state."""
    start_time = time_module.time()
    ss = _StreamState(last_refresh=time_module.time(), last_persist=time_module.time())

    redis_client = await _get_redis_client()
    state_store = HITLStateStore(redis_client)

    logger.info(
        f"[ActorExecution] Continuing chat: request_id={request_id}, "
        f"response_keys={list(response_data.keys()) if isinstance(response_data, dict) else 'None'}"
    )

    state = await _load_hitl_state(state_store, request_id)
    if not state:
        logger.error(f"[ActorExecution] HITL state not found for request_id={request_id}")
        return _hitl_state_not_found_result(start_time)

    logger.info(
        f"[ActorExecution] Loaded HITL state: conversation_id={state.conversation_id}, "
        f"hitl_type={state.hitl_type}, messages_count={len(state.messages)}, "
        f"last_event_time_us={state.last_event_time_us}, "
        f"last_event_counter={state.last_event_counter}"
    )

    from src.infrastructure.agent.hitl.coordinator import mark_hitl_request_completed

    validation_error = _validate_hitl_resume_request(
        state=state,
        response_data=response_data,
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    if validation_error:
        logger.warning(
            "[ActorExecution] Rejected HITL response for request_id=%s: %s",
            request_id,
            validation_error,
        )
        execution_time_ms = (time_module.time() - start_time) * 1000
        return ProjectChatResult(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            is_error=True,
            error_message=validation_error,
            execution_time_ms=execution_time_ms,
        )

    db_event_time = await _get_last_db_event_time(state.conversation_id)
    time_gen = _init_continue_time_gen(state, db_event_time)
    automation_identity = _automation_runtime_identity(
        tenant_id=state.tenant_id,
        project_id=state.project_id,
        conversation_id=state.conversation_id,
        message_id=state.message_id,
        automation_run_id=state.automation_run_id,
    )
    await set_agent_running(state.conversation_id, state.message_id)
    await _project_automation_runtime_running(automation_identity)

    try:
        conversation_context = _build_hitl_context(state, response_data)

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
            ss.events.append(event)

            await _publish_event_to_stream(
                conversation_id=state.conversation_id,
                event=event,
                message_id=state.message_id,
                event_time_us=evt_time_us,
                event_counter=evt_counter,
                correlation_id=state.correlation_id,
                redis_client=redis_client,
            )

            side_effects = _extract_event_side_effects(event)
            ss.apply_side_effects(side_effects)
            if event.get("type") in _HITL_REQUEST_EVENT_TYPES:
                await _project_automation_runtime_waiting_human(automation_identity)

            now = time_module.time()
            ss.last_refresh = await _maybe_refresh_ttl(
                now,
                ss.last_refresh,
                state.conversation_id,
            )
            ss.persisted_count, ss.last_persist = await _maybe_incremental_persist(
                now,
                ss.last_persist,
                ss.events,
                ss.persisted_count,
                state.conversation_id,
                state.message_id,
                state.correlation_id,
            )
            await _flush_if_requested(
                side_effects,
                ss,
                conversation_id=state.conversation_id,
                message_id=state.message_id,
                correlation_id=state.correlation_id,
                last_persist=now,
            )

        await _flush_remaining_events(
            ss.events,
            ss.persisted_count,
            state.conversation_id,
            state.message_id,
            state.correlation_id,
        )

        if ss.summary_save_data and not ss.is_error:
            await _save_context_summary(
                conversation_id=state.conversation_id,
                summary_data=ss.summary_save_data,
                last_event_time_us=time_gen.last_time_us,
            )

        if not ss.is_error:
            completed = await mark_hitl_request_completed(request_id, lease_owner=lease_owner)
            if completed:
                await state_store.delete_state_by_request(request_id)
                await delete_hitl_snapshot(request_id)
            else:
                logger.warning(
                    "[ActorExecution] Skipped cleanup after fenced completion miss: request_id=%s "
                    "lease_owner=%s",
                    request_id,
                    lease_owner,
                )

        execution_time_ms = (time_module.time() - start_time) * 1000

        if state.agent_id and state.parent_session_id:
            await _finalize_child_session_result(
                agent_id=state.agent_id,
                child_session_id=state.conversation_id,
                request_message_id=state.message_id,
                parent_session_id=state.parent_session_id,
                result_content=ss.final_content,
                success=not ss.is_error,
                event_count=len(ss.events),
                execution_time_ms=execution_time_ms,
                error_message=ss.error_message,
            )

        await _project_automation_stream_terminal(
            automation_identity,
            outcome="failed" if ss.is_error else "success",
            state=ss,
            start_time=start_time,
        )

        return ProjectChatResult(
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            content=ss.final_content,
            last_event_time_us=time_gen.last_time_us,
            last_event_counter=time_gen.last_counter,
            is_error=ss.is_error,
            error_message=ss.error_message,
            execution_time_ms=execution_time_ms,
            event_count=len(ss.events),
        )

    except asyncio.CancelledError:
        await _project_automation_stream_terminal(
            automation_identity,
            outcome="cancelled",
            state=ss,
            start_time=start_time,
        )
        raise
    except Exception as e:
        await _project_automation_stream_terminal(
            automation_identity,
            outcome="timeout" if isinstance(e, TimeoutError) else "failed",
            state=ss,
            start_time=start_time,
        )
        return await _handle_chat_error(
            e,
            ss.events,
            ss.persisted_count,
            state.conversation_id,
            state.message_id,
            state.correlation_id,
            start_time,
            publish_error=False,
            agent_id=state.agent_id,
            parent_session_id=state.parent_session_id,
        )
    finally:
        await clear_agent_running(state.conversation_id, state.message_id)


# ---------------------------------------------------------------------------
# Infrastructure helpers (DB, Redis, metrics)
# ---------------------------------------------------------------------------


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

    try:
        async with async_session_factory() as session, session.begin():
            existing_assistant_result = await session.execute(
                select(AgentExecutionEvent.event_data).where(
                    AgentExecutionEvent.conversation_id == conversation_id,
                    AgentExecutionEvent.message_id == message_id,
                    AgentExecutionEvent.event_type == "assistant_message",
                )
            )
            existing_assistant_events = [
                event_data
                for event_data in existing_assistant_result.scalars().all()
                if isinstance(event_data, dict)
            ]
            has_text_end_messages = any(
                event_data.get("source") == "text_end" for event_data in existing_assistant_events
            )
            has_complete_assistant_message = any(
                event_data.get("source") == "complete" for event_data in existing_assistant_events
            )
            inserted_message_count = 0
            latest_event_time_us = 0

            for event in events:
                (
                    persistable_event,
                    has_text_end_messages,
                    has_complete_assistant_message,
                ) = _prepare_event_for_persistence(
                    event,
                    has_text_end_messages=has_text_end_messages,
                    has_complete_assistant_message=has_complete_assistant_message,
                )
                if persistable_event is None:
                    continue

                stmt = (
                    insert(AgentExecutionEvent)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type=persistable_event.event_type,
                        event_data=persistable_event.event_data,
                        event_time_us=persistable_event.event_time_us,
                        event_counter=persistable_event.event_counter,
                        correlation_id=correlation_id,
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["conversation_id", "event_time_us", "event_counter"]
                    )
                    .returning(
                        AgentExecutionEvent.event_type,
                        AgentExecutionEvent.event_time_us,
                    )
                )
                insert_result = await session.execute(stmt)
                inserted_row = insert_result.one_or_none()
                if inserted_row is None:
                    continue
                inserted_event_type, inserted_event_time = inserted_row
                if inserted_event_type in _MESSAGE_EVENT_TYPES:
                    inserted_message_count += 1
                latest_event_time_us = max(latest_event_time_us, int(inserted_event_time))

            await apply_conversation_event_projection_delta(
                session,
                conversation_id,
                inserted_message_count=inserted_message_count,
                latest_event_time_us=latest_event_time_us or None,
            )
    except Exception as e:
        logger.error(
            f"[ActorExecution] Failed to persist {len(events)} events "
            f"for conversation {conversation_id}: {e}",
            exc_info=True,
        )


def _prepare_event_for_persistence(
    event: dict[str, Any],
    *,
    has_text_end_messages: bool,
    has_complete_assistant_message: bool,
) -> tuple[_PersistableEvent | None, bool, bool]:
    """Normalize a stream event into the shape persisted by the actor."""
    normalized_event = normalize_event_dict(event)
    persistable_event: _PersistableEvent | None = None
    next_has_text_end_messages = has_text_end_messages
    next_has_complete_assistant_message = has_complete_assistant_message

    if normalized_event is not None:
        event_type = str(normalized_event.get("type", "unknown"))
        if event_type not in _SKIP_PERSIST_EVENT_TYPES:
            raw_event_data = normalized_event.get("data", {})
            event_data = dict(raw_event_data)
            evt_time_us = _coerce_event_int(normalized_event.get("event_time_us", 0))
            evt_counter = _coerce_event_int(normalized_event.get("event_counter", 0))

            if event_type == "text_end":
                full_text = str(event_data.get("full_text", "")).strip()
                if full_text:
                    persistable_event = _PersistableEvent(
                        event_type="assistant_message",
                        event_data={
                            "content": full_text,
                            "message_id": str(uuid.uuid4()),
                            "role": "assistant",
                            "source": "text_end",
                        },
                        event_time_us=evt_time_us,
                        event_counter=evt_counter,
                    )
                    next_has_text_end_messages = True
            elif event_type == "complete":
                persistable_event, complete_created_message = _complete_event_for_persistence(
                    raw_event_data,
                    event_data,
                    event_time_us=evt_time_us,
                    event_counter=evt_counter,
                    has_text_end_messages=has_text_end_messages,
                    has_complete_assistant_message=has_complete_assistant_message,
                )
                if complete_created_message:
                    next_has_complete_assistant_message = True
            elif event_type == "status":
                persistable_event, status_created_message = _terminal_workspace_status_event(
                    event_data,
                    event_time_us=evt_time_us,
                    event_counter=evt_counter,
                    has_assistant_message=(has_text_end_messages or has_complete_assistant_message),
                )
                if status_created_message:
                    next_has_complete_assistant_message = True
                if persistable_event is None:
                    persistable_event = _PersistableEvent(
                        event_type=event_type,
                        event_data=event_data,
                        event_time_us=evt_time_us,
                        event_counter=evt_counter,
                    )
            else:
                persistable_event = _PersistableEvent(
                    event_type=event_type,
                    event_data=event_data,
                    event_time_us=evt_time_us,
                    event_counter=evt_counter,
                )

    return (
        _sanitize_persistable_event(persistable_event),
        next_has_text_end_messages,
        next_has_complete_assistant_message,
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
    """Publish an error event to the conversation Redis stream.

    Uses the pooled Redis client (``_get_redis_client``) instead of opening a
    fresh connection per call. The previous implementation called
    ``aioredis.from_url`` + ``close()`` on every error path, which caused
    connection churn and a ``RuntimeError: Event loop is closed`` race during
    actor shutdown.
    """
    stream_key = f"agent:events:{conversation_id}"

    now = datetime.now(UTC)
    now_us = int(now.timestamp() * 1_000_000)

    error_event: dict[str, Any] = {
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

    try:
        redis_client = await _get_redis_client()
        await redis_client.xadd(stream_key, {"data": json.dumps(error_event)}, maxlen=1000)
    except Exception as e:
        logger.error(
            f"[ActorExecution] Failed to publish error event to Redis: {e}",
            exc_info=True,
        )
        agent_metrics.increment(
            "project_agent.event_publish_errors",
            labels={"event_type": "error"},
        )


def _build_stream_redis_message(
    conversation_id: str,
    event: dict[str, Any],
    message_id: str,
    event_time_us: int,
    event_counter: int,
    correlation_id: str | None = None,
) -> dict[str, str] | None:
    """Build the Redis stream message for one event, or None if it normalizes away."""
    normalized_event = normalize_event_dict(event)
    if normalized_event is None:
        return None

    event_type = normalized_event.get("type", "unknown")
    event_data = normalized_event.get("data", {})

    event_data_with_meta = dict(
        _sanitize_event_data_for_postgres({**event_data, "message_id": message_id})
    )

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

    return {"data": json.dumps(stream_event_payload)}


async def _publish_event_to_stream(
    conversation_id: str,
    event: dict[str, Any],
    message_id: str,
    event_time_us: int,
    event_counter: int,
    correlation_id: str | None = None,
    redis_client: aioredis.Redis | None = None,
) -> None:
    normalized_event = normalize_event_dict(event)
    if normalized_event is None:
        return
    event_type = normalized_event.get("type", "unknown")

    redis_message = _build_stream_redis_message(
        conversation_id,
        event,
        message_id,
        event_time_us,
        event_counter,
        correlation_id,
    )
    if redis_message is None:
        return

    if redis_client is None:
        redis_client = await _get_redis_client()

    try:
        stream_key = f"agent:events:{conversation_id}"
        await redis_client.xadd(stream_key, redis_message, maxlen=1000)  # type: ignore[arg-type]
        if event_type in ("task_list_updated", "task_updated"):
            event_data = normalized_event.get("data", {})
            task_count = len(event_data.get("tasks", [])) if isinstance(event_data, dict) else 0
            logger.info(
                f"[ActorExecution] Published {event_type} to Redis: "
                f"conversation={conversation_id}, tasks={task_count}"
            )
    except Exception as e:
        # Promoted from warning to error: when Redis publish fails the live UI
        # stalls until the WAL replay path catches up on reconnect. The DB
        # remains the source of truth (``_maybe_incremental_persist``), so we
        # do not raise; we surface a metric so dashboards can alert.
        logger.error(
            f"[ActorExecution] Failed to publish {event_type} event to Redis "
            f"(conversation={conversation_id}): {e}",
            exc_info=True,
        )
        agent_metrics.increment(
            "project_agent.event_publish_errors",
            labels={"event_type": event_type},
        )


# Delta event types that are buffered and flushed to the Redis stream in
# batches. They fire once per LLM token; batching removes one Redis round
# trip per token from the actor event loop while keeping one stream entry
# per event (so replay/dedup semantics are unchanged).
_STREAM_BATCHABLE_DELTA_TYPES = frozenset({"text_delta", "thought_delta", "act_delta"})

# Flush buffered deltas at least this often; also flushed before any
# non-delta event and at end of stream, preserving event order.
_STREAM_DELTA_FLUSH_INTERVAL_S = 0.05


async def _flush_pending_delta_events(
    pending: list[tuple[dict[str, Any], int, int]],
    *,
    conversation_id: str,
    message_id: str,
    correlation_id: str | None,
    redis_client: aioredis.Redis,
) -> None:
    """Flush buffered delta events with one pipelined Redis round trip.

    Failure semantics match ``_publish_event_to_stream``: log + metric, never
    raise — the DB remains the source of truth for replay.
    """
    if not pending:
        return
    try:
        stream_key = f"agent:events:{conversation_id}"
        pipeline = redis_client.pipeline(transaction=False)
        queued = 0
        for event, event_time_us, event_counter in pending:
            redis_message = _build_stream_redis_message(
                conversation_id,
                event,
                message_id,
                event_time_us,
                event_counter,
                correlation_id,
            )
            if redis_message is None:
                continue
            pipeline.xadd(stream_key, redis_message, maxlen=1000)  # type: ignore[arg-type]
            queued += 1
        if queued:
            await pipeline.execute()
    except Exception as e:
        logger.error(
            f"[ActorExecution] Failed to publish {len(pending)} delta events to Redis "
            f"(conversation={conversation_id}): {e}",
            exc_info=True,
        )
        agent_metrics.increment(
            "project_agent.event_publish_errors",
            labels={"event_type": "delta_batch"},
        )
    finally:
        pending.clear()


async def _stream_publish_event(
    *,
    event: dict[str, Any],
    event_time_us: int,
    event_counter: int,
    pending_deltas: list[tuple[dict[str, Any], int, int]],
    conversation_id: str,
    message_id: str,
    correlation_id: str | None,
    redis_client: aioredis.Redis,
    last_delta_flush: float,
) -> float:
    """Route one event to the Redis stream: buffer deltas, publish others.

    Per-token deltas are buffered and flushed in batches (on interval, before
    any non-delta event so stream order is preserved, and at end of stream by
    the caller). Returns the updated last-flush timestamp.
    """
    if event.get("type") in _STREAM_BATCHABLE_DELTA_TYPES:
        pending_deltas.append((event, event_time_us, event_counter))
        now = time_module.time()
        if now - last_delta_flush < _STREAM_DELTA_FLUSH_INTERVAL_S:
            return last_delta_flush
        await _flush_pending_delta_events(
            pending_deltas,
            conversation_id=conversation_id,
            message_id=message_id,
            correlation_id=correlation_id,
            redis_client=redis_client,
        )
        return now

    await _flush_pending_delta_events(
        pending_deltas,
        conversation_id=conversation_id,
        message_id=message_id,
        correlation_id=correlation_id,
        redis_client=redis_client,
    )
    await _publish_event_to_stream(
        conversation_id=conversation_id,
        event=event,
        message_id=message_id,
        event_time_us=event_time_us,
        event_counter=event_counter,
        correlation_id=correlation_id,
        redis_client=redis_client,
    )
    return time_module.time()


async def _get_redis_client() -> aioredis.Redis:
    return await get_redis_client()


async def _get_announce_service() -> AnnounceService:
    """Get or create module-level AnnounceService singleton."""
    redis_client = await _get_redis_client()
    return AnnounceService(redis_client=redis_client)


async def _finalize_child_session_result(
    *,
    agent_id: str,
    child_session_id: str,
    request_message_id: str,
    parent_session_id: str,
    result_content: str,
    success: bool,
    event_count: int,
    execution_time_ms: float,
    error_message: str | None,
) -> None:
    """Mirror a child session terminal result into parent-visible status and history."""
    terminal_message_id = _child_terminal_message_id(
        child_session_id=child_session_id,
        request_message_id=request_message_id,
    )
    terminal_signature = _child_terminal_signature(
        content=result_content,
        success=success,
        error_message=error_message,
    )
    finalization_state_key = f"agent:child:terminal:state:{terminal_message_id}"
    finalization_lock_key = f"{finalization_state_key}:lock"
    redis_client: aioredis.Redis | None = None
    lock_token: str | None = None
    lock_acquired = False

    try:
        try:
            redis_client = await _get_redis_client()
            lock_token = str(uuid.uuid4())
            lock_acquired = bool(
                await redis_client.set(finalization_lock_key, lock_token, ex=30, nx=True)
            )
            if not lock_acquired:
                return

            existing_signature = await redis_client.get(finalization_state_key)
            if isinstance(existing_signature, bytes):
                existing_signature = existing_signature.decode("utf-8")
            if existing_signature == terminal_signature:
                return
        except Exception:
            logger.warning(
                "Failed to acquire child finalization guard for session=%s message=%s",
                child_session_id,
                request_message_id,
                exc_info=True,
            )
            redis_client = None
            lock_token = None
            lock_acquired = False

        terminal_status = await _resolve_child_terminal_status(
            child_session_id=child_session_id,
            success=success,
        )
        if terminal_status is not None:
            await _update_spawn_status(
                child_session_id=child_session_id,
                status=terminal_status,
                parent_session_id=parent_session_id,
            )
        await _record_child_result_history(
            agent_id=agent_id,
            child_session_id=child_session_id,
            request_message_id=request_message_id,
            parent_session_id=parent_session_id,
            result_content=result_content,
            success=success,
            event_count=event_count,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
        )

        announce_content = result_content.strip() or (error_message or "").strip()
        _task = asyncio.create_task(
            _publish_announce_via_service(
                agent_id=agent_id,
                parent_session_id=parent_session_id,
                child_session_id=child_session_id,
                result_content=announce_content,
                success=success,
                event_count=event_count,
                execution_time_ms=execution_time_ms,
            )
        )
        _background_tasks.add(_task)
        _task.add_done_callback(_background_tasks.discard)

        if redis_client is not None:
            try:
                await redis_client.set(finalization_state_key, terminal_signature, ex=86400)
            except Exception:
                logger.warning(
                    "Failed to persist child finalization signature for session=%s message=%s",
                    child_session_id,
                    request_message_id,
                    exc_info=True,
                )
    finally:
        if redis_client is not None and lock_token is not None and lock_acquired:
            try:
                current_lock = await redis_client.get(finalization_lock_key)
                if isinstance(current_lock, bytes):
                    current_lock = current_lock.decode("utf-8")
                if current_lock == lock_token:
                    await redis_client.delete(finalization_lock_key)
            except Exception:
                logger.warning(
                    "Failed to release child finalization lock for session=%s message=%s",
                    child_session_id,
                    request_message_id,
                    exc_info=True,
                )


async def _record_child_result_history(
    *,
    agent_id: str,
    child_session_id: str,
    request_message_id: str,
    parent_session_id: str,
    result_content: str,
    success: bool,
    event_count: int,
    execution_time_ms: float,
    error_message: str | None,
) -> None:
    """Persist a child agent's terminal result into its own queryable history."""
    terminal_message_id = _child_terminal_message_id(
        child_session_id=child_session_id,
        request_message_id=request_message_id,
    )
    content = result_content.strip()
    if not content:
        content = (error_message or "").strip()
    if not content:
        content = "Child session finished without textual output."
    metadata = {
        "source": "child_result_history",
        "parent_session_id": parent_session_id,
        "success": success,
        "event_count": event_count,
        "execution_time_ms": round(execution_time_ms, 2),
        "error_message": error_message,
        "source_message_id": request_message_id,
        "terminal_message_id": terminal_message_id,
    }

    try:
        redis_client = await _get_redis_client()
        message_bus = RedisAgentMessageBusAdapter(redis_client)
        history = await message_bus.get_message_history(session_id=child_session_id, limit=50)
        existing_terminal_message = next(
            (
                message
                for message in reversed(history)
                if message.metadata
                and message.metadata.get("terminal_message_id") == terminal_message_id
            ),
            None,
        )
        terminal_metadata = (
            existing_terminal_message.metadata if existing_terminal_message else None
        )
        terminal_metadata = terminal_metadata or {}
        terminal_message_matches = (
            existing_terminal_message is not None
            and existing_terminal_message.content == content
            and bool(terminal_metadata.get("success")) is success
            and terminal_metadata.get("error_message") == error_message
        )
        if not terminal_message_matches:
            await message_bus.send_message(
                from_agent_id=agent_id,
                to_agent_id="",
                session_id=child_session_id,
                content=content,
                message_type=AgentMessageType.RESPONSE,
                metadata=metadata,
            )
    except Exception:
        logger.warning(
            "Failed to persist child result history for agent=%s session=%s",
            agent_id,
            child_session_id,
            exc_info=True,
        )

    await _persist_child_result_message(
        child_session_id=child_session_id,
        terminal_message_id=terminal_message_id,
        content=content,
        success=success,
        metadata=metadata,
    )


def _child_terminal_message_id(*, child_session_id: str, request_message_id: str) -> str:
    """Build a deterministic ID for a child session's terminal history record."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{child_session_id}:{request_message_id}:terminal"))


def _child_terminal_signature(
    *,
    content: str,
    success: bool,
    error_message: str | None,
) -> str:
    """Serialize the terminal payload shape used for idempotent child finalization."""
    return json.dumps(
        {
            "content": content,
            "success": success,
            "error_message": error_message,
        },
        sort_keys=True,
    )


async def _persist_child_result_message(
    *,
    child_session_id: str,
    terminal_message_id: str,
    content: str,
    success: bool,
    metadata: dict[str, Any],
) -> None:
    """Persist a child terminal result to the DB-backed conversation history."""
    try:
        from sqlalchemy import func, select

        from src.domain.model.agent.conversation.message import (
            Message,
            MessageRole,
            MessageType,
        )
        from src.infrastructure.adapters.secondary.persistence.models import Message as DBMessage
        from src.infrastructure.adapters.secondary.persistence.sql_conversation_repository import (
            SqlConversationRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_message_repository import (
            SqlMessageRepository,
        )

        async with async_session_factory() as session:
            conversation_repo = SqlConversationRepository(session)
            message_repo = SqlMessageRepository(session)
            conversation = await conversation_repo.find_by_id(child_session_id)
            if conversation is None:
                return

            existing_message_result = await session.execute(
                select(DBMessage.id).where(DBMessage.id == terminal_message_id)
            )
            message_exists = existing_message_result.scalar_one_or_none() is not None
            await message_repo.save(
                Message(
                    id=terminal_message_id,
                    conversation_id=child_session_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    message_type=MessageType.TEXT if success else MessageType.ERROR,
                    metadata=metadata,
                )
            )
            if not success and not message_exists:
                projected_assistant_result = await session.execute(
                    select(func.count())
                    .select_from(AgentExecutionEvent)
                    .where(
                        AgentExecutionEvent.conversation_id == child_session_id,
                        AgentExecutionEvent.event_type == "assistant_message",
                    )
                )
                projected_assistant_count = int(projected_assistant_result.scalar() or 0)
                if projected_assistant_count == 0:
                    conversation.increment_message_count()
                    await conversation_repo.save(conversation)
            await session.commit()
    except Exception:
        logger.warning(
            "Failed to persist child DB message history for session=%s",
            child_session_id,
            exc_info=True,
        )


async def _publish_announce_via_service(
    agent_id: str,
    parent_session_id: str,
    child_session_id: str,
    result_content: str,
    success: bool,
    event_count: int,
    execution_time_ms: float,
) -> None:
    """Publish announce via AnnounceService (fire-and-forget wrapper)."""
    try:
        service = await _get_announce_service()
        await service.publish_announce(
            agent_id=agent_id,
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            result_content=result_content,
            success=success,
            event_count=event_count,
            execution_time_ms=execution_time_ms,
        )
    except Exception:
        logger.warning(
            "Failed to publish announce via service for agent=%s session=%s",
            agent_id,
            child_session_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# HITL response formatting (dispatch-dict pattern)
# ---------------------------------------------------------------------------


def _format_clarification_response(response_data: object) -> str:
    """Format clarification HITL response."""
    if isinstance(response_data, str):
        return f"User clarification: {response_data}"
    if not isinstance(response_data, dict):
        return "User provided clarification (no specific selection)"
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


def _format_decision_response(response_data: object) -> str:
    """Format decision HITL response."""
    if isinstance(response_data, str):
        return f"User decision: {response_data}"
    if not isinstance(response_data, dict):
        return "User made a decision (no specific selection)"
    selected = response_data.get("selected_option_id") or response_data.get("decision")
    custom = response_data.get("custom_input") or response_data.get("decision")
    if custom:
        return f"User decision (custom): {custom}"
    if selected:
        return f"User chose: {selected}"
    return "User made a decision (no specific selection)"


def _format_env_var_response(response_data: object) -> str:
    """Format env_var HITL response."""
    if isinstance(response_data, str):
        return f"User provided environment variables: {response_data}"
    if not isinstance(response_data, dict):
        return "User provided environment variable values"
    values = response_data.get("values", {})
    provided_vars = list(values.keys()) if isinstance(values, dict) else []
    if provided_vars:
        return f"User provided environment variables: {', '.join(provided_vars)}"
    return "User provided environment variable values"


def _format_permission_response(response_data: object) -> str:
    """Format permission HITL response."""
    if isinstance(response_data, str):
        return f"User permission response: {response_data}"
    if not isinstance(response_data, dict):
        return "User denied permission"
    granted = response_data.get("granted")
    if granted is None:
        granted = response_data.get("action") == "allow"
    scope = response_data.get("scope", "once")
    if granted:
        return f"User granted permission (scope: {scope})"
    return "User denied permission"


_HITL_FORMATTERS: dict[str, Any] = {
    "clarification": _format_clarification_response,
    "decision": _format_decision_response,
    "env_var": _format_env_var_response,
    "permission": _format_permission_response,
}


def _format_hitl_response_as_tool_result(
    hitl_type: str,
    response_data: object,
) -> str:
    """Format HITL response data as a tool result content string."""
    if isinstance(response_data, str):
        return f"User responded to {hitl_type} request: {response_data}"
    if not isinstance(response_data, dict):
        return f"User responded to {hitl_type} request"
    if response_data.get("cancelled") or response_data.get("timeout"):
        return f"User did not complete {hitl_type} request"
    formatter = _HITL_FORMATTERS.get(hitl_type)
    if formatter:
        return cast(str, formatter(response_data))
    return f"User responded to {hitl_type} request"


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def _save_mcp_app_html(app_id: str, resource_uri: str, html_content: str) -> None:
    """Persist agent-generated MCPApp HTML to the database (D2 fix).

    Called as a fire-and-forget background task when the agent emits a
    ``mcp_app_result`` event with non-empty ``resource_html``. Persisting the
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
