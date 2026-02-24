"""Session-oriented SubAgent collaboration tools."""

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.base import AgentTool

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
        "requester_session_key": requester_session_key,
        "control_plane_version": "v2",
    }
    if lineage_root_run_id:
        metadata["lineage_root_run_id"] = lineage_root_run_id
    if parent_run_id:
        metadata["parent_run_id"] = parent_run_id
    if delegation_depth is not None:
        metadata["delegation_depth"] = delegation_depth
    if extra:
        metadata.update(extra)
    return metadata


class SessionsSpawnTool(AgentTool):
    """Spawn a SubAgent run as a non-blocking session."""

    def __init__(
        self,
        subagent_names: list[str],
        subagent_descriptions: dict[str, str],
        spawn_callback: Callable[..., Awaitable[str]],
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        max_active_runs: int = 16,
        max_active_runs_per_lineage: int | None = None,
        max_children_per_requester: int | None = None,
        requester_session_key: str | None = None,
        delegation_depth: int = 0,
        max_delegation_depth: int = 1,
        max_spawn_retries: int = 2,
        retry_delay_ms: int = 200,
    ) -> None:
        desc = "; ".join(f"{name}: {text}" for name, text in subagent_descriptions.items())
        super().__init__(
            name="sessions_spawn",
            description=(
                "Spawn a detached SubAgent session for long-running work. "
                f"Available SubAgents: {desc or 'none'}"
            ),
        )
        self._subagent_names = subagent_names
        self._spawn_callback = spawn_callback
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._max_active_runs = max(1, max_active_runs)
        self._max_active_runs_per_lineage = max(1, max_active_runs_per_lineage or max_active_runs)
        self._max_children_per_requester = max(1, max_children_per_requester or max_active_runs)
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._delegation_depth = delegation_depth
        self._max_delegation_depth = max(1, max_delegation_depth)
        self._max_spawn_retries = max(0, max_spawn_retries)
        self._retry_delay_ms = max(1, retry_delay_ms)
        self._spawn_callback_params, self._spawn_callback_accepts_kwargs = (
            _resolve_spawn_callback_signature(spawn_callback)
        )
        self._pending_events: list[dict[str, Any]] = []

    def consume_pending_events(self) -> list[dict[str, Any]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subagent_name": {
                    "type": "string",
                    "description": "Target SubAgent name.",
                    "enum": self._subagent_names,
                },
                "task": {
                    "type": "string",
                    "description": "Task to execute asynchronously.",
                },
                "run_timeout_seconds": {
                    "type": "integer",
                    "description": "Optional timeout for the detached run (0 means no timeout).",
                    "minimum": 0,
                    "maximum": 3600,
                },
                "mode": {
                    "type": "string",
                    "description": "Spawn mode: run (one-shot) or session (persistent follow-up).",
                    "enum": ["run", "session"],
                },
                "thread": {
                    "type": "boolean",
                    "description": "Whether thread binding is requested for this spawn.",
                },
                "cleanup": {
                    "type": "string",
                    "description": "Post-run cleanup preference.",
                    "enum": ["keep", "delete"],
                },
                "agent_id": {
                    "type": "string",
                    "description": "Optional SubAgent override; must match an available subagent.",
                },
                "model": {
                    "type": "string",
                    "description": "Optional model override for this spawned session.",
                },
                "thinking": {
                    "type": "string",
                    "description": "Optional thinking/reasoning level hint for this spawned session.",
                },
            },
            "required": ["subagent_name", "task"],
        }

    async def execute(
        self,
        subagent_name: str = "",
        task: str = "",
        run_timeout_seconds: int = 0,
        mode: str = "run",
        thread: bool = False,
        cleanup: str = "keep",
        agent_id: str = "",
        model: str = "",
        thinking: str = "",
        **kwargs: Any,
    ) -> str:
        self._pending_events.clear()
        if not subagent_name or subagent_name not in self._subagent_names:
            return f"Error: invalid subagent_name. Available: {', '.join(self._subagent_names)}"
        if not task or not task.strip():
            return "Error: task is required"
        if self._delegation_depth >= self._max_delegation_depth:
            return (
                "Error: sessions_spawn is disabled at current delegation depth "
                f"({self._delegation_depth}/{self._max_delegation_depth})"
            )
        try:
            timeout_seconds = max(0, int(run_timeout_seconds or 0))
        except (TypeError, ValueError):
            timeout_seconds = 0
        spawn_mode = (mode or "run").strip().lower()
        if spawn_mode not in {"run", "session"}:
            return "Error: mode must be one of run|session"

        thread_requested = bool(thread)
        if spawn_mode == "session" and not thread_requested:
            return "Error: mode='session' requires thread=true"

        cleanup_policy = (cleanup or "keep").strip().lower()
        if cleanup_policy not in {"keep", "delete"}:
            return "Error: cleanup must be one of keep|delete"
        if spawn_mode == "session" and cleanup_policy == "delete":
            return "Error: mode='session' requires cleanup='keep'"
        if spawn_mode == "session":
            cleanup_policy = "keep"

        requested_agent_id = (agent_id or "").strip()
        target_subagent_name = subagent_name
        if requested_agent_id:
            if requested_agent_id not in self._subagent_names:
                return f"Error: invalid agent_id. Available: {', '.join(self._subagent_names)}"
            target_subagent_name = requested_agent_id

        model_override = (model or "").strip() or None
        thinking_override = (thinking or "").strip() or None
        spawn_options: dict[str, Any] = {
            "spawn_mode": spawn_mode,
            "thread_requested": thread_requested,
            "cleanup": cleanup_policy,
            "agent_id": requested_agent_id or target_subagent_name,
            "model": model_override,
            "thinking": thinking_override,
            "requester_session_key": self._requester_session_key,
            "run_timeout_seconds": timeout_seconds,
        }

        active_runs = self._run_registry.count_active_runs(self._conversation_id)
        if active_runs >= self._max_active_runs:
            return (
                f"Error: active SubAgent sessions limit reached "
                f"({active_runs}/{self._max_active_runs})"
            )
        requester_runs = self._run_registry.count_active_runs_for_requester(
            self._conversation_id, self._requester_session_key
        )
        if requester_runs >= self._max_children_per_requester:
            return (
                "Error: requester SubAgent sessions limit reached "
                f"({requester_runs}/{self._max_children_per_requester})"
            )

        run = self._run_registry.create_run(
            conversation_id=self._conversation_id,
            subagent_name=target_subagent_name,
            task=task,
            metadata=_build_lifecycle_metadata(
                session_mode="spawn",
                requester_session_key=self._requester_session_key,
                lineage_root_run_id=None,
                delegation_depth=self._delegation_depth,
                extra={
                    **spawn_options,
                    "requested_subagent_name": subagent_name,
                    "max_active_runs_per_lineage": self._max_active_runs_per_lineage,
                },
            ),
            requester_session_key=self._requester_session_key,
        )
        running = self._run_registry.mark_running(self._conversation_id, run.run_id)
        if running:
            self._pending_events.append(
                {"type": "subagent_run_started", "data": running.to_event_data()}
            )

        try:
            retry_count = await self._spawn_with_retry(
                run_id=run.run_id,
                subagent_name=target_subagent_name,
                task=task,
                spawn_options=spawn_options,
            )
            if retry_count > 0:
                self._run_registry.attach_metadata(
                    self._conversation_id,
                    run.run_id,
                    {"announce_retry_count": retry_count},
                )
            self._pending_events.append(
                {
                    "type": "subagent_session_spawned",
                    "data": {
                        "conversation_id": self._conversation_id,
                        "run_id": run.run_id,
                        "subagent_name": target_subagent_name,
                        "spawn_mode": spawn_mode,
                        "thread_requested": thread_requested,
                        "cleanup": cleanup_policy,
                    },
                }
            )
            if spawn_mode == "session":
                return (
                    f"Spawned persistent SubAgent session {run.run_id} for "
                    f"'{target_subagent_name}'. Use sessions_send to continue the lineage."
                )
            return (
                f"Spawned SubAgent session {run.run_id} for '{target_subagent_name}'. "
                "Use sessions_list or sessions_history to inspect progress."
            )
        except Exception as exc:
            failed = self._run_registry.mark_failed(
                conversation_id=self._conversation_id,
                run_id=run.run_id,
                error=str(exc),
            )
            if failed:
                self._pending_events.append(
                    {"type": "subagent_run_failed", "data": failed.to_event_data()}
                )
            return f"Error: failed to spawn session: {exc}"

    async def _invoke_spawn_callback(
        self,
        subagent_name: str,
        task: str,
        run_id: str,
        spawn_options: dict[str, Any],
    ) -> str:
        filtered_options = _filter_spawn_options(
            spawn_options,
            self._spawn_callback_params,
            self._spawn_callback_accepts_kwargs,
        )
        return await self._spawn_callback(subagent_name, task, run_id, **filtered_options)

    async def _spawn_with_retry(
        self,
        run_id: str,
        subagent_name: str,
        task: str,
        spawn_options: dict[str, Any],
    ) -> int:
        last_error: Exception | None = None
        for attempt in range(self._max_spawn_retries + 1):
            try:
                await self._invoke_spawn_callback(
                    subagent_name=subagent_name,
                    task=task,
                    run_id=run_id,
                    spawn_options=spawn_options,
                )
                return attempt
            except Exception as exc:
                last_error = exc
                if attempt >= self._max_spawn_retries:
                    break
                self._pending_events.append(
                    {
                        "type": "subagent_announce_retry",
                        "data": {
                            "conversation_id": self._conversation_id,
                            "run_id": run_id,
                            "subagent_name": subagent_name,
                            "attempt": attempt + 1,
                            "error": str(exc),
                            "next_delay_ms": self._retry_delay_ms,
                        },
                    }
                )
                _record_announce_event(
                    run_registry=self._run_registry,
                    conversation_id=self._conversation_id,
                    run_id=run_id,
                    event_type="retry",
                    payload={
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "next_delay_ms": self._retry_delay_ms,
                    },
                )
                await asyncio.sleep(self._retry_delay_ms / 1000)

        self._pending_events.append(
            {
                "type": "subagent_announce_giveup",
                "data": {
                    "conversation_id": self._conversation_id,
                    "run_id": run_id,
                    "subagent_name": subagent_name,
                    "attempts": self._max_spawn_retries + 1,
                    "error": str(last_error) if last_error else "unknown error",
                },
            }
        )
        _record_announce_event(
            run_registry=self._run_registry,
            conversation_id=self._conversation_id,
            run_id=run_id,
            event_type="giveup",
            payload={
                "attempts": self._max_spawn_retries + 1,
                "error": str(last_error) if last_error else "unknown error",
            },
        )
        if last_error:
            raise last_error
        raise RuntimeError("failed to spawn session")


