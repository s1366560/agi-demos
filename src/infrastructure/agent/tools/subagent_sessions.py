"""Session-oriented SubAgent collaboration tools."""

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from src.domain.events.agent_events import SubAgentDepthLimitedEvent
from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlChannelPort, ControlMessage
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


def _resolve_spawn_callback_signature(
    callback: Callable[..., Awaitable[str]],
) -> tuple[set[str] | None, bool]:
    """Resolve callback kwargs support for backwards-compatible spawn options."""
    target = callback
    side_effect = getattr(callback, "side_effect", None)
    if callable(side_effect):
        target = side_effect

    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return None, True

    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    accepted_params = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }
    return accepted_params, accepts_kwargs


def _filter_spawn_options(
    options: dict[str, Any],
    accepted_params: set[str] | None,
    accepts_kwargs: bool,
) -> dict[str, Any]:
    if accepts_kwargs or accepted_params is None:
        return dict(options)
    return {
        key: value for key, value in options.items() if key in accepted_params and value is not None
    }


def _record_announce_event(
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    max_events: int = 20,
) -> None:
    """Persist bounded announce history into run metadata."""
    run = run_registry.get_run(conversation_id, run_id)
    if not run:
        return
    announce_events = run.metadata.get("announce_events")
    if not isinstance(announce_events, list):
        announce_events = []
    dropped = int(run.metadata.get("announce_events_dropped") or 0)
    if len(announce_events) >= max_events:
        announce_events = announce_events[-(max_events - 1) :]
        dropped += 1
    announce_events.append(
        {
            "type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
    )
    metadata: dict[str, Any] = {"announce_events": announce_events}
    if dropped > 0:
        metadata["announce_events_dropped"] = dropped
    run_registry.attach_metadata(conversation_id, run_id, metadata)


def _build_lifecycle_metadata(
    *,
    session_mode: str,
    requester_session_key: str,
    lineage_root_run_id: str | None,
    parent_run_id: str | None = None,
    delegation_depth: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build normalized run metadata for control-plane lifecycle tracking."""
    metadata: dict[str, Any] = {
        "session_mode": session_mode,
        "control_plane_version": "v2",
    }
    if delegation_depth is not None:
        metadata["delegation_depth"] = delegation_depth
    if extra:
        metadata.update(extra)
    return metadata


# ---------------------------------------------------------------------------
# @tool_define decorator-based session tools (migrate batch 1 of 2)
# ---------------------------------------------------------------------------


# Shared DI state for all decorator-based session tools

_sess_run_registry: SubAgentRunRegistry | None = None
_sess_spawn_callback: Callable[..., Awaitable[str]] | None = None
_sess_max_active_runs: int = 3
_sess_max_spawn_retries: int = 2
_sess_retry_delay_ms: int = 200
_sess_subagent_names: list[str] = []
_sess_subagent_descriptions: dict[str, str] = {}
_sess_conversation_id: str = ""
_sess_requester_session_key: str = ""
_sess_delegation_depth: int = 0
_sess_max_delegation_depth: int = 1
_sess_max_active_runs_per_lineage: int = 16
_sess_max_children_per_requester: int = 16
_sess_visibility_default: str = "tree"


def configure_session_tools(  # noqa: PLR0913
    run_registry: SubAgentRunRegistry,
    spawn_callback: Callable[..., Awaitable[str]] | None = None,
    max_active_runs: int = 3,
    *,
    max_spawn_retries: int = 2,
    retry_delay_ms: int = 200,
    subagent_names: list[str] | None = None,
    subagent_descriptions: dict[str, str] | None = None,
    conversation_id: str = "",
    requester_session_key: str = "",
    delegation_depth: int = 0,
    max_delegation_depth: int = 1,
    max_active_runs_per_lineage: int = 16,
    max_children_per_requester: int = 16,
    visibility_default: str = "tree",
) -> None:
    """Configure shared state for all decorator-based session tools."""
    global \
        _sess_run_registry, \
        _sess_spawn_callback, \
        _sess_max_active_runs, \
        _sess_max_spawn_retries, \
        _sess_retry_delay_ms, \
        _sess_subagent_names, \
        _sess_subagent_descriptions, \
        _sess_conversation_id, \
        _sess_requester_session_key, \
        _sess_delegation_depth, \
        _sess_max_delegation_depth, \
        _sess_max_active_runs_per_lineage, \
        _sess_max_children_per_requester, \
        _sess_visibility_default
    _sess_run_registry = run_registry
    _sess_spawn_callback = spawn_callback
    _sess_max_active_runs = max(1, max_active_runs)
    _sess_max_spawn_retries = max(0, max_spawn_retries)
    _sess_retry_delay_ms = max(1, retry_delay_ms)
    _sess_subagent_names = subagent_names or []
    _sess_subagent_descriptions = subagent_descriptions or {}
    _sess_conversation_id = conversation_id
    _sess_requester_session_key = (requester_session_key or conversation_id).strip()
    _sess_delegation_depth = delegation_depth
    _sess_max_delegation_depth = max(1, max_delegation_depth)
    _sess_max_active_runs_per_lineage = max(1, max_active_runs_per_lineage)
    _sess_max_children_per_requester = max(1, max_children_per_requester)
    _sess_visibility_default = (
        visibility_default if visibility_default in {"self", "tree", "all"} else "tree"
    )


# ---------------------------------------------------------------------------
# sessions_spawn helpers
# ---------------------------------------------------------------------------


def _spawn_validate_basic(
    subagent_name: str,
    task: str,
) -> str | None:
    """Validate subagent_name, task, and delegation depth."""
    if not subagent_name or subagent_name not in _sess_subagent_names:
        return f"Error: invalid subagent_name. Available: {', '.join(_sess_subagent_names)}"
    if not task or not task.strip():
        return "Error: task is required"
    if _sess_delegation_depth >= _sess_max_delegation_depth:
        return (
            "Error: sessions_spawn is disabled at current delegation depth "
            f"({_sess_delegation_depth}/{_sess_max_delegation_depth})"
        )
    return None


def _spawn_validate_mode_cleanup(
    spawn_mode: str,
    thread_requested: bool,
    cleanup_policy: str,
) -> str | None:
    """Validate mode, thread, and cleanup constraints."""
    if spawn_mode not in {"run", "session"}:
        return "Error: mode must be one of run|session"
    if spawn_mode == "session" and not thread_requested:
        return "Error: mode='session' requires thread=true"
    if cleanup_policy not in {"keep", "delete"}:
        return "Error: cleanup must be one of keep|delete"
    if spawn_mode == "session" and cleanup_policy == "delete":
        return "Error: mode='session' requires cleanup='keep'"
    return None


def _spawn_check_capacity() -> str | None:
    """Check active run capacity limits, returning error if exceeded."""
    assert _sess_run_registry is not None
    active_runs = _sess_run_registry.count_active_runs(_sess_conversation_id)
    if active_runs >= _sess_max_active_runs:
        return (
            f"Error: active SubAgent sessions limit reached ({active_runs}/{_sess_max_active_runs})"
        )
    requester_runs = _sess_run_registry.count_active_runs_for_requester(
        _sess_conversation_id, _sess_requester_session_key
    )
    if requester_runs >= _sess_max_children_per_requester:
        return (
            "Error: requester SubAgent sessions limit reached "
            f"({requester_runs}/{_sess_max_children_per_requester})"
        )
    return None


async def _spawn_with_retry_fn(
    ctx: ToolContext,
    run_id: str,
    subagent_name: str,
    task: str,
    spawn_options: dict[str, Any],
) -> int:
    """Retry spawn callback and record announce events."""
    assert _sess_run_registry is not None
    assert _sess_spawn_callback is not None
    accepted_params, accepts_kwargs = _resolve_spawn_callback_signature(_sess_spawn_callback)
    filtered = _filter_spawn_options(spawn_options, accepted_params, accepts_kwargs)
    last_error: Exception | None = None
    for attempt in range(_sess_max_spawn_retries + 1):
        try:
            await _sess_spawn_callback(subagent_name, task, run_id, **filtered)
            return attempt
        except Exception as exc:
            last_error = exc
            if attempt >= _sess_max_spawn_retries:
                break
            await ctx.emit(
                {
                    "type": "subagent_announce_retry",
                    "data": {
                        "conversation_id": _sess_conversation_id,
                        "run_id": run_id,
                        "subagent_name": subagent_name,
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "next_delay_ms": _sess_retry_delay_ms,
                    },
                }
            )
            _record_announce_event(
                run_registry=_sess_run_registry,
                conversation_id=_sess_conversation_id,
                run_id=run_id,
                event_type="retry",
                payload={
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "next_delay_ms": _sess_retry_delay_ms,
                },
            )
            await asyncio.sleep(_sess_retry_delay_ms / 1000)

    await ctx.emit(
        {
            "type": "subagent_announce_giveup",
            "data": {
                "conversation_id": _sess_conversation_id,
                "run_id": run_id,
                "subagent_name": subagent_name,
                "attempts": _sess_max_spawn_retries + 1,
                "error": str(last_error) if last_error else "unknown error",
            },
        }
    )
    _record_announce_event(
        run_registry=_sess_run_registry,
        conversation_id=_sess_conversation_id,
        run_id=run_id,
        event_type="giveup",
        payload={
            "attempts": _sess_max_spawn_retries + 1,
            "error": str(last_error) if last_error else "unknown error",
        },
    )
    if last_error:
        raise last_error
    raise RuntimeError("failed to spawn session")


async def _spawn_create_and_run(
    ctx: ToolContext,
    subagent_name: str,
    target_subagent_name: str,
    task: str,
    spawn_options: dict[str, Any],
) -> ToolResult:
    """Create run record and invoke spawn callback."""
    assert _sess_run_registry is not None
    run = _sess_run_registry.create_run(
        conversation_id=_sess_conversation_id,
        subagent_name=target_subagent_name,
        task=task,
        metadata=_build_lifecycle_metadata(
            session_mode="spawn",
            requester_session_key=_sess_requester_session_key,
            lineage_root_run_id=None,
            delegation_depth=_sess_delegation_depth,
            extra={
                **spawn_options,
                "requested_subagent_name": subagent_name,
                "max_active_runs_per_lineage": _sess_max_active_runs_per_lineage,
            },
        ),
        requester_session_key=_sess_requester_session_key,
    )
    running = _sess_run_registry.mark_running(_sess_conversation_id, run.run_id)
    if running:
        await ctx.emit({"type": "subagent_started", "data": running.to_event_data()})
    try:
        retry_count = await _spawn_with_retry_fn(
            ctx,
            run_id=run.run_id,
            subagent_name=target_subagent_name,
            task=task,
            spawn_options=spawn_options,
        )
        if retry_count > 0:
            _sess_run_registry.attach_metadata(
                _sess_conversation_id,
                run.run_id,
                {"announce_retry_count": retry_count},
            )
        await ctx.emit(
            {
                "type": "subagent_session_spawned",
                "data": {
                    "conversation_id": _sess_conversation_id,
                    "run_id": run.run_id,
                    "subagent_name": target_subagent_name,
                    "spawn_mode": spawn_options["spawn_mode"],
                    "thread_requested": spawn_options["thread_requested"],
                    "cleanup": spawn_options["cleanup"],
                },
            }
        )
        return _spawn_success_result(run.run_id, target_subagent_name, spawn_options)
    except Exception as exc:
        failed = _sess_run_registry.mark_failed(
            conversation_id=_sess_conversation_id,
            run_id=run.run_id,
            error=str(exc),
        )
        if failed:
            await ctx.emit({"type": "subagent_failed", "data": failed.to_event_data()})
        return ToolResult(
            output=f"Error: failed to spawn session: {exc}",
            is_error=True,
        )


def _spawn_success_result(
    run_id: str,
    target_subagent_name: str,
    spawn_options: dict[str, Any],
) -> ToolResult:
    """Build success ToolResult for spawn."""
    if spawn_options["spawn_mode"] == "session":
        return ToolResult(
            output=(
                f"Spawned persistent SubAgent session {run_id} for "
                f"'{target_subagent_name}'. Use sessions_send to continue the lineage."
            ),
        )
    return ToolResult(
        output=(
            f"Spawned SubAgent session {run_id} for '{target_subagent_name}'. "
            "Use sessions_list or sessions_history to inspect progress."
        ),
    )


# ---------------------------------------------------------------------------
# 1. sessions_spawn_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_spawn_v2",
    description=(
        "Spawn a detached SubAgent session for long-running work. "
        "Use sessions_list or sessions_history to inspect progress."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subagent_name": {
                "type": "string",
                "description": "Target SubAgent name.",
            },
            "task": {
                "type": "string",
                "description": "Task to execute asynchronously.",
            },
            "run_timeout_seconds": {
                "type": "integer",
                "description": ("Optional timeout for the detached run (0 means no timeout)."),
                "minimum": 0,
                "maximum": 3600,
            },
            "mode": {
                "type": "string",
                "description": ("Spawn mode: run (one-shot) or session (persistent follow-up)."),
                "enum": ["run", "session"],
            },
            "thread": {
                "type": "boolean",
                "description": ("Whether thread binding is requested for this spawn."),
            },
            "cleanup": {
                "type": "string",
                "description": "Post-run cleanup preference.",
                "enum": ["keep", "delete"],
            },
            "agent_id": {
                "type": "string",
                "description": ("Optional SubAgent override; must match an available subagent."),
            },
            "model": {
                "type": "string",
                "description": ("Optional model override for this spawned session."),
            },
            "thinking": {
                "type": "string",
                "description": ("Optional thinking/reasoning level hint for this spawned session."),
            },
        },
        "required": ["subagent_name", "task"],
    },
    category="subagent",
    tags=frozenset({"subagent", "spawn"}),
)
async def sessions_spawn_tool(
    ctx: ToolContext,
    *,
    subagent_name: str = "",
    task: str = "",
    run_timeout_seconds: int = 0,
    mode: str = "run",
    thread: bool = False,
    cleanup: str = "keep",
    agent_id: str = "",
    model: str = "",
    thinking: str = "",
) -> ToolResult:
    """Spawn a SubAgent run as a non-blocking session."""
    if _sess_run_registry is None or _sess_spawn_callback is None:
        return ToolResult(
            output="Error: session tools are not configured.",
            is_error=True,
        )
    error = _spawn_validate_basic(subagent_name, task)
    if error:
        if "delegation depth" in error:
            await ctx.emit(
                dict(
                    SubAgentDepthLimitedEvent(
                        subagent_name=subagent_name or "unknown",
                        current_depth=_sess_delegation_depth,
                        max_depth=_sess_max_delegation_depth,
                    ).to_event_dict()
                )
            )
        return ToolResult(output=error, is_error=True)
    spawn_mode = (mode or "run").strip().lower()
    cleanup_policy = (cleanup or "keep").strip().lower()
    mode_error = _spawn_validate_mode_cleanup(spawn_mode, bool(thread), cleanup_policy)
    if mode_error:
        return ToolResult(output=mode_error, is_error=True)
    if spawn_mode == "session":
        cleanup_policy = "keep"
    target = _spawn_resolve_agent_id(subagent_name, agent_id)
    if isinstance(target, ToolResult):
        return target
    try:
        timeout_seconds = max(0, int(run_timeout_seconds or 0))
    except (TypeError, ValueError):
        timeout_seconds = 0
    capacity_error = _spawn_check_capacity()
    if capacity_error:
        return ToolResult(output=capacity_error, is_error=True)
    spawn_options: dict[str, Any] = {
        "spawn_mode": spawn_mode,
        "thread_requested": bool(thread),
        "cleanup": cleanup_policy,
        "agent_id": (agent_id or "").strip() or target,
        "model": (model or "").strip() or None,
        "thinking": (thinking or "").strip() or None,
        "requester_session_key": _sess_requester_session_key,
        "run_timeout_seconds": timeout_seconds,
    }
    return await _spawn_create_and_run(
        ctx,
        subagent_name=subagent_name,
        target_subagent_name=target,
        task=task,
        spawn_options=spawn_options,
    )


def _spawn_resolve_agent_id(
    subagent_name: str,
    agent_id: str,
) -> str | ToolResult:
    """Resolve agent_id override to target subagent name."""
    requested = (agent_id or "").strip()
    if not requested:
        return subagent_name
    if requested not in _sess_subagent_names:
        return ToolResult(
            output=(f"Error: invalid agent_id. Available: {', '.join(_sess_subagent_names)}"),
            is_error=True,
        )
    return requested


# ---------------------------------------------------------------------------
# 2. sessions_list_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_list_v2",
    description=(
        "List active SubAgent sessions for this conversation. "
        "Use status='active' for pending/running runs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter runs by status.",
                "enum": [
                    "active",
                    "pending",
                    "running",
                    "completed",
                    "failed",
                    "cancelled",
                    "timed_out",
                ],
            },
            "visibility": {
                "type": "string",
                "description": "Run visibility boundary.",
                "enum": ["self", "tree", "all"],
            },
            "limit": {
                "type": "integer",
                "description": "Maximum runs to return.",
                "minimum": 1,
                "maximum": 200,
            },
        },
        "required": [],
    },
    category="subagent",
    tags=frozenset({"subagent", "list"}),
)
async def sessions_list_tool(
    ctx: ToolContext,
    *,
    status: str = "active",
    visibility: str = "",
    limit: int = 20,
) -> ToolResult:
    """List active SubAgent sessions."""
    _ = ctx
    if _sess_run_registry is None:
        return ToolResult(
            output="Error: session tools are not configured.",
            is_error=True,
        )
    statuses: list[SubAgentRunStatus] | None
    if status == "active":
        statuses = [SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING]
    elif status:
        try:
            statuses = [SubAgentRunStatus(status)]
        except ValueError:
            return ToolResult(
                output=f"Error: invalid status '{status}'",
                is_error=True,
            )
    else:
        statuses = None
    effective_visibility = (visibility or _sess_visibility_default).strip().lower()
    if effective_visibility not in {"self", "tree", "all"}:
        return ToolResult(
            output=f"Error: invalid visibility '{effective_visibility}'",
            is_error=True,
        )
    runs = _sess_run_registry.list_runs_for_requester(
        _sess_conversation_id,
        _sess_requester_session_key,
        visibility=effective_visibility,
        statuses=statuses,
    )[: max(1, limit)]
    output = json.dumps(
        {
            "conversation_id": _sess_conversation_id,
            "visibility": effective_visibility,
            "count": len(runs),
            "runs": [run.to_event_data() for run in runs],
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolResult(output=output)


# ---------------------------------------------------------------------------
# 3. sessions_history_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_history_v2",
    description="List historical SubAgent sessions (including terminal runs).",
    parameters={
        "type": "object",
        "properties": {
            "visibility": {
                "type": "string",
                "description": "Run visibility boundary.",
                "enum": ["self", "tree", "all"],
            },
            "limit": {
                "type": "integer",
                "description": "Maximum history items to return.",
                "minimum": 1,
                "maximum": 200,
            },
        },
        "required": [],
    },
    category="subagent",
    tags=frozenset({"subagent", "history"}),
)
async def sessions_history_tool(
    ctx: ToolContext,
    *,
    visibility: str = "",
    limit: int = 50,
) -> ToolResult:
    """List SubAgent session history."""
    _ = ctx
    if _sess_run_registry is None:
        return ToolResult(
            output="Error: session tools are not configured.",
            is_error=True,
        )
    effective_visibility = (visibility or _sess_visibility_default).strip().lower()
    if effective_visibility not in {"self", "tree", "all"}:
        return ToolResult(
            output=f"Error: invalid visibility '{effective_visibility}'",
            is_error=True,
        )
    runs = _sess_run_registry.list_runs_for_requester(
        _sess_conversation_id,
        _sess_requester_session_key,
        visibility=effective_visibility,
    )[: max(1, limit)]
    output = json.dumps(
        {
            "conversation_id": _sess_conversation_id,
            "visibility": effective_visibility,
            "count": len(runs),
            "runs": [run.to_event_data() for run in runs],
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolResult(output=output)


# ---------------------------------------------------------------------------
# 4. sessions_timeline_tool
# ---------------------------------------------------------------------------


def _timeline_events_for_run(
    run: SubAgentRun,
    *,
    include_announce: bool,
) -> list[dict[str, Any]]:
    """Build lifecycle timeline events for a single run."""
    events: list[dict[str, Any]] = [
        {
            "run_id": run.run_id,
            "subagent_name": run.subagent_name,
            "type": "run_created",
            "status": SubAgentRunStatus.PENDING.value,
            "timestamp": run.created_at.isoformat(),
        }
    ]
    if run.started_at:
        events.append(
            {
                "run_id": run.run_id,
                "subagent_name": run.subagent_name,
                "type": "run_started",
                "status": SubAgentRunStatus.RUNNING.value,
                "timestamp": run.started_at.isoformat(),
            }
        )
    if run.ended_at:
        events.append(
            {
                "run_id": run.run_id,
                "subagent_name": run.subagent_name,
                "type": f"run_{run.status.value}",
                "status": run.status.value,
                "timestamp": run.ended_at.isoformat(),
            }
        )
    if not include_announce:
        return events
    _timeline_append_announce_events(events, run)
    _timeline_append_ack_events(events, run)
    return events


def _timeline_append_announce_events(
    events: list[dict[str, Any]],
    run: SubAgentRun,
) -> None:
    """Append announce retry/giveup events from run metadata."""
    announce_events = run.metadata.get("announce_events")
    if not isinstance(announce_events, list):
        return
    fallback_ts = run.started_at or run.created_at
    for item in announce_events:
        if not isinstance(item, dict):
            continue
        announce_type = str(item.get("type") or "unknown").strip() or "unknown"
        timestamp = str(item.get("timestamp") or fallback_ts.isoformat())
        payload: dict[str, Any] = {
            str(key): value for key, value in item.items() if key not in {"type", "timestamp"}
        }
        events.append(
            {
                "run_id": run.run_id,
                "subagent_name": run.subagent_name,
                "type": f"announce_{announce_type}",
                "status": run.status.value,
                "timestamp": timestamp,
                "data": payload,
            }
        )


def _timeline_append_ack_events(
    events: list[dict[str, Any]],
    run: SubAgentRun,
) -> None:
    """Append ack events from run metadata."""
    ack_events = run.metadata.get("ack_events")
    if not isinstance(ack_events, list):
        return
    fallback_ts = run.started_at or run.created_at
    for item in ack_events:
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("timestamp") or fallback_ts.isoformat())
        payload: dict[str, Any] = {
            str(key): value for key, value in item.items() if key not in {"type", "timestamp"}
        }
        events.append(
            {
                "run_id": run.run_id,
                "subagent_name": run.subagent_name,
                "type": "run_acknowledged",
                "status": run.status.value,
                "timestamp": timestamp,
                "data": payload,
            }
        )


@tool_define(
    name="sessions_timeline_v2",
    description="Replay run lifecycle timeline and announce history by run_id.",
    parameters={
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Root run id to replay.",
            },
            "include_descendants": {
                "type": "boolean",
                "description": ("Include descendant runs in timeline replay."),
                "default": False,
            },
            "include_announce": {
                "type": "boolean",
                "description": ("Include announce retry/giveup events from metadata."),
                "default": True,
            },
        },
        "required": ["run_id"],
    },
    category="subagent",
    tags=frozenset({"subagent", "timeline"}),
)
async def sessions_timeline_tool(
    ctx: ToolContext,
    *,
    run_id: str = "",
    include_descendants: bool = False,
    include_announce: bool = True,
) -> ToolResult:
    """Replay lifecycle timeline for a run."""
    _ = ctx
    if _sess_run_registry is None:
        return ToolResult(
            output="Error: session tools are not configured.",
            is_error=True,
        )
    if not run_id:
        return ToolResult(output="Error: run_id is required", is_error=True)
    root_run = _sess_run_registry.get_run(_sess_conversation_id, run_id)
    if not root_run:
        return ToolResult(
            output=f"Error: run_id '{run_id}' not found",
            is_error=True,
        )
    runs: dict[str, SubAgentRun] = {root_run.run_id: root_run}
    if include_descendants:
        descendants = _sess_run_registry.list_descendant_runs(
            _sess_conversation_id,
            run_id,
            include_terminal=True,
        )
        for desc_run in descendants:
            runs[desc_run.run_id] = desc_run
    all_events: list[dict[str, Any]] = []
    for r in runs.values():
        all_events.extend(_timeline_events_for_run(r, include_announce=include_announce))
    all_events.sort(key=lambda item: item.get("timestamp") or "")
    output = json.dumps(
        {
            "conversation_id": _sess_conversation_id,
            "root_run_id": run_id,
            "run_count": len(runs),
            "event_count": len(all_events),
            "events": all_events,
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolResult(output=output)


# ---------------------------------------------------------------------------
# @tool_define migrations: sessions_overview, sessions_wait, sessions_ack
# ---------------------------------------------------------------------------

# -- DI state for sessions_overview_tool --

_sess_overview_run_registry: SubAgentRunRegistry | None = None
_sess_overview_conversation_id: str = ""
_sess_overview_requester_session_key: str = ""
_sess_overview_visibility_default: str = "tree"
_sess_overview_observability_provider: Callable[[], dict[str, Any]] | None = None


def configure_sessions_overview(
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    requester_session_key: str | None = None,
    visibility_default: str = "tree",
    observability_provider: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Configure DI state for sessions_overview_tool."""
    global _sess_overview_run_registry
    global _sess_overview_conversation_id
    global _sess_overview_requester_session_key
    global _sess_overview_visibility_default
    global _sess_overview_observability_provider
    _sess_overview_run_registry = run_registry
    _sess_overview_conversation_id = conversation_id
    _sess_overview_requester_session_key = (requester_session_key or conversation_id).strip()
    valid = {"self", "tree", "all"}
    _sess_overview_visibility_default = (
        visibility_default if visibility_default in valid else "tree"
    )
    _sess_overview_observability_provider = observability_provider


# -- DI state for sessions_wait_tool --

_sess_wait_run_registry: SubAgentRunRegistry | None = None
_sess_wait_conversation_id: str = ""


def configure_sessions_wait(
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
) -> None:
    """Configure DI state for sessions_wait_tool."""
    global _sess_wait_run_registry, _sess_wait_conversation_id
    _sess_wait_run_registry = run_registry
    _sess_wait_conversation_id = conversation_id


# -- DI state for sessions_ack_tool --

_sess_ack_run_registry: SubAgentRunRegistry | None = None
_sess_ack_conversation_id: str = ""
_sess_ack_requester_session_key: str = ""


def configure_sessions_ack(
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    requester_session_key: str | None = None,
) -> None:
    """Configure DI state for sessions_ack_tool."""
    global _sess_ack_run_registry
    global _sess_ack_conversation_id
    global _sess_ack_requester_session_key
    _sess_ack_run_registry = run_registry
    _sess_ack_conversation_id = conversation_id
    _sess_ack_requester_session_key = (requester_session_key or conversation_id).strip()


# -- Shared constants --

_TERMINAL_STATUSES: set[SubAgentRunStatus] = {
    SubAgentRunStatus.COMPLETED,
    SubAgentRunStatus.FAILED,
    SubAgentRunStatus.CANCELLED,
    SubAgentRunStatus.TIMED_OUT,
}


# ---------------------------------------------------------------------------
# Helper functions for sessions_overview_tool (C901 compliance)
# ---------------------------------------------------------------------------


def _overview_collect_error_stats(
    run: SubAgentRun,
    error_counts: dict[str, int],
) -> None:
    """Collect error counts from a single run."""
    fail_statuses = {
        SubAgentRunStatus.FAILED,
        SubAgentRunStatus.TIMED_OUT,
        SubAgentRunStatus.CANCELLED,
    }
    if run.status in fail_statuses and run.error:
        error_counts[run.error] = error_counts.get(run.error, 0) + 1


def _overview_collect_announce_stats(run: SubAgentRun) -> dict[str, int]:
    """Collect announce event counts from a single run."""
    retry = 0
    giveup = 0
    delivered = 0
    dropped = int(run.metadata.get("announce_events_dropped") or 0)
    announce_events = run.metadata.get("announce_events")
    if isinstance(announce_events, list):
        for event in announce_events:
            if not isinstance(event, dict):
                continue
            etype = str(event.get("type") or "").strip().lower()
            if etype in {"retry", "completion_retry"}:
                retry += 1
            elif etype in {"giveup", "completion_giveup"}:
                giveup += 1
            elif etype == "completion_delivered":
                delivered += 1
    return {"retry": retry, "giveup": giveup, "delivered": delivered, "dropped": dropped}


def _overview_collect_archive_lag(
    run: SubAgentRun,
    retention_seconds: int,
    now: datetime,
    archive_lag_values: list[int],
) -> None:
    """Collect archive lag value for a terminal run."""
    if retention_seconds > 0:
        terminal_at = run.ended_at or run.created_at
        lag_ms = int((now - terminal_at).total_seconds() * 1000) - (retention_seconds * 1000)
        if lag_ms > 0:
            archive_lag_values.append(lag_ms)


def _overview_collect_run_stats(
    runs: list[SubAgentRun],
    retention_seconds: int,
) -> dict[str, Any]:
    """Collect aggregate statistics from all runs."""
    status_counts: dict[str, int] = {s.value: 0 for s in SubAgentRunStatus}
    subagent_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    announce_retry = 0
    announce_giveup = 0
    announce_delivered = 0
    announce_dropped = 0
    announce_backlog = 0
    lane_wait_values: list[int] = []
    archive_lag_values: list[int] = []
    now = datetime.now(UTC)
    for run in runs:
        status_counts[run.status.value] = status_counts.get(run.status.value, 0) + 1
        subagent_counts[run.subagent_name] = subagent_counts.get(run.subagent_name, 0) + 1
        _overview_collect_error_stats(run, error_counts)
        astats = _overview_collect_announce_stats(run)
        announce_retry += astats["retry"]
        announce_giveup += astats["giveup"]
        announce_delivered += astats["delivered"]
        announce_dropped += astats["dropped"]
        if run.status in _TERMINAL_STATUSES:
            ann_status = str(run.metadata.get("announce_status") or "").strip().lower()
            if ann_status not in {"delivered", "giveup"}:
                announce_backlog += 1
            _overview_collect_archive_lag(run, retention_seconds, now, archive_lag_values)
        lane_wait_ms = run.metadata.get("lane_wait_ms")
        if isinstance(lane_wait_ms, (int, float)):
            lane_wait_values.append(int(lane_wait_ms))
    return {
        "status_counts": status_counts,
        "subagent_counts": subagent_counts,
        "error_counts": error_counts,
        "announce_retry": announce_retry,
        "announce_giveup": announce_giveup,
        "announce_delivered": announce_delivered,
        "announce_dropped": announce_dropped,
        "announce_backlog": announce_backlog,
        "lane_wait_values": lane_wait_values,
        "archive_lag_values": archive_lag_values,
    }


def _overview_get_hook_failures(
    provider: Callable[[], dict[str, Any]] | None,
) -> int:
    """Get hook failure count from observability provider."""
    if not provider:
        return 0
    try:
        stats = provider()
        if isinstance(stats, dict):
            return int(stats.get("hook_failures") or 0)
    except Exception:
        pass
    return 0


def _overview_build_response(
    conversation_id: str,
    visibility: str,
    runs: list[SubAgentRun],
    stats: dict[str, Any],
    hook_failures: int,
) -> str:
    """Build the JSON overview response."""
    status_counts: dict[str, int] = stats["status_counts"]
    active_runs = status_counts.get(SubAgentRunStatus.PENDING.value, 0) + status_counts.get(
        SubAgentRunStatus.RUNNING.value, 0
    )
    by_subagent = [
        {"subagent_name": name, "count": count}
        for name, count in sorted(
            stats["subagent_counts"].items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    error_hotspots = [
        {"error": error, "count": count}
        for error, count in sorted(
            stats["error_counts"].items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]
    lwv = stats["lane_wait_values"]
    lane_wait_summary = {
        "sample_count": len(lwv),
        "avg": int(sum(lwv) / len(lwv)) if lwv else 0,
        "max": max(lwv) if lwv else 0,
    }
    alv = stats["archive_lag_values"]
    archive_lag_summary = {
        "stale_count": len(alv),
        "avg": int(sum(alv) / len(alv)) if alv else 0,
        "max": max(alv) if alv else 0,
    }
    return json.dumps(
        {
            "conversation_id": conversation_id,
            "visibility": visibility,
            "total_runs": len(runs),
            "active_runs": active_runs,
            "status_counts": status_counts,
            "by_subagent": by_subagent,
            "announce_summary": {
                "retry_count": stats["announce_retry"],
                "giveup_count": stats["announce_giveup"],
                "delivered_count": stats["announce_delivered"],
                "dropped_count": stats["announce_dropped"],
                "backlog_count": stats["announce_backlog"],
            },
            "archive_lag_ms": archive_lag_summary,
            "hook_failures": hook_failures,
            "lane_wait_ms": lane_wait_summary,
            "error_hotspots": error_hotspots,
        },
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# sessions_overview_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_overview",
    description=(
        "Show run observability summary including status counts, "
        "error hotspots, announce retry/giveup stats, lane wait, "
        "and archive lag for SubAgent runs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "visibility": {
                "type": "string",
                "description": "Run visibility boundary.",
                "enum": ["self", "tree", "all"],
            },
        },
        "required": [],
    },
    category="subagent",
    tags=frozenset({"subagent", "session", "observability"}),
)
async def sessions_overview_tool(
    ctx: ToolContext,
    *,
    visibility: str = "",
) -> ToolResult:
    """Show run observability summary for SubAgent runs."""
    registry = _sess_overview_run_registry
    if registry is None:
        return ToolResult(
            output="Error: sessions_overview not configured",
            is_error=True,
        )
    conv_id = _sess_overview_conversation_id
    req_key = _sess_overview_requester_session_key
    vis = (visibility or _sess_overview_visibility_default).strip().lower()
    if vis not in {"self", "tree", "all"}:
        return ToolResult(
            output=f"Error: invalid visibility '{vis}'",
            is_error=True,
        )
    runs = registry.list_runs_for_requester(conv_id, req_key, visibility=vis)
    retention = max(int(registry.terminal_retention_seconds), 0)
    stats = _overview_collect_run_stats(runs, retention)
    hook_failures = _overview_get_hook_failures(
        _sess_overview_observability_provider,
    )
    output = _overview_build_response(conv_id, vis, runs, stats, hook_failures)
    return ToolResult(output=output, title="Sessions Overview")


# ---------------------------------------------------------------------------
# sessions_wait_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_wait",
    description=("Wait for a SubAgent run to reach terminal status and return latest state."),
    parameters={
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Run id to wait for.",
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Maximum wait duration in seconds.",
                "minimum": 0,
                "maximum": 3600,
            },
            "poll_interval_ms": {
                "type": "integer",
                "description": "Polling interval in milliseconds.",
                "minimum": 10,
                "maximum": 5000,
            },
        },
        "required": ["run_id"],
    },
    category="subagent",
    tags=frozenset({"subagent", "session", "wait"}),
)
async def sessions_wait_tool(
    ctx: ToolContext,
    *,
    run_id: str,
    timeout_seconds: float = 30,
    poll_interval_ms: int = 200,
) -> ToolResult:
    """Wait for a SubAgent run to complete or timeout."""
    registry = _sess_wait_run_registry
    if registry is None:
        return ToolResult(
            output="Error: sessions_wait not configured",
            is_error=True,
        )
    conv_id = _sess_wait_conversation_id
    if not run_id:
        return ToolResult(output="Error: run_id is required", is_error=True)
    try:
        timeout = max(0.0, float(timeout_seconds))
    except (TypeError, ValueError):
        timeout = 30.0
    try:
        poll_interval = max(0.01, int(poll_interval_ms) / 1000)
    except (TypeError, ValueError):
        poll_interval = 0.2

    started_at = datetime.now(UTC)
    while True:
        run = registry.get_run(conv_id, run_id)
        if not run:
            return ToolResult(
                output=f"Error: run_id '{run_id}' not found",
                is_error=True,
            )
        elapsed = (datetime.now(UTC) - started_at).total_seconds()
        is_terminal = run.status in _TERMINAL_STATUSES
        if is_terminal or elapsed >= timeout:
            return _wait_build_result(conv_id, run, is_terminal, elapsed, timeout)
        await asyncio.sleep(poll_interval)


