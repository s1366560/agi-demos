"""Session-oriented SubAgent collaboration tools."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class SessionsSpawnTool(AgentTool):
    """Spawn a SubAgent run as a non-blocking session."""

    def __init__(
        self,
        subagent_names: List[str],
        subagent_descriptions: Dict[str, str],
        spawn_callback: Callable[[str, str, str], Awaitable[str]],
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        max_active_runs: int = 16,
        max_children_per_requester: Optional[int] = None,
        requester_session_key: Optional[str] = None,
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
        self._max_children_per_requester = max(
            1, max_children_per_requester or max_active_runs
        )
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._delegation_depth = delegation_depth
        self._max_delegation_depth = max(1, max_delegation_depth)
        self._max_spawn_retries = max(0, max_spawn_retries)
        self._retry_delay_ms = max(1, retry_delay_ms)
        self._pending_events: List[Dict[str, Any]] = []

    def consume_pending_events(self) -> List[Dict[str, Any]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> Dict[str, Any]:
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
            },
            "required": ["subagent_name", "task"],
        }

    async def execute(
        self,
        subagent_name: str = "",
        task: str = "",
        run_timeout_seconds: int = 0,
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
            subagent_name=subagent_name,
            task=task,
            metadata={
                "session_mode": "spawn",
                "delegation_depth": self._delegation_depth,
                "requester_session_key": self._requester_session_key,
                "run_timeout_seconds": timeout_seconds,
            },
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
                subagent_name=subagent_name,
                task=task,
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
                        "subagent_name": subagent_name,
                    },
                }
            )
            return (
                f"Spawned SubAgent session {run.run_id} for '{subagent_name}'. "
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

    async def _spawn_with_retry(self, run_id: str, subagent_name: str, task: str) -> int:
        last_error: Optional[Exception] = None
        for attempt in range(self._max_spawn_retries + 1):
            try:
                await self._spawn_callback(subagent_name, task, run_id)
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
        if last_error:
            raise last_error
        raise RuntimeError("failed to spawn session")


class SessionsListTool(AgentTool):
    """List active SubAgent sessions."""

    def __init__(self, run_registry: SubAgentRunRegistry, conversation_id: str) -> None:
        super().__init__(
            name="sessions_list",
            description=(
                "List active SubAgent sessions for this conversation. "
                "Use status='active' for pending/running runs."
            ),
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id

    def get_parameters_schema(self) -> Dict[str, Any]:
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum runs to return.",
                    "minimum": 1,
                    "maximum": 200,
                },
            },
            "required": [],
        }

    async def execute(self, status: str = "active", limit: int = 20, **kwargs: Any) -> str:
        statuses: Optional[List[SubAgentRunStatus]]
        if status == "active":
            statuses = [SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING]
        elif status:
            try:
                statuses = [SubAgentRunStatus(status)]
            except ValueError:
                return f"Error: invalid status '{status}'"
        else:
            statuses = None

        runs = self._run_registry.list_runs(self._conversation_id, statuses=statuses)[
            : max(1, limit)
        ]
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "count": len(runs),
                "runs": [run.to_event_data() for run in runs],
            },
            ensure_ascii=False,
            indent=2,
        )


class SessionsHistoryTool(AgentTool):
    """List SubAgent session history."""

    def __init__(self, run_registry: SubAgentRunRegistry, conversation_id: str) -> None:
        super().__init__(
            name="sessions_history",
            description="List historical SubAgent sessions (including terminal runs).",
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum history items to return.",
                    "minimum": 1,
                    "maximum": 200,
                }
            },
            "required": [],
        }

    async def execute(self, limit: int = 50, **kwargs: Any) -> str:
        runs = self._run_registry.list_runs(self._conversation_id)[: max(1, limit)]
        return json.dumps(
            {
                "conversation_id": self._conversation_id,
                "count": len(runs),
                "runs": [run.to_event_data() for run in runs],
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
        spawn_callback: Callable[[str, str, str], Awaitable[str]],
        max_active_runs: int = 16,
        max_children_per_requester: Optional[int] = None,
        requester_session_key: Optional[str] = None,
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
        self._max_children_per_requester = max(
            1, max_children_per_requester or max_active_runs
        )
        self._requester_session_key = (requester_session_key or conversation_id).strip()
        self._delegation_depth = delegation_depth
        self._max_delegation_depth = max(1, max_delegation_depth)
        self._max_spawn_retries = max(0, max_spawn_retries)
        self._retry_delay_ms = max(1, retry_delay_ms)
        self._pending_events: List[Dict[str, Any]] = []

    def consume_pending_events(self) -> List[Dict[str, Any]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> Dict[str, Any]:
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
        try:
            parent_timeout = int(parent_run.metadata.get("run_timeout_seconds") or 0)
        except (TypeError, ValueError):
            parent_timeout = 0

        child_run = self._run_registry.create_run(
            conversation_id=self._conversation_id,
            subagent_name=parent_run.subagent_name,
            task=task,
            metadata={
                "session_mode": "send",
                "parent_run_id": run_id,
                "lineage_root_run_id": lineage_root_run_id,
                "requester_session_key": self._requester_session_key,
                "run_timeout_seconds": timeout_seconds or parent_timeout,
            },
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

    async def _spawn_with_retry(self, run_id: str, subagent_name: str, task: str) -> int:
        last_error: Optional[Exception] = None
        for attempt in range(self._max_spawn_retries + 1):
            try:
                await self._spawn_callback(subagent_name, task, run_id)
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
        if last_error:
            raise last_error
        raise RuntimeError("failed to send follow-up")


class SubAgentsControlTool(AgentTool):
    """List and control SubAgent runs."""

    def __init__(
        self,
        run_registry: SubAgentRunRegistry,
        conversation_id: str,
        subagent_names: List[str],
        subagent_descriptions: Dict[str, str],
        cancel_callback: Callable[[str], Awaitable[bool]],
        restart_callback: Optional[Callable[[str, str, str], Awaitable[str]]] = None,
        steer_rate_limit_ms: int = 2000,
    ) -> None:
        super().__init__(
            name="subagents",
            description=(
                "SubAgent control plane. Actions: "
                "list (available agents + active counts), "
                "kill (cancel an active run), steer (attach steering instruction)."
            ),
        )
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._subagent_names = subagent_names
        self._subagent_descriptions = subagent_descriptions
        self._cancel_callback = cancel_callback
        self._restart_callback = restart_callback
        self._steer_rate_limit_ms = max(1, steer_rate_limit_ms)
        self._last_steer_at: Dict[str, datetime] = {}
        self._pending_events: List[Dict[str, Any]] = []

    def consume_pending_events(self) -> List[Dict[str, Any]]:
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "kill", "steer"],
                    "description": "Control action.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Target run id (required for kill/steer).",
                },
                "instruction": {
                    "type": "string",
                    "description": "Steering instruction (required for steer).",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "list",
        run_id: str = "",
        instruction: str = "",
        **kwargs: Any,
    ) -> str:
        self._pending_events.clear()
        if action == "list":
            return self._list_subagents()
        if action == "kill":
            return await self._kill_run(run_id)
        if action == "steer":
            return await self._steer_run(run_id, instruction)
        return "Error: action must be one of list|kill|steer"

    def _list_subagents(self) -> str:
        active_runs = self._run_registry.list_runs(
            self._conversation_id,
            statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
        )
        active_by_name: Dict[str, int] = {}
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
            },
            ensure_ascii=False,
            indent=2,
        )

    async def _kill_run(self, run_id: str) -> str:
        if not run_id:
            return "Error: run_id is required for kill"

        run = self._run_registry.get_run(self._conversation_id, run_id)
        if not run:
            return f"Error: run_id '{run_id}' not found"
        if run.status not in {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}:
            return f"Run {run_id} is already terminal ({run.status.value})"

        runs_to_cancel = [run]
        runs_to_cancel.extend(
            self._run_registry.list_descendant_runs(
                self._conversation_id,
                run_id,
                include_terminal=False,
            )
        )
        cancelled_count = 0
        for candidate in runs_to_cancel:
            if candidate.status not in {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}:
                continue
            cancelled = await self._cancel_callback(candidate.run_id)
            updated = self._run_registry.mark_cancelled(
                conversation_id=self._conversation_id,
                run_id=candidate.run_id,
                reason="Cancelled by subagents tool",
                metadata={
                    "cancelled_by_tool": True,
                    "cascade_root_run_id": run_id,
                },
                expected_statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
            )
            if updated:
                self._pending_events.append(
                    {"type": "subagent_killed", "data": updated.to_event_data()}
                )
            if cancelled or updated:
                cancelled_count += 1
        if cancelled_count > 0:
            return f"Cancelled {cancelled_count} run(s) in lineage rooted at {run_id}"
        return f"Marked run lineage {run_id} as cancelled (tasks already finished or detached)"

    async def _steer_run(self, run_id: str, instruction: str) -> str:
        if not run_id:
            return "Error: run_id is required for steer"
        if not instruction or not instruction.strip():
            return "Error: instruction is required for steer"
        run = self._run_registry.get_run(self._conversation_id, run_id)
        if not run:
            return f"Error: run_id '{run_id}' not found"
        if run.status not in {SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING}:
            return f"Run {run_id} is already terminal ({run.status.value})"

        now = datetime.now(timezone.utc)
        last_steer = self._last_steer_at.get(run_id)
        if last_steer:
            elapsed_ms = int((now - last_steer).total_seconds() * 1000)
            if elapsed_ms < self._steer_rate_limit_ms:
                return (
                    "Error: steer rate limit exceeded. "
                    f"Wait at least {self._steer_rate_limit_ms - elapsed_ms}ms."
                )
        self._last_steer_at[run_id] = now

        if not self._restart_callback:
            updated = self._run_registry.attach_metadata(
                conversation_id=self._conversation_id,
                run_id=run_id,
                metadata={
                    "steer_instruction": instruction,
                    "steered_at": now.isoformat(),
                },
            )
            if not updated:
                return f"Error: run_id '{run_id}' not found"
            self._pending_events.append(
                {
                    "type": "subagent_steered",
                    "data": {
                        **updated.to_event_data(),
                        "instruction": instruction,
                    },
                }
            )
            return f"Steering instruction attached to run {run_id}"

        cancelled = await self._cancel_callback(run_id)
        updated_old = self._run_registry.mark_cancelled(
            conversation_id=self._conversation_id,
            run_id=run_id,
            reason="Cancelled by steer restart",
            metadata={"steer_instruction": instruction},
            expected_statuses=[SubAgentRunStatus.PENDING, SubAgentRunStatus.RUNNING],
        )
        if updated_old:
            self._pending_events.append(
                {"type": "subagent_killed", "data": updated_old.to_event_data()}
            )

        restart_task = f"{run.task}\n\n[Steering Instruction]\n{instruction.strip()}"
        lineage_root = str(run.metadata.get("lineage_root_run_id") or run_id).strip()
        replacement = self._run_registry.create_run(
            conversation_id=self._conversation_id,
            subagent_name=run.subagent_name,
            task=restart_task,
            metadata={
                **dict(run.metadata),
                "session_mode": "steer_restart",
                "steered_from_run_id": run_id,
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
            return f"Error: failed to steer run {run_id}: {exc}"

        if updated_old:
            self._run_registry.attach_metadata(
                conversation_id=self._conversation_id,
                run_id=run_id,
                metadata={"replaced_by_run_id": replacement.run_id},
            )
        self._pending_events.append(
            {
                "type": "subagent_steered",
                "data": {
                    **(running.to_event_data() if running else replacement.to_event_data()),
                    "instruction": instruction,
                    "previous_run_id": run_id,
                    "new_run_id": replacement.run_id,
                    "cancel_requested": cancelled,
                },
            }
        )
        return f"Steered run {run_id}; restarted as {replacement.run_id}"