class SessionsListTool(AgentTool):
    """List active SubAgent sessions."""

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        requester_session_key: str | None = None,
        visibility_default: str = "tree",
    ) -> None:
        super().__init__(
            name="sessions_list",
            description=(
                "List active SubAgent sessions for this conversation. "
                "Use status='active' for pending/running runs."
            ),
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._visibility_default = (
            visibility_default
            if visibility_default
            in {
                "self",
                "tree",
                "all",
            }
            else "tree"
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
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
        }

    async def execute(
        self,
        status: str = "active",
        visibility: str = "",
        limit: int = 20,
        **kwargs: Any,
    ) -> str:
        statuses: list[SubAgentRunStatus] | None
        if status == "active":
            statuses = [SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING]
        elif status:
            try:
                statuses = [SubAgentRunStatus(status)]
            except ValueError:
                return f"Error: invalid status '{status}'"
        else:
            statuses = None

        effective_visibility = (visibility or self._visibility_default).strip().lower()
        if effective_visibility not in {"self", "tree", "all"}:
            return f"Error: invalid visibility '{effective_visibility}'"

        runs = self._run_registry.list_runs_for_requester(
            self._conversation_id,
            self._requester_session_key,
            visibility=effective_visibility,
            statuses=statuses,
        )[: max(1, limit)]
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "visibility": effective_visibility,
                "count": len(runs),
                "runs": [run.to_event_data() for run in runs],
            },
            ensure_ascii=False,
            indent=2,
        )