def _wait_build_result(
    conversation_id: str,
    run: SubAgentRun,
    is_terminal: bool,
    elapsed: float,
    timeout: float,
) -> ToolResult:
    """Build the wait result JSON."""
    announce_payload = run.metadata.get("announce_payload")
    if not isinstance(announce_payload, dict):
        announce_payload = None
    output = json.dumps(
        {
            "conversation_id": conversation_id,
            "run": run.to_event_data(),
            "is_terminal": is_terminal,
            "timed_out": not is_terminal and elapsed >= timeout,
            "waited_ms": int(elapsed * 1000),
            "announce": {
                "status": str(run.metadata.get("announce_status") or "").strip() or None,
                "attempt_count": int(run.metadata.get("announce_attempt_count") or 0),
                "last_error": str(run.metadata.get("announce_last_error") or "").strip() or None,
                "payload": announce_payload,
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolResult(output=output, title=f"Wait: {run.run_id}")


# ---------------------------------------------------------------------------
# sessions_ack_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_ack",
    description=("Acknowledge a terminal SubAgent run and record ack metadata."),
    parameters={
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Run id to acknowledge.",
            },
            "note": {
                "type": "string",
                "description": "Optional acknowledgement note.",
                "maxLength": 500,
            },
        },
        "required": ["run_id"],
    },
    category="subagent",
    tags=frozenset({"subagent", "session", "ack"}),
)
async def sessions_ack_tool(
    ctx: ToolContext,
    *,
    run_id: str,
    note: str = "",
) -> ToolResult:
    """Acknowledge a terminal SubAgent run."""
    registry = _sess_ack_run_registry
    if registry is None:
        return ToolResult(
            output="Error: sessions_ack not configured",
            is_error=True,
        )
    conv_id = _sess_ack_conversation_id
    req_key = _sess_ack_requester_session_key
    if not run_id:
        return ToolResult(output="Error: run_id is required", is_error=True)
    run = registry.get_run(conv_id, run_id)
    if not run:
        return ToolResult(
            output=f"Error: run_id '{run_id}' not found",
            is_error=True,
        )
    if run.status not in _TERMINAL_STATUSES:
        return ToolResult(
            output=(
                f"Error: run_id '{run_id}' status "
                f"'{run.status.value}' is not terminal. "
                "Use sessions_wait first."
            ),
            is_error=True,
        )

    ack_events: list[dict[str, Any]] = _ack_prepare_events(run)
    ack_event: dict[str, Any] = {
        "type": "ack",
        "timestamp": datetime.now(UTC).isoformat(),
        "requester_session_key": req_key,
    }
    if note and note.strip():
        ack_event["note"] = note.strip()[:500]
    ack_events.append(ack_event)

    updated = registry.attach_metadata(
        conv_id,
        run_id,
        {
            "ack_events": ack_events,
            "last_ack_by": req_key,
            "last_ack_at": ack_event["timestamp"],
        },
        expected_statuses=list(_TERMINAL_STATUSES),
    )
    if not updated:
        return ToolResult(
            output=(f"Error: run_id '{run_id}' changed while acknowledging, please retry."),
            is_error=True,
        )
    return ToolResult(
        output=json.dumps(
            {
                "conversation_id": conv_id,
                "run_id": run_id,
                "acknowledged": True,
                "status": updated.status.value,
                "ack_count": len(ack_events),
            },
            ensure_ascii=False,
            indent=2,
        ),
        title=f"Ack: {run_id}",
    )


def _ack_prepare_events(run: SubAgentRun) -> list[dict[str, Any]]:
    """Prepare ack_events list from run metadata, bounded to 20."""
    raw = run.metadata.get("ack_events")
    ack_events: list[dict[str, Any]]
    if isinstance(raw, list):
        ack_events = [e for e in raw if isinstance(e, dict)]
    else:
        ack_events = []
    if len(ack_events) >= 20:
        ack_events = ack_events[-19:]
    return ack_events


# ---------------------------------------------------------------------------
# @tool_define decorator-based session tools (migrate batch 2 of 2)
# sessions_send_tool + subagents_control_tool
# ---------------------------------------------------------------------------


# -- DI state for sessions_send_tool --

_sess_send_run_registry: SubAgentRunRegistry | None = None
_sess_send_conversation_id: str = ""
_sess_send_spawn_callback: Callable[..., Awaitable[str]] | None = None
_sess_send_max_active_runs: int = 16
_sess_send_max_active_runs_per_lineage: int = 16
_sess_send_max_children_per_requester: int = 16
_sess_send_requester_session_key: str = ""
_sess_send_delegation_depth: int = 0
_sess_send_max_delegation_depth: int = 1
_sess_send_max_spawn_retries: int = 2
_sess_send_retry_delay_ms: int = 200
_sess_send_spawn_callback_params: set[str] | None = None
_sess_send_spawn_callback_accepts_kwargs: bool = True