class SessionsHistoryTool(AgentTool):
    """List SubAgent session history."""

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        requester_session_key: str | None = None,
        visibility_default: str = "tree",
    ) -> None:
        super().__init__(
            name="sessions_history",
            description="List historical SubAgent sessions (including terminal runs).",
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._visibility_default = (
            visibility_default
            if visibility_default
            in {
                "self",
                "tree",
                "all",
            }
            else "tree"
        )

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
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
        }

    async def execute(self, visibility: str = "", limit: int = 50, **kwargs: Any) -> str:
        effective_visibility = (visibility or self._visibility_default).strip().lower()
        if effective_visibility not in {"self", "tree", "all"}:
            return f"Error: invalid visibility '{effective_visibility}'"

        runs = self._run_registry.list_runs_for_requester(
            self._conversation_id,
            self._requester_session_key,
            visibility=effective_visibility,
        )[: max(1, limit)]
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "visibility": effective_visibility,
                "count": len(runs),
                "runs": [run.to_event_data() for run in runs],
            },
            ensure_ascii=False,
            indent=2,
        )


class SessionsTimelineTool(AgentTool):
    """Replay lifecycle timeline for a run (optionally including descendants)."""

    def __init__(self, run_registry: SubAgentRunRegistry, conversation_id: str) -> None:
        super().__init__(
            name="sessions_timeline",
            description="Replay run lifecycle timeline and announce history by run_id.",
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Root run id to replay."},
                "include_descendants": {
                    "type": "boolean",
                    "description": "Include descendant runs in timeline replay.",
                    "default": False,
                },
                "include_announce": {
                    "type": "boolean",
                    "description": "Include announce retry/giveup events from metadata.",
                    "default": True,
                },
            },
            "required": ["run_id"],
        }

    async def execute(
        self,
        run_id: str = "",
        include_descendants: bool = False,
        include_announce: bool = True,
        **kwargs: Any,
    ) -> str:
        if not run_id:
            return "Error: run_id is required"
        root_run = self._run_registry.get_run(self._conversation_id, run_id)
        if not root_run:
            return f"Error: run_id '{run_id}' not found"

        runs: dict[str, SubAgentRun] = {root_run.run_id: root_run}
        if include_descendants:
            descendants = self._run_registry.list_descendant_runs(
                self._conversation_id,
                run_id,
                include_terminal=True,
            )
            for run in descendants:
                runs[run.run_id] = run

        events: list[dict[str, Any]] = []
        for run in runs.values():
            events.extend(self._build_timeline_for_run(run, include_announce=include_announce))

        events.sort(key=lambda item: item.get("timestamp") or "")
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "root_run_id": run_id,
                "run_count": len(runs),
                "event_count": len(events),
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _build_timeline_for_run(
        self,
        run: SubAgentRun,
        *,
        include_announce: bool,
    ) -> list[dict[str, Any]]:
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

        announce_events = run.metadata.get("announce_events")
        if not isinstance(announce_events, list):
            announce_events = []
        fallback_ts = run.started_at or run.created_at
        for item in announce_events:
            if not isinstance(item, dict):
                continue
            announce_type = str(item.get("type") or "unknown").strip() or "unknown"
            timestamp = str(item.get("timestamp") or fallback_ts.isoformat())
            payload = {
                key: value for key, value in item.items() if key not in {"type", "timestamp"}
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

        ack_events = run.metadata.get("ack_events")
        if isinstance(ack_events, list):
            for item in ack_events:
                if not isinstance(item, dict):
                    continue
                timestamp = str(item.get("timestamp") or fallback_ts.isoformat())
                payload = {
                    key: value for key, value in item.items() if key not in {"type", "timestamp"}
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
        return events


class SessionsOverviewTool(AgentTool):
    """Provide collaboration runtime observability summary for SubAgent runs."""

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        requester_session_key: str | None = None,
        visibility_default: str = "tree",
        observability_stats_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            name="sessions_overview",
            description="Show run observability summary (status/error/retry/lane wait hotspots).",
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._visibility_default = (
            visibility_default
            if visibility_default
            in {
                "self",
                "tree",
                "all",
            }
            else "tree"
        )
        self._observability_stats_provider = observability_stats_provider

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "visibility": {
                    "type": "string",
                    "description": "Run visibility boundary.",
                    "enum": ["self", "tree", "all"],
                }
            },
            "required": [],
        }

    async def execute(self, visibility: str = "", **kwargs: Any) -> str:
        effective_visibility = (visibility or self._visibility_default).strip().lower()
        if effective_visibility not in {"self", "tree", "all"}:
            return f"Error: invalid visibility '{effective_visibility}'"

        runs = self._run_registry.list_runs_for_requester(
            self._conversation_id,
            self._requester_session_key,
            visibility=effective_visibility,
        )
        status_counts: dict[str, int] = {status.value: 0 for status in SubAgentRunStatus}
        subagent_counts: dict[str, int] = {}
        error_counts: dict[str, int] = {}
        announce_retry_count = 0
        announce_giveup_count = 0
        announce_delivered_count = 0
        announce_dropped_count = 0
        announce_backlog_count = 0
        lane_wait_values: list[int] = []
        archive_lag_values: list[int] = []
        retention_seconds = max(int(self._run_registry.terminal_retention_seconds), 0)
        now = datetime.now(UTC)
        terminal_statuses = {
            SubAgentRunStatus.COMPLETED,
            SubAgentRunStatus.FAILED,
            SubAgentRunStatus.CANCELLED,
            SubAgentRunStatus.TIMED_OUT,
        }

        for run in runs:
            status_counts[run.status.value] = status_counts.get(run.status.value, 0) + 1
            subagent_counts[run.subagent_name] = subagent_counts.get(run.subagent_name, 0) + 1

            if (
                run.status
                in {
                    SubAgentRunStatus.FAILED,
                    SubAgentRunStatus.TIMED_OUT,
                    SubAgentRunStatus.CANCELLED,
                }
                and run.error
            ):
                error_counts[run.error] = error_counts.get(run.error, 0) + 1

            announce_dropped_count += int(run.metadata.get("announce_events_dropped") or 0)
            announce_events = run.metadata.get("announce_events")
            if isinstance(announce_events, list):
                for event in announce_events:
                    if not isinstance(event, dict):
                        continue
                    event_type = str(event.get("type") or "").strip().lower()
                    if event_type in {"retry", "completion_retry"}:
                        announce_retry_count += 1
                    elif event_type in {"giveup", "completion_giveup"}:
                        announce_giveup_count += 1
                    elif event_type == "completion_delivered":
                        announce_delivered_count += 1

            if run.status in terminal_statuses:
                announce_status = str(run.metadata.get("announce_status") or "").strip().lower()
                if announce_status not in {"delivered", "giveup"}:
                    announce_backlog_count += 1
                if retention_seconds > 0:
                    terminal_at = run.ended_at or run.created_at
                    lag_ms = int((now - terminal_at).total_seconds() * 1000) - (
                        retention_seconds * 1000
                    )
                    if lag_ms > 0:
                        archive_lag_values.append(lag_ms)

            lane_wait_ms = run.metadata.get("lane_wait_ms")
            if isinstance(lane_wait_ms, (int, float)):
                lane_wait_values.append(int(lane_wait_ms))

        active_runs = (
            status_counts[SubAgentRunStatus.PENDING.value]
            + status_counts[SubAgentRunStatus.RUNNING.value]
        )
        by_subagent = [
            {"subagent_name": name, "count": count}
            for name, count in sorted(
                subagent_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        error_hotspots = [
            {"error": error, "count": count}
            for error, count in sorted(
                error_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        ]
        lane_wait_summary = {
            "sample_count": len(lane_wait_values),
            "avg": int(sum(lane_wait_values) / len(lane_wait_values)) if lane_wait_values else 0,
            "max": max(lane_wait_values) if lane_wait_values else 0,
        }
        archive_lag_summary = {
            "retention_seconds": retention_seconds,
            "stale_count": len(archive_lag_values),
            "avg": int(sum(archive_lag_values) / len(archive_lag_values))
            if archive_lag_values
            else 0,
            "max": max(archive_lag_values) if archive_lag_values else 0,
        }
        hook_failures = 0
        if self._observability_stats_provider:
            try:
                stats = self._observability_stats_provider()
                if isinstance(stats, dict):
                    hook_failures = int(stats.get("hook_failures") or 0)
            except Exception:
                hook_failures = 0

        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "visibility": effective_visibility,
                "total_runs": len(runs),
                "active_runs": active_runs,
                "status_counts": status_counts,
                "by_subagent": by_subagent,
                "announce_summary": {
                    "retry_count": announce_retry_count,
                    "giveup_count": announce_giveup_count,
                    "delivered_count": announce_delivered_count,
                    "dropped_count": announce_dropped_count,
                    "backlog_count": announce_backlog_count,
                },
                "archive_lag_ms": archive_lag_summary,
                "hook_failures": hook_failures,
                "lane_wait_ms": lane_wait_summary,
                "error_hotspots": error_hotspots,
            },
            ensure_ascii=False,
            indent=2,
        )


class SessionsWaitTool(AgentTool):
    """Wait until a run reaches terminal state or timeout."""

    _TERMINAL_STATUSES: ClassVar[set] = {
        SubAgentRunStatus.COMPLETED,
        SubAgentRunStatus.FAILED,
        SubAgentRunStatus.CANCELLED,
        SubAgentRunStatus.TIMED_OUT,
    }

    def __init__(self, run_registry: SubAgentRunRegistry, conversation_id: str) -> None:
        super().__init__(
            name="sessions_wait",
            description="Wait for a SubAgent run to reach terminal status and return latest state.",
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run id to wait for."},
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
        }

    async def execute(
        self,
        run_id: str = "",
        timeout_seconds: float = 30,
        poll_interval_ms: int = 200,
        **kwargs: Any,
    ) -> str:
        if not run_id:
            return "Error: run_id is required"
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
            run = self._run_registry.get_run(self._conversation_id, run_id)
            if not run:
                return f"Error: run_id '{run_id}' not found"
            elapsed = (datetime.now(UTC) - started_at).total_seconds()
            is_terminal = run.status in self._TERMINAL_STATUSES
            if is_terminal or elapsed >= timeout:
                announce_payload = run.metadata.get("announce_payload")
                if not isinstance(announce_payload, dict):
                    announce_payload = None
                return json.dumps(
                    {
                        "conversation_id": self._conversation_id,
                        "run": run.to_event_data(),
                        "is_terminal": is_terminal,
                        "timed_out": not is_terminal and elapsed >= timeout,
                        "waited_ms": int(elapsed * 1000),
                        "announce": {
                            "status": str(run.metadata.get("announce_status") or "").strip()
                            or None,
                            "attempt_count": int(run.metadata.get("announce_attempt_count") or 0),
                            "last_error": str(run.metadata.get("announce_last_error") or "").strip()
                            or None,
                            "payload": announce_payload,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            await asyncio.sleep(poll_interval)


class SessionsAckTool(AgentTool):
    """Acknowledge a terminal run for wait/ack workflow."""

    _TERMINAL_STATUSES: ClassVar[set] = {
        SubAgentRunStatus.COMPLETED,
        SubAgentRunStatus.FAILED,
        SubAgentRunStatus.CANCELLED,
        SubAgentRunStatus.TIMED_OUT,
    }

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        requester_session_key: str | None = None,
    ) -> None:
        super().__init__(
            name="sessions_ack",
            description="Acknowledge a terminal SubAgent run and record ack metadata.",
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._requester_session_key = (requester_session_key or conversation_id).strip()

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run id to acknowledge."},
                "note": {
                    "type": "string",
                    "description": "Optional acknowledgement note.",
                    "maxLength": 500,
                },
            },
            "required": ["run_id"],
        }

    async def execute(self, run_id: str = "", note: str = "", **kwargs: Any) -> str:
        if not run_id:
            return "Error: run_id is required"
        run = self._run_registry.get_run(self._conversation_id, run_id)
        if not run:
            return f"Error: run_id '{run_id}' not found"
        if run.status not in self._TERMINAL_STATUSES:
            return (
                f"Error: run_id '{run_id}' status '{run.status.value}' is not terminal. "
                "Use sessions_wait first."
            )

        ack_events = run.metadata.get("ack_events")
        if not isinstance(ack_events, list):
            ack_events = []
        if len(ack_events) >= 20:
            ack_events = ack_events[-19:]
        ack_event = {
            "type": "ack",
            "timestamp": datetime.now(UTC).isoformat(),
            "requester_session_key": self._requester_session_key,
        }
        if note and note.strip():
            ack_event["note"] = note.strip()[:500]
        ack_events.append(ack_event)

        updated = self._run_registry.attach_metadata(
            self._conversation_id,
            run_id,
            {
                "ack_events": ack_events,
                "last_ack_by": self._requester_session_key,
                "last_ack_at": ack_event["timestamp"],
            },
            expected_statuses=list(self._TERMINAL_STATUSES),
        )
        if not updated:
            return f"Error: run_id '{run_id}' changed while acknowledging, please retry."

        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "run_id": run_id,
                "acknowledged": True,
                "status": updated.status.value,
                "ack_count": len(ack_events),
            },
            ensure_ascii=False,
            indent=2,
        )