def configure_sessions_send(
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    spawn_callback: Callable[..., Awaitable[str]] | None = None,
    *,
    max_active_runs: int = 16,
    max_active_runs_per_lineage: int | None = None,
    max_children_per_requester: int | None = None,
    requester_session_key: str | None = None,
    delegation_depth: int = 0,
    max_delegation_depth: int = 1,
    max_spawn_retries: int = 2,
    retry_delay_ms: int = 200,
) -> None:
    """Configure DI state for sessions_send_tool."""
    global _sess_send_run_registry
    global _sess_send_conversation_id
    global _sess_send_spawn_callback
    global _sess_send_max_active_runs
    global _sess_send_max_active_runs_per_lineage
    global _sess_send_max_children_per_requester
    global _sess_send_requester_session_key
    global _sess_send_delegation_depth
    global _sess_send_max_delegation_depth
    global _sess_send_max_spawn_retries
    global _sess_send_retry_delay_ms
    global _sess_send_spawn_callback_params
    global _sess_send_spawn_callback_accepts_kwargs
    _sess_send_run_registry = run_registry
    _sess_send_conversation_id = conversation_id
    _sess_send_spawn_callback = spawn_callback
    _sess_send_max_active_runs = max(1, max_active_runs)
    _sess_send_max_active_runs_per_lineage = max(1, max_active_runs_per_lineage or max_active_runs)
    _sess_send_max_children_per_requester = max(1, max_children_per_requester or max_active_runs)
    _sess_send_requester_session_key = (requester_session_key or conversation_id).strip()
    _sess_send_delegation_depth = delegation_depth
    _sess_send_max_delegation_depth = max(1, max_delegation_depth)
    _sess_send_max_spawn_retries = max(0, max_spawn_retries)
    _sess_send_retry_delay_ms = max(1, retry_delay_ms)
    if spawn_callback is not None:
        params, accepts_kw = _resolve_spawn_callback_signature(spawn_callback)
        _sess_send_spawn_callback_params = params
        _sess_send_spawn_callback_accepts_kwargs = accepts_kw
    else:
        _sess_send_spawn_callback_params = None
        _sess_send_spawn_callback_accepts_kwargs = True


# ---------------------------------------------------------------------------
# sessions_send helpers
# ---------------------------------------------------------------------------


def _send_validate_params(
    run_id: str, task: str, run_timeout_seconds: int
) -> tuple[str | None, int]:
    """Validate send parameters. Returns (error_message, timeout_seconds)."""
    if not run_id:
        return "Error: run_id is required", 0
    if not task or not task.strip():
        return "Error: task is required", 0
    if _sess_send_delegation_depth >= _sess_send_max_delegation_depth:
        return (
            "Error: sessions_send is disabled at current delegation depth "
            f"({_sess_send_delegation_depth}/{_sess_send_max_delegation_depth})"
        ), 0
    try:
        timeout_seconds = max(0, int(run_timeout_seconds or 0))
    except (TypeError, ValueError):
        timeout_seconds = 0
    return None, timeout_seconds


def _send_check_capacity(lineage_root_run_id: str) -> str | None:
    """Check capacity limits for send. Returns error or None."""
    assert _sess_send_run_registry is not None
    active_runs = _sess_send_run_registry.count_active_runs(_sess_send_conversation_id)
    if active_runs >= _sess_send_max_active_runs:
        return (
            f"Error: active SubAgent sessions limit reached "
            f"({active_runs}/{_sess_send_max_active_runs})"
        )
    requester_runs = _sess_send_run_registry.count_active_runs_for_requester(
        _sess_send_conversation_id, _sess_send_requester_session_key
    )
    if requester_runs >= _sess_send_max_children_per_requester:
        return (
            "Error: requester SubAgent sessions limit reached "
            f"({requester_runs}/{_sess_send_max_children_per_requester})"
        )
    lineage_active = _sess_send_run_registry.count_active_runs_for_lineage(
        _sess_send_conversation_id, lineage_root_run_id
    )
    if lineage_active >= _sess_send_max_active_runs_per_lineage:
        return (
            "Error: lineage SubAgent sessions limit reached "
            f"({lineage_active}/{_sess_send_max_active_runs_per_lineage})"
        )
    return None


def _send_build_follow_up_options(parent_run: SubAgentRun, timeout_seconds: int) -> dict[str, Any]:
    """Build spawn options from parent run metadata."""
    try:
        parent_timeout = int(parent_run.metadata.get("run_timeout_seconds") or 0)
    except (TypeError, ValueError):
        parent_timeout = 0
    return {
        "spawn_mode": str(parent_run.metadata.get("spawn_mode") or "run"),
        "thread_requested": bool(parent_run.metadata.get("thread_requested")),
        "cleanup": str(parent_run.metadata.get("cleanup") or "keep"),
        "agent_id": str(parent_run.metadata.get("agent_id") or parent_run.subagent_name),
        "model": (
            str(parent_run.metadata.get("model") or "").strip()
            or str(parent_run.metadata.get("model_override") or "").strip()
            or None
        ),
        "thinking": (
            str(parent_run.metadata.get("thinking") or "").strip()
            or str(parent_run.metadata.get("thinking_override") or "").strip()
            or None
        ),
        "requester_session_key": _sess_send_requester_session_key,
        "run_timeout_seconds": timeout_seconds or parent_timeout,
    }


async def _send_invoke_spawn(
    subagent_name: str,
    task: str,
    run_id: str,
    spawn_options: dict[str, Any],
) -> str:
    """Invoke spawn callback with filtered options."""
    assert _sess_send_spawn_callback is not None
    filtered = _filter_spawn_options(
        spawn_options,
        _sess_send_spawn_callback_params,
        _sess_send_spawn_callback_accepts_kwargs,
    )
    return await _sess_send_spawn_callback(subagent_name, task, run_id, **filtered)


async def _send_spawn_with_retry(
    ctx: ToolContext,
    run_id: str,
    subagent_name: str,
    task: str,
    spawn_options: dict[str, Any],
) -> int:
    """Retry spawn callback, emitting events via ctx."""
    assert _sess_send_run_registry is not None
    last_error: Exception | None = None
    for attempt in range(_sess_send_max_spawn_retries + 1):
        try:
            await _send_invoke_spawn(
                subagent_name=subagent_name,
                task=task,
                run_id=run_id,
                spawn_options=spawn_options,
            )
            return attempt
        except Exception as exc:
            last_error = exc
            if attempt >= _sess_send_max_spawn_retries:
                break
            await ctx.emit(
                {
                    "type": "subagent_announce_retry",
                    "data": {
                        "conversation_id": _sess_send_conversation_id,
                        "run_id": run_id,
                        "subagent_name": subagent_name,
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "next_delay_ms": _sess_send_retry_delay_ms,
                    },
                }
            )
            _record_announce_event(
                run_registry=_sess_send_run_registry,
                conversation_id=_sess_send_conversation_id,
                run_id=run_id,
                event_type="retry",
                payload={
                    "attempt": attempt + 1,
                    "error": str(exc),
                    "next_delay_ms": _sess_send_retry_delay_ms,
                },
            )
            await asyncio.sleep(_sess_send_retry_delay_ms / 1000)

    await ctx.emit(
        {
            "type": "subagent_announce_giveup",
            "data": {
                "conversation_id": _sess_send_conversation_id,
                "run_id": run_id,
                "subagent_name": subagent_name,
                "attempts": _sess_send_max_spawn_retries + 1,
                "error": str(last_error) if last_error else "unknown error",
            },
        }
    )
    _record_announce_event(
        run_registry=_sess_send_run_registry,
        conversation_id=_sess_send_conversation_id,
        run_id=run_id,
        event_type="giveup",
        payload={
            "attempts": _sess_send_max_spawn_retries + 1,
            "error": str(last_error) if last_error else "unknown error",
        },
    )
    if last_error:
        raise last_error
    raise RuntimeError("failed to send follow-up")


# ---------------------------------------------------------------------------
# 5. sessions_send_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="sessions_send_v2",
    description=(
        "Send a follow-up task to an existing SubAgent session lineage "
        "by run_id. Creates a new child run with parent_run_id metadata."
    ),
    parameters={
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Existing run id to follow up.",
            },
            "task": {
                "type": "string",
                "description": "Follow-up task content.",
            },
            "run_timeout_seconds": {
                "type": "integer",
                "description": ("Optional timeout for follow-up run (0 means no timeout)."),
                "minimum": 0,
                "maximum": 3600,
            },
        },
        "required": ["run_id", "task"],
    },
    category="subagent",
    tags=frozenset({"subagent", "send"}),
)
async def sessions_send_tool(
    ctx: ToolContext,
    *,
    run_id: str = "",
    task: str = "",
    run_timeout_seconds: int = 0,
) -> ToolResult:
    """Send follow-up work to an existing SubAgent lineage."""
    registry = _sess_send_run_registry
    if registry is None or _sess_send_spawn_callback is None:
        return ToolResult(
            output="Error: sessions_send not configured",
            is_error=True,
        )
    conv_id = _sess_send_conversation_id
    error, timeout_seconds = _send_validate_params(run_id, task, run_timeout_seconds)
    if error:
        if "delegation depth" in error:
            await ctx.emit(
                dict(
                    SubAgentDepthLimitedEvent(
                        subagent_name="",
                        current_depth=_sess_send_delegation_depth,
                        max_depth=_sess_send_max_delegation_depth,
                    ).to_event_dict()
                )
            )
        return ToolResult(output=error, is_error=True)
    parent_run = registry.get_run(conv_id, run_id)
    if not parent_run:
        return ToolResult(
            output=f"Error: run_id '{run_id}' not found",
            is_error=True,
        )
    lineage_root_run_id = str(parent_run.metadata.get("lineage_root_run_id") or run_id).strip()
    capacity_error = _send_check_capacity(lineage_root_run_id)
    if capacity_error:
        return ToolResult(output=capacity_error, is_error=True)
    follow_up_options = _send_build_follow_up_options(parent_run, timeout_seconds)
    child_run = registry.create_run(
        conversation_id=conv_id,
        subagent_name=parent_run.subagent_name,
        task=task,
        metadata=_build_lifecycle_metadata(
            session_mode="send",
            requester_session_key=_sess_send_requester_session_key,
            parent_run_id=run_id,
            lineage_root_run_id=lineage_root_run_id,
            delegation_depth=_sess_send_delegation_depth,
            extra={
                **follow_up_options,
                "max_active_runs_per_lineage": (_sess_send_max_active_runs_per_lineage),
            },
        ),
        requester_session_key=_sess_send_requester_session_key,
        parent_run_id=run_id,
        lineage_root_run_id=lineage_root_run_id,
    )
    running = registry.mark_running(conv_id, child_run.run_id)
    if running:
        await ctx.emit({"type": "subagent_started", "data": running.to_event_data()})
    try:
        retry_count = await _send_spawn_with_retry(
            ctx,
            run_id=child_run.run_id,
            subagent_name=parent_run.subagent_name,
            task=task,
            spawn_options=follow_up_options,
        )
        if retry_count > 0:
            _ = registry.attach_metadata(
                conv_id,
                child_run.run_id,
                {"announce_retry_count": retry_count},
            )
        await ctx.emit(
            {
                "type": "subagent_session_message_sent",
                "data": {
                    "conversation_id": conv_id,
                    "parent_run_id": run_id,
                    "run_id": child_run.run_id,
                    "subagent_name": parent_run.subagent_name,
                },
            }
        )
        return ToolResult(
            output=(
                f"Follow-up dispatched as run {child_run.run_id} "
                f"to SubAgent '{parent_run.subagent_name}'."
            ),
            title=f"Send: {child_run.run_id}",
        )
    except Exception as exc:
        failed = registry.mark_failed(
            conversation_id=conv_id,
            run_id=child_run.run_id,
            error=str(exc),
        )
        if failed:
            await ctx.emit({"type": "subagent_failed", "data": failed.to_event_data()})
        return ToolResult(
            output=f"Error: failed to send follow-up: {exc}",
            is_error=True,
        )


# ---------------------------------------------------------------------------
# DI state for subagents_control_tool
# ---------------------------------------------------------------------------

_ctrl_run_registry: SubAgentRunRegistry | None = None
_ctrl_conversation_id: str = ""
_ctrl_subagent_names: list[str] = []
_ctrl_subagent_descriptions: dict[str, str] = {}
_ctrl_cancel_callback: Callable[[str], Awaitable[bool]] | None = None
_ctrl_restart_callback: Callable[[str, str, str], Awaitable[str]] | None = None
_ctrl_control_channel: ControlChannelPort | None = None
_ctrl_steer_rate_limit_ms: int = 2000
_ctrl_max_active_runs: int = 16
_ctrl_max_active_runs_per_lineage: int = 16
_ctrl_max_children_per_requester: int = 16
_ctrl_requester_session_key: str = ""
_ctrl_delegation_depth: int = 0
_ctrl_max_delegation_depth: int = 1
_ctrl_last_steer_at: dict[str, datetime] = {}
_ctrl_spawn_callback_params: set[str] | None = None
_ctrl_spawn_callback_accepts_kwargs: bool = True


def configure_subagents_control(  # noqa: PLR0913
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    subagent_names: list[str],
    subagent_descriptions: dict[str, str],
    cancel_callback: Callable[[str], Awaitable[bool]],
    *,
    restart_callback: (Callable[[str, str, str], Awaitable[str]] | None) = None,
    control_channel: ControlChannelPort | None = None,
    steer_rate_limit_ms: int = 2000,
    max_active_runs: int = 16,
    max_active_runs_per_lineage: int | None = None,
    max_children_per_requester: int | None = None,
    requester_session_key: str | None = None,
    delegation_depth: int = 0,
    max_delegation_depth: int = 1,
) -> None:
    """Configure DI state for subagents_control_tool."""
    global _ctrl_run_registry
    global _ctrl_conversation_id
    global _ctrl_subagent_names
    global _ctrl_subagent_descriptions
    global _ctrl_cancel_callback
    global _ctrl_restart_callback
    global _ctrl_control_channel
    global _ctrl_steer_rate_limit_ms
    global _ctrl_max_active_runs
    global _ctrl_max_active_runs_per_lineage
    global _ctrl_max_children_per_requester
    global _ctrl_requester_session_key
    global _ctrl_delegation_depth
    global _ctrl_max_delegation_depth
    global _ctrl_last_steer_at
    global _ctrl_spawn_callback_params
    global _ctrl_spawn_callback_accepts_kwargs
    _ctrl_run_registry = run_registry
    _ctrl_conversation_id = conversation_id
    _ctrl_subagent_names = subagent_names
    _ctrl_subagent_descriptions = subagent_descriptions
    _ctrl_cancel_callback = cancel_callback
    _ctrl_restart_callback = restart_callback
    _ctrl_control_channel = control_channel
    _ctrl_steer_rate_limit_ms = max(1, steer_rate_limit_ms)
    _ctrl_max_active_runs = max(1, max_active_runs)
    _ctrl_max_active_runs_per_lineage = max(1, max_active_runs_per_lineage or max_active_runs)
    _ctrl_max_children_per_requester = max(1, max_children_per_requester or max_active_runs)
    _ctrl_requester_session_key = (requester_session_key or conversation_id).strip()
    _ctrl_delegation_depth = delegation_depth
    _ctrl_max_delegation_depth = max(1, max_delegation_depth)
    _ctrl_last_steer_at = {}
    if restart_callback is not None:
        params, accepts_kw = _resolve_spawn_callback_signature(restart_callback)
        _ctrl_spawn_callback_params = params
        _ctrl_spawn_callback_accepts_kwargs = accepts_kw
    else:
        _ctrl_spawn_callback_params = None
        _ctrl_spawn_callback_accepts_kwargs = True