class SessionsSendTool(AgentTool):
    """Send follow-up work to the same SubAgent lineage as an existing run."""

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        spawn_callback: Callable[..., Awaitable[str]],
        max_active_runs: int = 16,
        max_active_runs_per_lineage: int | None = None,
        max_children_per_requester: int | None = None,
        requester_session_key: str | None = None,
        delegation_depth: int = 0,
        max_delegation_depth: int = 1,
        max_spawn_retries: int = 2,
        retry_delay_ms: int = 200,
    ) -> None:
        super().__init__(
            name="sessions_send",
            description=(
                "Send a follow-up task to an existing SubAgent session lineage "
                "by run_id. Creates a new child run with parent_run_id metadata."
            ),
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._spawn_callback = spawn_callback
        self._max_active_runs = max(1, max_active_runs)
        self._max_active_runs_per_lineage = max(1, max_active_runs_per_lineage or max_active_runs)
        self._max_children_per_requester = max(1, max_children_per_requester or max_active_runs)
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._delegation_depth = delegation_depth
        self._max_delegation_depth = max(1, max_delegation_depth)
        self._max_spawn_retries = max(0, max_spawn_retries)
        self._retry_delay_ms = max(1, retry_delay_ms)
        self._spawn_callback_params, self._spawn_callback_accepts_kwargs = (
            _resolve_spawn_callback_signature(spawn_callback)
        )
        self._pending_events: list[dict[str, Any]] = []

    def consume_pending_events(self) -> list[dict[str, Any]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Existing run id to follow up."},
                "task": {"type": "string", "description": "Follow-up task content."},
                "run_timeout_seconds": {
                    "type": "integer",
                    "description": "Optional timeout for follow-up run (0 means no timeout).",
                    "minimum": 0,
                    "maximum": 3600,
                },
            },
            "required": ["run_id", "task"],
        }

    async def execute(
        self,
        run_id: str = "",
        task: str = "",
        run_timeout_seconds: int = 0,
        **kwargs: Any,
    ) -> str:
        self._pending_events.clear()
        if not run_id:
            return "Error: run_id is required"
        if not task or not task.strip():
            return "Error: task is required"
        if self._delegation_depth >= self._max_delegation_depth:
            return (
                "Error: sessions_send is disabled at current delegation depth "
                f"({self._delegation_depth}/{self._max_delegation_depth})"
            )
        try:
            timeout_seconds = max(0, int(run_timeout_seconds or 0))
        except (TypeError, ValueError):
            timeout_seconds = 0

        parent_run = self._run_registry.get_run(self._conversation_id, run_id)
        if not parent_run:
            return f"Error: run_id '{run_id}' not found"

        active_runs = self._run_registry.count_active_runs(self._conversation_id)
        if active_runs >= self._max_active_runs:
            return (
                f"Error: active SubAgent sessions limit reached "
                f"({active_runs}/{self._max_active_runs})"
            )
        requester_runs = self._run_registry.count_active_runs_for_requester(
            self._conversation_id, self._requester_session_key
        )
        if requester_runs >= self._max_children_per_requester:
            return (
                "Error: requester SubAgent sessions limit reached "
                f"({requester_runs}/{self._max_children_per_requester})"
            )

        lineage_root_run_id = str(parent_run.metadata.get("lineage_root_run_id") or run_id).strip()
        lineage_active_runs = self._run_registry.count_active_runs_for_lineage(
            self._conversation_id,
            lineage_root_run_id,
        )
        if lineage_active_runs >= self._max_active_runs_per_lineage:
            return (
                "Error: lineage SubAgent sessions limit reached "
                f"({lineage_active_runs}/{self._max_active_runs_per_lineage})"
            )
        try:
            parent_timeout = int(parent_run.metadata.get("run_timeout_seconds") or 0)
        except (TypeError, ValueError):
            parent_timeout = 0
        follow_up_options: dict[str, Any] = {
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
            "requester_session_key": self._requester_session_key,
            "run_timeout_seconds": timeout_seconds or parent_timeout,
        }

        child_run = self._run_registry.create_run(
            conversation_id=self._conversation_id,
            subagent_name=parent_run.subagent_name,
            task=task,
            metadata=_build_lifecycle_metadata(
                session_mode="send",
                requester_session_key=self._requester_session_key,
                parent_run_id=run_id,
                lineage_root_run_id=lineage_root_run_id,
                delegation_depth=self._delegation_depth,
                extra={
                    **follow_up_options,
                    "max_active_runs_per_lineage": self._max_active_runs_per_lineage,
                },
            ),
            requester_session_key=self._requester_session_key,
            parent_run_id=run_id,
            lineage_root_run_id=lineage_root_run_id,
        )
        running = self._run_registry.mark_running(self._conversation_id, child_run.run_id)
        if running:
            self._pending_events.append(
                {"type": "subagent_run_started", "data": running.to_event_data()}
            )

        try:
            retry_count = await self._spawn_with_retry(
                run_id=child_run.run_id,
                subagent_name=parent_run.subagent_name,
                task=task,
                spawn_options=follow_up_options,
            )
            if retry_count > 0:
                self._run_registry.attach_metadata(
                    self._conversation_id,
                    child_run.run_id,
                    {"announce_retry_count": retry_count},
                )
            self._pending_events.append(
                {
                    "type": "subagent_session_message_sent",
                    "data": {
                        "conversation_id": self._conversation_id,
                        "parent_run_id": run_id,
                        "run_id": child_run.run_id,
                        "subagent_name": parent_run.subagent_name,
                    },
                }
            )
            return (
                f"Follow-up dispatched as run {child_run.run_id} "
                f"to SubAgent '{parent_run.subagent_name}'."
            )
        except Exception as exc:
            failed = self._run_registry.mark_failed(
                conversation_id=self._conversation_id,
                run_id=child_run.run_id,
                error=str(exc),
            )
            if failed:
                self._pending_events.append(
                    {"type": "subagent_run_failed", "data": failed.to_event_data()}
                )
            return f"Error: failed to send follow-up: {exc}"

    async def _invoke_spawn_callback(
        self,
        subagent_name: str,
        task: str,
        run_id: str,
        spawn_options: dict[str, Any],
    ) -> str:
        filtered_options = _filter_spawn_options(
            spawn_options,
            self._spawn_callback_params,
            self._spawn_callback_accepts_kwargs,
        )
        return await self._spawn_callback(subagent_name, task, run_id, **filtered_options)

    async def _spawn_with_retry(
        self,
        run_id: str,
        subagent_name: str,
        task: str,
        spawn_options: dict[str, Any],
    ) -> int:
        last_error: Exception | None = None
        for attempt in range(self._max_spawn_retries + 1):
            try:
                await self._invoke_spawn_callback(
                    subagent_name=subagent_name,
                    task=task,
                    run_id=run_id,
                    spawn_options=spawn_options,
                )
                return attempt
            except Exception as exc:
                last_error = exc
                if attempt >= self._max_spawn_retries:
                    break
                self._pending_events.append(
                    {
                        "type": "subagent_announce_retry",
                        "data": {
                            "conversation_id": self._conversation_id,
                            "run_id": run_id,
                            "subagent_name": subagent_name,
                            "attempt": attempt + 1,
                            "error": str(exc),
                            "next_delay_ms": self._retry_delay_ms,
                        },
                    }
                )
                _record_announce_event(
                    run_registry=self._run_registry,
                    conversation_id=self._conversation_id,
                    run_id=run_id,
                    event_type="retry",
                    payload={
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "next_delay_ms": self._retry_delay_ms,
                    },
                )
                await asyncio.sleep(self._retry_delay_ms / 1000)

        self._pending_events.append(
            {
                "type": "subagent_announce_giveup",
                "data": {
                    "conversation_id": self._conversation_id,
                    "run_id": run_id,
                    "subagent_name": subagent_name,
                    "attempts": self._max_spawn_retries + 1,
                    "error": str(last_error) if last_error else "unknown error",
                },
            }
        )
        _record_announce_event(
            run_registry=self._run_registry,
            conversation_id=self._conversation_id,
            run_id=run_id,
            event_type="giveup",
            payload={
                "attempts": self._max_spawn_retries + 1,
                "error": str(last_error) if last_error else "unknown error",
            },
        )
        if last_error:
            raise last_error
        raise RuntimeError("failed to send follow-up")