# ---------------------------------------------------------------------------
# subagents_control helpers
# ---------------------------------------------------------------------------

_CTRL_ACTIVE_STATUSES: set[SubAgentRunStatus] = {
    SubAgentRunStatus.PENDING,
    SubAgentRunStatus.RUNNING,
}


def _ctrl_run_label(run: SubAgentRun) -> str | None:
    """Extract label from run metadata."""
    for key in ("label", "run_label", "session_label"):
        value = str(run.metadata.get(key) or "").strip()
        if value:
            return value
    return None


def _ctrl_resolve_target_token(run_id: str, target: str) -> str:
    """Resolve target token from run_id and target params."""
    return (target or run_id).strip()


def _ctrl_resolve_by_index(
    raw_index_str: str,
) -> tuple[list[SubAgentRun], str | None]:
    """Resolve target by index (#N or index:N)."""
    assert _ctrl_run_registry is not None
    try:
        resolved_index = int(raw_index_str)
    except (TypeError, ValueError):
        return [], f"Error: invalid target index '{raw_index_str}'"
    if resolved_index <= 0:
        return [], "Error: target index must be >= 1"
    active_runs = _ctrl_run_registry.list_runs(
        _ctrl_conversation_id,
        statuses=list(_CTRL_ACTIVE_STATUSES),
    )
    if resolved_index > len(active_runs):
        return (
            [],
            f"Error: target index #{resolved_index} out of range",
        )
    return [active_runs[resolved_index - 1]], None


def _ctrl_resolve_by_label(
    label: str, include_terminal: bool
) -> tuple[list[SubAgentRun], str | None]:
    """Resolve target by label."""
    assert _ctrl_run_registry is not None
    if not label:
        return [], "Error: label selector requires a non-empty value"
    statuses = None if include_terminal else list(_CTRL_ACTIVE_STATUSES)
    runs = _ctrl_run_registry.list_runs(_ctrl_conversation_id, statuses=statuses)
    matched = [run for run in runs if (_ctrl_run_label(run) or "") == label]
    if not matched:
        return [], f"Error: no runs found for label '{label}'"
    return matched, None


def _ctrl_resolve_target_runs(
    target_token: str,
    *,
    include_terminal: bool,
) -> tuple[list[SubAgentRun], str | None]:
    """Resolve target selector to a list of runs."""
    assert _ctrl_run_registry is not None
    token = target_token.strip()
    if not token:
        return [], "Error: target (or run_id) is required"
    if token.lower() == "all":
        statuses = None if include_terminal else list(_CTRL_ACTIVE_STATUSES)
        runs = _ctrl_run_registry.list_runs(_ctrl_conversation_id, statuses=statuses)
        return runs, None
    if token.startswith("#") or token.lower().startswith("index:"):
        raw_idx = token[1:] if token.startswith("#") else token.split(":", 1)[1]
        return _ctrl_resolve_by_index(raw_idx)
    if token.lower().startswith("label:"):
        return _ctrl_resolve_by_label(token.split(":", 1)[1].strip(), include_terminal)
    run = _ctrl_run_registry.get_run(_ctrl_conversation_id, token)
    if not run:
        return [], f"Error: run_id '{token}' not found"
    return [run], None


def _ctrl_serialize_run_snapshot(
    run: SubAgentRun,
) -> dict[str, Any]:
    """Serialize a run to a JSON-serializable dict."""
    return {
        "run_id": run.run_id,
        "subagent_name": run.subagent_name,
        "status": run.status.value,
        "task": run.task,
        "created_at": run.created_at.isoformat(),
        "started_at": (run.started_at.isoformat() if run.started_at else None),
        "ended_at": (run.ended_at.isoformat() if run.ended_at else None),
        "summary": run.summary,
        "error": run.error,
        "execution_time_ms": run.execution_time_ms,
        "tokens_used": run.tokens_used,
        "metadata": dict(run.metadata),
    }


def _ctrl_ensure_mutation_allowed(action_name: str) -> str | None:
    """Check delegation depth permits mutation."""
    if _ctrl_delegation_depth >= _ctrl_max_delegation_depth:
        return (
            f"Error: subagents {action_name} is disabled at "
            "current delegation depth "
            f"({_ctrl_delegation_depth}/{_ctrl_max_delegation_depth})"
        )
    return None


# -- action: list --


def _ctrl_handle_list() -> ToolResult:
    """Handle list action."""
    assert _ctrl_run_registry is not None
    active_runs = _ctrl_run_registry.list_runs(
        _ctrl_conversation_id,
        statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
    )
    snapshots = [
        {
            "index": idx + 1,
            "target": f"#{idx + 1}",
            "run_id": run.run_id,
            "subagent_name": run.subagent_name,
            "status": run.status.value,
            "label": _ctrl_run_label(run),
            "created_at": run.created_at.isoformat(),
        }
        for idx, run in enumerate(active_runs)
    ]
    active_by_name: dict[str, int] = {}
    for run in active_runs:
        active_by_name[run.subagent_name] = active_by_name.get(run.subagent_name, 0) + 1
    return ToolResult(
        output=json.dumps(
            {
                "conversation_id": _ctrl_conversation_id,
                "subagents": [
                    {
                        "name": name,
                        "description": (_ctrl_subagent_descriptions.get(name, "")),
                        "active_runs": (active_by_name.get(name, 0)),
                    }
                    for name in _ctrl_subagent_names
                ],
                "active_run_count": len(active_runs),
                "active_runs": snapshots,
            },
            ensure_ascii=False,
            indent=2,
        ),
        title="SubAgents: list",
    )


# -- action: info --


def _ctrl_handle_info(run_id: str, target: str, include_descendants: bool) -> ToolResult:
    """Handle info action."""
    assert _ctrl_run_registry is not None
    target_token = _ctrl_resolve_target_token(run_id, target)
    matched_runs, error = _ctrl_resolve_target_runs(target_token, include_terminal=True)
    if error:
        return ToolResult(output=error, is_error=True)
    run_by_id: dict[str, SubAgentRun] = {}
    for run in matched_runs:
        run_by_id[run.run_id] = run
        if include_descendants:
            descendants = _ctrl_run_registry.list_descendant_runs(
                _ctrl_conversation_id,
                run.run_id,
                include_terminal=True,
            )
            for desc in descendants:
                run_by_id.setdefault(desc.run_id, desc)
    runs = sorted(run_by_id.values(), key=lambda r: r.created_at)
    return ToolResult(
        output=json.dumps(
            {
                "conversation_id": _ctrl_conversation_id,
                "target": target_token,
                "include_descendants": bool(include_descendants),
                "run_count": len(runs),
                "runs": [_ctrl_serialize_run_snapshot(r) for r in runs],
            },
            ensure_ascii=False,
            indent=2,
        ),
        title=f"SubAgents: info {target_token}",
    )


# -- action: log --


async def _ctrl_handle_log(
    run_id: str,
    target: str,
    include_descendants: bool,
    include_announce: bool,
) -> ToolResult:
    """Handle log action by building timeline from run registry."""
    target_token = _ctrl_resolve_target_token(run_id, target)
    matched_runs, error = _ctrl_resolve_target_runs(target_token, include_terminal=True)
    if error:
        return ToolResult(output=error, is_error=True)
    if len(matched_runs) != 1:
        return ToolResult(
            output=(f"Error: log target '{target_token}' requires exactly one matched run"),
            is_error=True,
        )
    assert _ctrl_run_registry is not None
    matched_run = matched_runs[0]
    runs: dict[str, SubAgentRun] = {matched_run.run_id: matched_run}
    if include_descendants:
        descendants = _ctrl_run_registry.list_descendant_runs(
            _ctrl_conversation_id,
            matched_run.run_id,
            include_terminal=True,
        )
        for desc_run in descendants:
            runs[desc_run.run_id] = desc_run
    all_events: list[dict[str, Any]] = []
    for r in runs.values():
        all_events.extend(_timeline_events_for_run(r, include_announce=include_announce))
    all_events.sort(key=lambda item: item.get("timestamp") or "")
    raw = json.dumps(
        {
            "conversation_id": _ctrl_conversation_id,
            "root_run_id": matched_run.run_id,
            "run_count": len(runs),
            "event_count": len(all_events),
            "events": all_events,
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolResult(
        output=raw,
        title=f"SubAgents: log {target_token}",
    )


# -- action: send --


async def _ctrl_send_dispatch(
    ctx: ToolContext,
    parent_run: SubAgentRun,
    task: str,
    timeout_seconds: int,
) -> ToolResult:
    """Create child run and invoke spawn for send action."""
    assert _ctrl_run_registry is not None
    assert _ctrl_restart_callback is not None
    conv_id = _ctrl_conversation_id
    lineage_root = str(parent_run.metadata.get("lineage_root_run_id") or parent_run.run_id).strip()
    follow_up = _send_build_follow_up_options(parent_run, timeout_seconds)
    follow_up["requester_session_key"] = _ctrl_requester_session_key
    child_run = _ctrl_run_registry.create_run(
        conversation_id=conv_id,
        subagent_name=parent_run.subagent_name,
        task=task,
        metadata=_build_lifecycle_metadata(
            session_mode="send",
            requester_session_key=_ctrl_requester_session_key,
            parent_run_id=parent_run.run_id,
            lineage_root_run_id=lineage_root,
            delegation_depth=_ctrl_delegation_depth,
            extra={
                **follow_up,
                "max_active_runs_per_lineage": (_ctrl_max_active_runs_per_lineage),
            },
        ),
        requester_session_key=_ctrl_requester_session_key,
        parent_run_id=parent_run.run_id,
        lineage_root_run_id=lineage_root,
    )
    running = _ctrl_run_registry.mark_running(conv_id, child_run.run_id)
    if running:
        await ctx.emit({"type": "subagent_started", "data": running.to_event_data()})
    params, accepts_kw = _resolve_spawn_callback_signature(_ctrl_restart_callback)
    filtered = _filter_spawn_options(follow_up, params, accepts_kw)
    try:
        await _ctrl_restart_callback(
            parent_run.subagent_name,
            task,
            child_run.run_id,
            **filtered,
        )
        await ctx.emit(
            {
                "type": "subagent_session_message_sent",
                "data": {
                    "conversation_id": conv_id,
                    "parent_run_id": parent_run.run_id,
                    "run_id": child_run.run_id,
                    "subagent_name": parent_run.subagent_name,
                },
            }
        )
        return ToolResult(
            output=(
                f"Follow-up dispatched as run {child_run.run_id} "
                f"to SubAgent '{parent_run.subagent_name}'."
            ),
            title=f"SubAgents: send {child_run.run_id}",
        )
    except Exception as exc:
        failed = _ctrl_run_registry.mark_failed(
            conversation_id=conv_id,
            run_id=child_run.run_id,
            error=str(exc),
        )
        if failed:
            await ctx.emit({"type": "subagent_failed", "data": failed.to_event_data()})
        return ToolResult(
            output=f"Error: failed to send follow-up: {exc}",
            is_error=True,
        )


async def _ctrl_handle_send(
    ctx: ToolContext,
    run_id: str,
    target: str,
    task: str,
    run_timeout_seconds: int,
) -> ToolResult:
    """Handle send action."""
    if not task or not task.strip():
        return ToolResult(
            output="Error: task is required for send",
            is_error=True,
        )
    if not _ctrl_restart_callback:
        return ToolResult(
            output=("Error: send is unavailable because spawn callback is not configured"),
            is_error=True,
        )
    target_token = _ctrl_resolve_target_token(run_id, target)
    matched_runs, error = _ctrl_resolve_target_runs(target_token, include_terminal=True)
    if error:
        return ToolResult(output=error, is_error=True)
    if len(matched_runs) != 1:
        return ToolResult(
            output=(f"Error: send target '{target_token}' requires exactly one matched run"),
            is_error=True,
        )
    try:
        timeout = max(0, int(run_timeout_seconds or 0))
    except (TypeError, ValueError):
        timeout = 0
    return await _ctrl_send_dispatch(ctx, matched_runs[0], task, timeout)


# -- action: kill --


def _ctrl_collect_kill_candidates(
    matched_roots: list[SubAgentRun],
) -> dict[str, str]:
    """Collect candidate run_ids mapping to root_run_id."""
    assert _ctrl_run_registry is not None
    candidates: dict[str, str] = {}
    for root in matched_roots:
        if root.status in _CTRL_ACTIVE_STATUSES:
            candidates[root.run_id] = root.run_id
        descendants = _ctrl_run_registry.list_descendant_runs(
            _ctrl_conversation_id,
            root.run_id,
            include_terminal=False,
        )
        for desc in descendants:
            if desc.status in _CTRL_ACTIVE_STATUSES:
                candidates.setdefault(desc.run_id, root.run_id)
    return candidates


async def _ctrl_send_control_message(
    run_id: str,
    message_type: ControlMessageType,
    payload: str = "",
    cascade: bool = False,
) -> None:
    """Send a control message via the control channel (best-effort).

    Silently logs and ignores errors so that the existing cancel/steer
    flow is never disrupted by a channel failure.
    """
    if _ctrl_control_channel is None:
        return
    try:
        msg = ControlMessage(
            run_id=run_id,
            message_type=message_type,
            payload=payload,
            sender_id=_ctrl_conversation_id,
            cascade=cascade,
        )
        await _ctrl_control_channel.send_control(msg)
    except Exception:
        logger.warning(
            "Failed to send %s control message for run %s",
            message_type.value,
            run_id,
            exc_info=True,
        )


async def _ctrl_exec_cancellations(
    ctx: ToolContext,
    candidates: dict[str, str],
    target_token: str,
) -> int:
    """Execute cancellations. Returns cancelled count."""
    assert _ctrl_run_registry is not None
    assert _ctrl_cancel_callback is not None
    cancelled_count = 0
    for cand_id, root_id in candidates.items():
        cand = _ctrl_run_registry.get_run(_ctrl_conversation_id, cand_id)
        if not cand or cand.status not in _CTRL_ACTIVE_STATUSES:
            continue
        cancelled = await _ctrl_cancel_callback(cand.run_id)
        await _ctrl_send_control_message(
            cand.run_id,
            ControlMessageType.KILL,
            cascade=(root_id != cand_id),
        )
        updated = _ctrl_run_registry.mark_cancelled(
            conversation_id=_ctrl_conversation_id,
            run_id=cand.run_id,
            reason="Cancelled by subagents tool",
            metadata={
                "cancelled_by_tool": True,
                "cascade_root_run_id": root_id,
                "target_selector": target_token,
            },
            expected_statuses=list(_CTRL_ACTIVE_STATUSES),
        )
        if updated:
            await ctx.emit({"type": "subagent_killed", "data": updated.to_event_data()})
        if cancelled or updated:
            cancelled_count += 1
    return cancelled_count


def _ctrl_kill_result_msg(
    cancelled_count: int,
    target_token: str,
    run_id: str,
    is_direct: bool,
) -> str:
    """Build result message for kill operation."""
    if cancelled_count > 0:
        if is_direct:
            return f"Cancelled {cancelled_count} run(s) in lineage rooted at {run_id}"
        return f"Cancelled {cancelled_count} run(s) for target {target_token}"
    if is_direct:
        return f"Marked run lineage {run_id} as cancelled (tasks already finished or detached)"
    return f"No active runs matched target '{target_token}'"


async def _ctrl_handle_kill(ctx: ToolContext, run_id: str, target: str) -> ToolResult:
    """Handle kill action."""
    target_token = _ctrl_resolve_target_token(run_id, target)
    matched_roots, error = _ctrl_resolve_target_runs(target_token, include_terminal=True)
    if error:
        return ToolResult(output=error, is_error=True)
    if (
        len(matched_roots) == 1
        and matched_roots[0].run_id == target_token
        and matched_roots[0].status not in _CTRL_ACTIVE_STATUSES
    ):
        return ToolResult(
            output=(f"Run {target_token} is already terminal ({matched_roots[0].status.value})"),
        )
    candidates = _ctrl_collect_kill_candidates(matched_roots)
    is_direct = bool(target_token == run_id and run_id and not target)
    if not candidates:
        return ToolResult(
            output=_ctrl_kill_result_msg(0, target_token, run_id, is_direct),
        )
    cancelled = await _ctrl_exec_cancellations(ctx, candidates, target_token)
    return ToolResult(
        output=_ctrl_kill_result_msg(cancelled, target_token, run_id, is_direct),
        title=f"SubAgents: kill {target_token}",
    )


# -- action: steer --


def _ctrl_steer_resolve_active(
    target_token: str,
) -> tuple[SubAgentRun | None, str | None]:
    """Resolve target to exactly one active run for steering."""
    matched_runs, error = _ctrl_resolve_target_runs(target_token, include_terminal=True)
    if error:
        return None, error
    active = [r for r in matched_runs if r.status in _CTRL_ACTIVE_STATUSES]
    if len(active) != 1:
        if (
            len(matched_runs) == 1
            and matched_runs[0].run_id == target_token
            and matched_runs[0].status not in _CTRL_ACTIVE_STATUSES
        ):
            return (
                None,
                (f"Run {target_token} is already terminal ({matched_runs[0].status.value})"),
            )
        return (
            None,
            (f"Error: steer target '{target_token}' requires exactly one active run"),
        )
    return active[0], None


def _ctrl_steer_check_rate_limit(
    resolved_run_id: str,
) -> str | None:
    """Check steer rate limit, returning error if exceeded."""
    now = datetime.now(UTC)
    last_steer = _ctrl_last_steer_at.get(resolved_run_id)
    if last_steer:
        elapsed_ms = int((now - last_steer).total_seconds() * 1000)
        if elapsed_ms < _ctrl_steer_rate_limit_ms:
            return (
                "Error: steer rate limit exceeded. "
                f"Wait at least "
                f"{_ctrl_steer_rate_limit_ms - elapsed_ms}ms."
            )
    _ctrl_last_steer_at[resolved_run_id] = now
    return None


async def _ctrl_steer_metadata_only(
    ctx: ToolContext, resolved_run_id: str, instruction: str
) -> ToolResult:
    """Attach steer instruction as metadata without restart."""
    assert _ctrl_run_registry is not None
    now = datetime.now(UTC)
    updated = _ctrl_run_registry.attach_metadata(
        conversation_id=_ctrl_conversation_id,
        run_id=resolved_run_id,
        metadata={
            "steer_instruction": instruction,
            "steered_at": now.isoformat(),
        },
    )
    if not updated:
        return ToolResult(
            output=f"Error: run_id '{resolved_run_id}' not found",
            is_error=True,
        )
    await ctx.emit(
        {
            "type": "subagent_steered",
            "data": {**updated.to_event_data(), "instruction": instruction},
        }
    )
    await _ctrl_send_control_message(resolved_run_id, ControlMessageType.STEER, instruction)
    return ToolResult(
        output=(f"Steering instruction attached to run {resolved_run_id}"),
        title=f"SubAgents: steer {resolved_run_id}",
    )


async def _ctrl_steer_with_restart(
    ctx: ToolContext, run: SubAgentRun, instruction: str
) -> ToolResult:
    """Cancel run and restart with steering instruction."""
    assert _ctrl_run_registry is not None
    assert _ctrl_cancel_callback is not None
    assert _ctrl_restart_callback is not None
    resolved_run_id = run.run_id
    await _ctrl_send_control_message(resolved_run_id, ControlMessageType.KILL)
    cancelled = await _ctrl_cancel_callback(resolved_run_id)
    updated_old = _ctrl_run_registry.mark_cancelled(
        conversation_id=_ctrl_conversation_id,
        run_id=resolved_run_id,
        reason="Cancelled by steer restart",
        metadata={"steer_instruction": instruction},
        expected_statuses=list(_CTRL_ACTIVE_STATUSES),
    )
    if updated_old:
        await ctx.emit({"type": "subagent_killed", "data": updated_old.to_event_data()})
    restart_task = f"{run.task}\n\n[Steering Instruction]\n{instruction.strip()}"
    now = datetime.now(UTC)
    lineage_root = str(run.metadata.get("lineage_root_run_id") or resolved_run_id).strip()
    replacement = _ctrl_run_registry.create_run(
        conversation_id=_ctrl_conversation_id,
        subagent_name=run.subagent_name,
        task=restart_task,
        metadata={
            **dict(run.metadata),
            "session_mode": "steer_restart",
            "steered_from_run_id": resolved_run_id,
            "steer_instruction": instruction,
            "steered_at": now.isoformat(),
            "lineage_root_run_id": lineage_root,
        },
        requester_session_key=str(run.metadata.get("requester_session_key") or "").strip(),
        parent_run_id=str(run.metadata.get("parent_run_id") or "").strip() or None,
        lineage_root_run_id=lineage_root,
    )
    running = _ctrl_run_registry.mark_running(_ctrl_conversation_id, replacement.run_id)
    if running:
        await ctx.emit({"type": "subagent_started", "data": running.to_event_data()})
    try:
        await _ctrl_restart_callback(run.subagent_name, restart_task, replacement.run_id)
    except Exception as exc:
        failed = _ctrl_run_registry.mark_failed(
            conversation_id=_ctrl_conversation_id,
            run_id=replacement.run_id,
            error=str(exc),
            expected_statuses=[SubAgentRunStatus.RUNNING],
        )
        if failed:
            await ctx.emit({"type": "subagent_failed", "data": failed.to_event_data()})
        return ToolResult(
            output=(f"Error: failed to steer run {resolved_run_id}: {exc}"),
            is_error=True,
        )
    if updated_old:
        _ = _ctrl_run_registry.attach_metadata(
            conversation_id=_ctrl_conversation_id,
            run_id=resolved_run_id,
            metadata={"replaced_by_run_id": replacement.run_id},
        )
    await ctx.emit(
        {
            "type": "subagent_steered",
            "data": {
                **(running.to_event_data() if running else replacement.to_event_data()),
                "instruction": instruction,
                "previous_run_id": resolved_run_id,
                "new_run_id": replacement.run_id,
                "cancel_requested": cancelled,
            },
        }
    )
    return ToolResult(
        output=(f"Steered run {resolved_run_id}; restarted as {replacement.run_id}"),
        title=f"SubAgents: steer {resolved_run_id}",
    )


async def _ctrl_handle_steer(
    ctx: ToolContext, run_id: str, target: str, instruction: str
) -> ToolResult:
    """Handle steer action."""
    target_token = _ctrl_resolve_target_token(run_id, target)
    if not target_token:
        return ToolResult(
            output="Error: target (or run_id) is required for steer",
            is_error=True,
        )
    if not instruction or not instruction.strip():
        return ToolResult(
            output="Error: instruction is required for steer",
            is_error=True,
        )
    run, error = _ctrl_steer_resolve_active(target_token)
    if error:
        return ToolResult(output=error, is_error=True)
    assert run is not None
    rate_error = _ctrl_steer_check_rate_limit(run.run_id)
    if rate_error:
        return ToolResult(output=rate_error, is_error=True)
    if not _ctrl_restart_callback:
        return await _ctrl_steer_metadata_only(ctx, run.run_id, instruction)
    return await _ctrl_steer_with_restart(ctx, run, instruction)


# ---------------------------------------------------------------------------
# 6. subagents_control_tool
# ---------------------------------------------------------------------------


@tool_define(
    name="subagents_v2",
    description=(
        "SubAgent control plane. Actions: "
        "list (available agents + active counts), "
        "info (inspect run snapshots), "
        "log (replay run timeline), "
        "send (dispatch follow-up), "
        "kill (cancel active runs), "
        "steer (attach steering instruction)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "info",
                    "log",
                    "send",
                    "kill",
                    "steer",
                ],
                "description": "Control action.",
            },
            "run_id": {
                "type": "string",
                "description": ("Legacy target run id (use target for richer selectors)."),
            },
            "target": {
                "type": "string",
                "description": (
                    "Target selector: run_id | #<active-index> "
                    "| index:<active-index> | label:<tag> | all."
                ),
            },
            "instruction": {
                "type": "string",
                "description": ("Steering instruction (required for steer)."),
            },
            "task": {
                "type": "string",
                "description": ("Follow-up task content (required for send)."),
            },
            "run_timeout_seconds": {
                "type": "integer",
                "description": (
                    "Optional timeout for send action follow-up run (0 means no timeout)."
                ),
                "minimum": 0,
                "maximum": 3600,
            },
            "include_descendants": {
                "type": "boolean",
                "description": ("For info/log action, include descendants of matched runs."),
            },
            "include_announce": {
                "type": "boolean",
                "description": ("For log action, include announce/ack events."),
            },
        },
        "required": ["action"],
    },
    category="subagent",
    tags=frozenset({"subagent", "control"}),
)
async def subagents_control_tool(
    ctx: ToolContext,
    *,
    action: str = "list",
    run_id: str = "",
    target: str = "",
    instruction: str = "",
    task: str = "",
    run_timeout_seconds: int = 0,
    include_descendants: bool = True,
    include_announce: bool = True,
) -> ToolResult:
    """SubAgent control plane with 6 actions."""
    if _ctrl_run_registry is None:
        return ToolResult(
            output="Error: subagents_control not configured",
            is_error=True,
        )
    normalized = (action or "list").strip().lower()
    if normalized == "list":
        return _ctrl_handle_list()
    if normalized == "info":
        return _ctrl_handle_info(run_id, target, include_descendants)
    if normalized == "log":
        return await _ctrl_handle_log(run_id, target, include_descendants, include_announce)
    return await _ctrl_dispatch_mutation(
        ctx,
        normalized,
        run_id=run_id,
        target=target,
        instruction=instruction,
        task=task,
        run_timeout_seconds=run_timeout_seconds,
    )