class SubAgentsControlTool(AgentTool):
    """List and control SubAgent runs."""

    _ACTIVE_STATUSES: ClassVar[set] = {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        subagent_names: list[str],
        subagent_descriptions: dict[str, str],
        cancel_callback: Callable[[str], Awaitable[bool]],
        restart_callback: Callable[[str, str, str], Awaitable[str]] | None = None,
        steer_rate_limit_ms: int = 2000,
        max_active_runs: int = 16,
        max_active_runs_per_lineage: int | None = None,
        max_children_per_requester: int | None = None,
        requester_session_key: str | None = None,
        delegation_depth: int = 0,
        max_delegation_depth: int = 1,
    ) -> None:
        super().__init__(
            name="subagents",
            description=(
                "SubAgent control plane. Actions: "
                "list (available agents + active counts), "
                "info (inspect run snapshots), "
                "log (replay run timeline), "
                "send (dispatch follow-up), "
                "kill (cancel active runs), steer (attach steering instruction)."
            ),
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._subagent_names = subagent_names
        self._subagent_descriptions = subagent_descriptions
        self._cancel_callback = cancel_callback
        self._restart_callback = restart_callback
        self._steer_rate_limit_ms = max(1, steer_rate_limit_ms)
        self._max_active_runs = max(1, max_active_runs)
        self._max_active_runs_per_lineage = max(1, max_active_runs_per_lineage or max_active_runs)
        self._max_children_per_requester = max(1, max_children_per_requester or max_active_runs)
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._delegation_depth = delegation_depth
        self._max_delegation_depth = max(1, max_delegation_depth)
        self._last_steer_at: dict[str, datetime] = {}
        self._pending_events: list[dict[str, Any]] = []

    def consume_pending_events(self) -> list[dict[str, Any]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "info", "log", "send", "kill", "steer"],
                    "description": "Control action.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Legacy target run id (use target for richer selectors).",
                },
                "target": {
                    "type": "string",
                    "description": (
                        "Target selector: run_id | #<active-index> | index:<active-index> | "
                        "label:<tag> | all."
                    ),
                },
                "instruction": {
                    "type": "string",
                    "description": "Steering instruction (required for steer).",
                },
                "task": {
                    "type": "string",
                    "description": "Follow-up task content (required for send).",
                },
                "run_timeout_seconds": {
                    "type": "integer",
                    "description": "Optional timeout for send action follow-up run (0 means no timeout).",
                    "minimum": 0,
                    "maximum": 3600,
                },
                "include_descendants": {
                    "type": "boolean",
                    "description": "For info/log action, include descendants of matched runs.",
                },
                "include_announce": {
                    "type": "boolean",
                    "description": "For log action, include announce/ack events.",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "list",
        run_id: str = "",
        target: str = "",
        instruction: str = "",
        task: str = "",
        run_timeout_seconds: int = 0,
        include_descendants: bool = True,
        include_announce: bool = True,
        **kwargs: Any,
    ) -> str:
        self._pending_events.clear()
        normalized_action = (action or "list").strip().lower()
        if normalized_action == "list":
            return self._list_subagents()
        if normalized_action == "info":
            return self._info_runs(
                run_id=run_id, target=target, include_descendants=include_descendants
            )
        if normalized_action == "log":
            return await self._log_runs(
                run_id=run_id,
                target=target,
                include_descendants=include_descendants,
                include_announce=include_announce,
            )
        if normalized_action == "send":
            blocked_error = self._ensure_mutation_allowed(action_name="send")
            if blocked_error:
                return blocked_error
            return await self._send_follow_up(
                run_id=run_id,
                target=target,
                task=task,
                run_timeout_seconds=run_timeout_seconds,
            )
        if normalized_action == "kill":
            blocked_error = self._ensure_mutation_allowed(action_name="kill")
            if blocked_error:
                return blocked_error
            return await self._kill_run(run_id=run_id, target=target)
        if normalized_action == "steer":
            blocked_error = self._ensure_mutation_allowed(action_name="steer")
            if blocked_error:
                return blocked_error
            return await self._steer_run(run_id=run_id, target=target, instruction=instruction)
        return "Error: action must be one of list|info|log|send|kill|steer"

    def _ensure_mutation_allowed(self, action_name: str) -> str | None:
        if self._delegation_depth >= self._max_delegation_depth:
            return (
                f"Error: subagents {action_name} is disabled at current delegation depth "
                f"({self._delegation_depth}/{self._max_delegation_depth})"
            )
        return None

    def _list_subagents(self) -> str:
        active_runs = self._run_registry.list_runs(
            self._conversation_id,
            statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
        )
        active_run_snapshots = [
            {
                "index": idx + 1,
                "target": f"#{idx + 1}",
                "run_id": run.run_id,
                "subagent_name": run.subagent_name,
                "status": run.status.value,
                "label": self._run_label(run),
                "created_at": run.created_at.isoformat(),
            }
            for idx, run in enumerate(active_runs)
        ]
        active_by_name: dict[str, int] = {}
        for run in active_runs:
            active_by_name[run.subagent_name] = active_by_name.get(run.subagent_name, 0) + 1
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "subagents": [
                    {
                        "name": name,
                        "description": self._subagent_descriptions.get(name, ""),
                        "active_runs": active_by_name.get(name, 0),
                    }
                    for name in self._subagent_names
                ],
                "active_run_count": len(active_runs),
                "active_runs": active_run_snapshots,
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def _run_label(run: SubAgentRun) -> str | None:
        for key in ("label", "run_label", "session_label"):
            value = str(run.metadata.get(key) or "").strip()
            if value:
                return value
        return None

    def _resolve_target_token(self, run_id: str, target: str) -> str:
        return (target or run_id).strip()

    def _resolve_target_runs(
        self,
        target_token: str,
        *,
        include_terminal: bool,
    ) -> tuple[list[SubAgentRun], str | None]:
        token = target_token.strip()
        if not token:
            return [], "Error: target (or run_id) is required"

        if token.lower() == "all":
            statuses = None if include_terminal else list(self._ACTIVE_STATUSES)
            runs = self._run_registry.list_runs(self._conversation_id, statuses=statuses)
            return runs, None

        if token.startswith("#") or token.lower().startswith("index:"):
            raw_index = token[1:] if token.startswith("#") else token.split(":", 1)[1]
            try:
                resolved_index = int(raw_index)
            except (TypeError, ValueError):
                return [], f"Error: invalid target index '{raw_index}'"
            if resolved_index <= 0:
                return [], "Error: target index must be >= 1"
            active_runs = self._run_registry.list_runs(
                self._conversation_id,
                statuses=list(self._ACTIVE_STATUSES),
            )
            if resolved_index > len(active_runs):
                return [], f"Error: target index #{resolved_index} out of range"
            return [active_runs[resolved_index - 1]], None

        if token.lower().startswith("label:"):
            label = token.split(":", 1)[1].strip()
            if not label:
                return [], "Error: label selector requires a non-empty value"
            statuses = None if include_terminal else list(self._ACTIVE_STATUSES)
            runs = self._run_registry.list_runs(self._conversation_id, statuses=statuses)
            matched = [run for run in runs if (self._run_label(run) or "") == label]
            if not matched:
                return [], f"Error: no runs found for label '{label}'"
            return matched, None

        run = self._run_registry.get_run(self._conversation_id, token)
        if not run:
            return [], f"Error: run_id '{token}' not found"
        return [run], None

    @staticmethod
    def _serialize_run_snapshot(run: SubAgentRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "subagent_name": run.subagent_name,
            "status": run.status.value,
            "task": run.task,
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "summary": run.summary,
            "error": run.error,
            "execution_time_ms": run.execution_time_ms,
            "tokens_used": run.tokens_used,
            "metadata": dict(run.metadata),
        }

    def _info_runs(self, run_id: str, target: str, include_descendants: bool) -> str:
        target_token = self._resolve_target_token(run_id, target)
        matched_runs, error = self._resolve_target_runs(target_token, include_terminal=True)
        if error:
            return error

        run_by_id: dict[str, SubAgentRun] = {}
        for run in matched_runs:
            run_by_id[run.run_id] = run
            if include_descendants:
                descendants = self._run_registry.list_descendant_runs(
                    self._conversation_id,
                    run.run_id,
                    include_terminal=True,
                )
                for descendant in descendants:
                    run_by_id.setdefault(descendant.run_id, descendant)

        runs = sorted(run_by_id.values(), key=lambda item: item.created_at)
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "target": target_token,
                "include_descendants": bool(include_descendants),
                "run_count": len(runs),
                "runs": [self._serialize_run_snapshot(run) for run in runs],
            },
            ensure_ascii=False,
            indent=2,
        )

    async def _log_runs(
        self,
        run_id: str,
        target: str,
        include_descendants: bool,
        include_announce: bool,
    ) -> str:
        target_token = self._resolve_target_token(run_id, target)
        matched_runs, error = self._resolve_target_runs(target_token, include_terminal=True)
        if error:
            return error
        if len(matched_runs) != 1:
            return f"Error: log target '{target_token}' requires exactly one matched run"
        timeline_tool = SessionsTimelineTool(self._run_registry, self._conversation_id)
        return await timeline_tool.execute(
            run_id=matched_runs[0].run_id,
            include_descendants=include_descendants,
            include_announce=include_announce,
        )

    async def _send_follow_up(
        self,
        run_id: str,
        target: str,
        task: str,
        run_timeout_seconds: int,
    ) -> str:
        if not task or not task.strip():
            return "Error: task is required for send"
        if not self._restart_callback:
            return "Error: send is unavailable because spawn callback is not configured"

        target_token = self._resolve_target_token(run_id, target)
        matched_runs, error = self._resolve_target_runs(target_token, include_terminal=True)
        if error:
            return error
        if len(matched_runs) != 1:
            return f"Error: send target '{target_token}' requires exactly one matched run"

        send_tool = SessionsSendTool(
            run_registry=self._run_registry,
            conversation_id=self._conversation_id,
            spawn_callback=self._restart_callback,
            max_active_runs=self._max_active_runs,
            max_active_runs_per_lineage=self._max_active_runs_per_lineage,
            max_children_per_requester=self._max_children_per_requester,
            requester_session_key=self._requester_session_key,
            delegation_depth=self._delegation_depth,
            max_delegation_depth=self._max_delegation_depth,
        )
        result = await send_tool.execute(
            run_id=matched_runs[0].run_id,
            task=task,
            run_timeout_seconds=run_timeout_seconds,
        )
        self._pending_events.extend(send_tool.consume_pending_events())
        return result

    async def _kill_run(self, run_id: str, target: str) -> str:
        target_token = self._resolve_target_token(run_id, target)
        matched_roots, error = self._resolve_target_runs(target_token, include_terminal=True)
        if error:
            return error

        if (
            len(matched_roots) == 1
            and matched_roots[0].run_id == target_token
            and matched_roots[0].status not in self._ACTIVE_STATUSES
        ):
            return f"Run {target_token} is already terminal ({matched_roots[0].status.value})"

        candidate_roots: dict[str, str] = {}
        for root in matched_roots:
            if root.status in self._ACTIVE_STATUSES:
                candidate_roots[root.run_id] = root.run_id
            descendants = self._run_registry.list_descendant_runs(
                self._conversation_id,
                root.run_id,
                include_terminal=False,
            )
            for descendant in descendants:
                if descendant.status in self._ACTIVE_STATUSES:
                    candidate_roots.setdefault(descendant.run_id, root.run_id)

        if not candidate_roots:
            if target_token == run_id and run_id and not target:
                return (
                    f"Marked run lineage {run_id} as cancelled (tasks already finished or detached)"
                )
            return f"No active runs matched target '{target_token}'"

        cancelled_count = 0
        for candidate_run_id, root_run_id in candidate_roots.items():
            candidate = self._run_registry.get_run(self._conversation_id, candidate_run_id)
            if not candidate or candidate.status not in self._ACTIVE_STATUSES:
                continue
            cancelled = await self._cancel_callback(candidate.run_id)
            updated = self._run_registry.mark_cancelled(
                conversation_id=self._conversation_id,
                run_id=candidate.run_id,
                reason="Cancelled by subagents tool",
                metadata={
                    "cancelled_by_tool": True,
                    "cascade_root_run_id": root_run_id,
                    "target_selector": target_token,
                },
                expected_statuses=list(self._ACTIVE_STATUSES),
            )
            if updated:
                self._pending_events.append(
                    {"type": "subagent_killed", "data": updated.to_event_data()}
                )
            if cancelled or updated:
                cancelled_count += 1

        if cancelled_count > 0:
            if target_token == run_id and run_id and not target:
                return f"Cancelled {cancelled_count} run(s) in lineage rooted at {run_id}"
            return f"Cancelled {cancelled_count} run(s) for target {target_token}"
        if target_token == run_id and run_id and not target:
            return f"Marked run lineage {run_id} as cancelled (tasks already finished or detached)"
        return f"No active runs matched target '{target_token}'"

    async def _steer_run(self, run_id: str, target: str, instruction: str) -> str:
        target_token = self._resolve_target_token(run_id, target)
        if not target_token:
            return "Error: target (or run_id) is required for steer"
        if not instruction or not instruction.strip():
            return "Error: instruction is required for steer"

        matched_runs, error = self._resolve_target_runs(target_token, include_terminal=True)
        if error:
            return error
        active_runs = [
            candidate for candidate in matched_runs if candidate.status in self._ACTIVE_STATUSES
        ]
        if len(active_runs) != 1:
            if (
                len(matched_runs) == 1
                and matched_runs[0].run_id == target_token
                and matched_runs[0].status not in self._ACTIVE_STATUSES
            ):
                return f"Run {target_token} is already terminal ({matched_runs[0].status.value})"
            return f"Error: steer target '{target_token}' requires exactly one active run"
        run = active_runs[0]
        resolved_run_id = run.run_id

        now = datetime.now(UTC)
        last_steer = self._last_steer_at.get(resolved_run_id)
        if last_steer:
            elapsed_ms = int((now - last_steer).total_seconds() * 1000)
            if elapsed_ms < self._steer_rate_limit_ms:
                return (
                    "Error: steer rate limit exceeded. "
                    f"Wait at least {self._steer_rate_limit_ms - elapsed_ms}ms."
                )
        self._last_steer_at[resolved_run_id] = now

        if not self._restart_callback:
            updated = self._run_registry.attach_metadata(
                conversation_id=self._conversation_id,
                run_id=resolved_run_id,
                metadata={
                    "steer_instruction": instruction,
                    "steered_at": now.isoformat(),
                },
            )
            if not updated:
                return f"Error: run_id '{resolved_run_id}' not found"
            self._pending_events.append(
                {
                    "type": "subagent_steered",
                    "data": {
                        **updated.to_event_data(),
                        "instruction": instruction,
                    },
                }
            )
            return f"Steering instruction attached to run {resolved_run_id}"

        cancelled = await self._cancel_callback(resolved_run_id)
        updated_old = self._run_registry.mark_cancelled(
            conversation_id=self._conversation_id,
            run_id=resolved_run_id,
            reason="Cancelled by steer restart",
            metadata={"steer_instruction": instruction},
            expected_statuses=list(self._ACTIVE_STATUSES),
        )
        if updated_old:
            self._pending_events.append(
                {"type": "subagent_killed", "data": updated_old.to_event_data()}
            )

        restart_task = f"{run.task}\n\n[Steering Instruction]\n{instruction.strip()}"
        lineage_root = str(run.metadata.get("lineage_root_run_id") or resolved_run_id).strip()
        replacement = self._run_registry.create_run(
            conversation_id=self._conversation_id,
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
        running = self._run_registry.mark_running(self._conversation_id, replacement.run_id)
        if running:
            self._pending_events.append(
                {"type": "subagent_run_started", "data": running.to_event_data()}
            )

        try:
            await self._restart_callback(run.subagent_name, restart_task, replacement.run_id)
        except Exception as exc:
            failed = self._run_registry.mark_failed(
                conversation_id=self._conversation_id,
                run_id=replacement.run_id,
                error=str(exc),
                expected_statuses=[SubAgentRunStatus.RUNNING],
            )
            if failed:
                self._pending_events.append(
                    {"type": "subagent_run_failed", "data": failed.to_event_data()}
                )
            return f"Error: failed to steer run {resolved_run_id}: {exc}"

        if updated_old:
            self._run_registry.attach_metadata(
                conversation_id=self._conversation_id,
                run_id=resolved_run_id,
                metadata={"replaced_by_run_id": replacement.run_id},
            )
        self._pending_events.append(
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
        return f"Steered run {resolved_run_id}; restarted as {replacement.run_id}"