async def _ctrl_dispatch_mutation(
    ctx: ToolContext,
    action: str,
    *,
    run_id: str,
    target: str,
    instruction: str,
    task: str,
    run_timeout_seconds: int,
) -> ToolResult:
    """Dispatch mutation actions with permission check."""
    blocked = _ctrl_ensure_mutation_allowed(action)
    if blocked:
        if "delegation depth" in blocked:
            await ctx.emit(
                dict(
                    SubAgentDepthLimitedEvent(
                        subagent_name="",
                        current_depth=_ctrl_delegation_depth,
                        max_depth=_ctrl_max_delegation_depth,
                    ).to_event_dict()
                )
            )
        return ToolResult(output=blocked, is_error=True)
    if action == "send":
        return await _ctrl_handle_send(ctx, run_id, target, task, run_timeout_seconds)
    if action == "kill":
        return await _ctrl_handle_kill(ctx, run_id, target)
    if action == "steer":
        return await _ctrl_handle_steer(ctx, run_id, target, instruction)
    return ToolResult(
        output=("Error: action must be one of list|info|log|send|kill|steer"),
        is_error=True,
    )


# ---------------------------------------------------------------------------
# Factory for nested session ToolDefinitions
# ---------------------------------------------------------------------------


def make_nested_session_tool_defs(  # noqa: C901, PLR0913, PLR0915
    *,
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    requester_session_key: str,
    visibility_default: str,
    observability_stats_provider: Callable[[], dict[str, Any]] | None,
    subagent_names: list[str],
    subagent_descriptions: dict[str, str],
    cancel_callback: Callable[[str], Awaitable[bool]],
    restart_callback: Callable[[str, str, str], Awaitable[str]] | None,
    max_active_runs: int,
    max_active_runs_per_lineage: int,
    max_children_per_requester: int,
    delegation_depth: int,
    max_delegation_depth: int,
) -> list[Any]:
    """Build nested session ToolDefinitions for use inside SubAgent scopes.

    Returns a list of ``ToolDefinition`` objects for the 6 nested session tools
    (list, history, timeline, overview, wait, control).

    Because the ``@tool_define`` functions read from module-level globals, each
    closure produced here snapshots the current globals, re-configures them for
    the nested scope, delegates to the ``@tool_define`` execute, and restores
    the originals in a ``finally`` block.
    """
    from src.infrastructure.agent.processor.processor import ToolDefinition

    # References to the @tool_define ToolInfo objects (module-level singletons)
    list_info = sessions_list_tool
    history_info = sessions_history_tool
    timeline_info = sessions_timeline_tool
    overview_info = sessions_overview_tool
    wait_info = sessions_wait_tool
    control_info = subagents_control_tool

    # -- helpers to snapshot / restore module globals -----------------------

    _sess_global_names = [
        "_sess_run_registry",
        "_sess_spawn_callback",
        "_sess_max_active_runs",
        "_sess_max_spawn_retries",
        "_sess_retry_delay_ms",
        "_sess_subagent_names",
        "_sess_subagent_descriptions",
        "_sess_conversation_id",
        "_sess_requester_session_key",
        "_sess_delegation_depth",
        "_sess_max_delegation_depth",
        "_sess_max_active_runs_per_lineage",
        "_sess_max_children_per_requester",
        "_sess_visibility_default",
    ]
    _overview_global_names = [
        "_sess_overview_run_registry",
        "_sess_overview_conversation_id",
        "_sess_overview_requester_session_key",
        "_sess_overview_visibility_default",
        "_sess_overview_observability_provider",
    ]
    _wait_global_names = [
        "_sess_wait_run_registry",
        "_sess_wait_conversation_id",
    ]
    _ctrl_global_names = [
        "_ctrl_run_registry",
        "_ctrl_conversation_id",
        "_ctrl_subagent_names",
        "_ctrl_subagent_descriptions",
        "_ctrl_cancel_callback",
        "_ctrl_restart_callback",
        "_ctrl_steer_rate_limit_ms",
        "_ctrl_max_active_runs",
        "_ctrl_max_active_runs_per_lineage",
        "_ctrl_max_children_per_requester",
        "_ctrl_requester_session_key",
        "_ctrl_delegation_depth",
        "_ctrl_max_delegation_depth",
        "_ctrl_last_steer_at",
        "_ctrl_spawn_callback_params",
        "_ctrl_spawn_callback_accepts_kwargs",
    ]

    _mod = __import__(__name__)
    # Resolve to actual submodule via dotted path
    for part in __name__.split(".")[1:]:
        _mod = getattr(_mod, part)

    def _snapshot(names: list[str]) -> dict[str, Any]:
        return {n: getattr(_mod, n) for n in names}

    def _restore(snap: dict[str, Any]) -> None:
        for n, v in snap.items():
            setattr(_mod, n, v)

    # -- closures that configure + execute + restore -----------------------

    def _make_sess_tool(
        tool_info: Any,
    ) -> Callable[..., Awaitable[Any]]:
        """Wrap a session @tool_define for nested scope (list/history/timeline)."""

        async def _execute(ctx: ToolContext, **kwargs: Any) -> Any:
            snap = _snapshot(_sess_global_names)
            try:
                configure_session_tools(
                    run_registry=run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=requester_session_key,
                    visibility_default=visibility_default,
                    subagent_names=subagent_names,
                    subagent_descriptions=subagent_descriptions,
                    delegation_depth=delegation_depth,
                    max_delegation_depth=max_delegation_depth,
                    max_active_runs_per_lineage=max_active_runs_per_lineage,
                    max_children_per_requester=max_children_per_requester,
                )
                return await tool_info.execute(ctx, **kwargs)
            finally:
                _restore(snap)

        return _execute

    def _make_overview_tool() -> Callable[..., Awaitable[Any]]:
        async def _execute(ctx: ToolContext, **kwargs: Any) -> Any:
            snap = _snapshot(_overview_global_names)
            try:
                configure_sessions_overview(
                    run_registry=run_registry,
                    conversation_id=conversation_id,
                    requester_session_key=requester_session_key,
                    visibility_default=visibility_default,
                    observability_provider=observability_stats_provider,
                )
                return await overview_info.execute(ctx, **kwargs)
            finally:
                _restore(snap)

        return _execute

    def _make_wait_tool() -> Callable[..., Awaitable[Any]]:
        async def _execute(ctx: ToolContext, **kwargs: Any) -> Any:
            snap = _snapshot(_wait_global_names)
            try:
                configure_sessions_wait(
                    run_registry=run_registry,
                    conversation_id=conversation_id,
                )
                return await wait_info.execute(ctx, **kwargs)
            finally:
                _restore(snap)

        return _execute

    def _make_ctrl_tool() -> Callable[..., Awaitable[Any]]:
        async def _execute(ctx: ToolContext, **kwargs: Any) -> Any:
            snap = _snapshot(_ctrl_global_names)
            try:
                configure_subagents_control(
                    run_registry=run_registry,
                    conversation_id=conversation_id,
                    subagent_names=subagent_names,
                    subagent_descriptions=subagent_descriptions,
                    cancel_callback=cancel_callback,
                    restart_callback=restart_callback,
                    max_active_runs=max_active_runs,
                    max_active_runs_per_lineage=max_active_runs_per_lineage,
                    max_children_per_requester=max_children_per_requester,
                    requester_session_key=requester_session_key,
                    delegation_depth=delegation_depth,
                    max_delegation_depth=max_delegation_depth,
                )
                return await control_info.execute(ctx, **kwargs)
            finally:
                _restore(snap)

        return _execute

    # -- assemble ToolDefinition list --------------------------------------

    result: list[ToolDefinition] = []
    for info, factory in [
        (list_info, _make_sess_tool(list_info)),
        (history_info, _make_sess_tool(history_info)),
        (timeline_info, _make_sess_tool(timeline_info)),
    ]:
        result.append(
            ToolDefinition(
                name=info.name,
                description=info.description,
                parameters=info.parameters,
                execute=factory,
            )
        )

    result.append(
        ToolDefinition(
            name=overview_info.name,
            description=overview_info.description,
            parameters=overview_info.parameters,
            execute=_make_overview_tool(),
        )
    )
    result.append(
        ToolDefinition(
            name=wait_info.name,
            description=wait_info.description,
            parameters=wait_info.parameters,
            execute=_make_wait_tool(),
        )
    )
    result.append(
        ToolDefinition(
            name=control_info.name,
            description=control_info.description,
            parameters=control_info.parameters,
            execute=_make_ctrl_tool(),
        )
    )

    return result
