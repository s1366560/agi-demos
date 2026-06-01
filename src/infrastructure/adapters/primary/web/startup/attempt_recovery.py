"""Startup wiring for :class:`WorkspaceAttemptRecoveryService`.

Always-on. Runs a sweep at boot to recover orphaned attempts left over from
a prior process and then starts the periodic watchdog loop that rescues
attempts stale from this process.

Disable only for tests / emergencies via
``WORKSPACE_ATTEMPT_RECOVERY_ENABLED=false``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

if TYPE_CHECKING:
    from src.domain.model.workspace.workspace_task_session_attempt import (
        WorkspaceTaskSessionAttempt,
    )
    from src.infrastructure.agent.workspace.workspace_attempt_recovery import (
        WorkspaceAttemptRecoveryService,
    )

logger = logging.getLogger(__name__)

_ENABLED_ENV = "WORKSPACE_ATTEMPT_RECOVERY_ENABLED"
_STALE_ENV = "WORKSPACE_ATTEMPT_RECOVERY_STALE_SECONDS"
_INTERVAL_ENV = "WORKSPACE_ATTEMPT_RECOVERY_INTERVAL_SECONDS"
_GRACE_ENV = "WORKSPACE_ATTEMPT_RECOVERY_STARTUP_GRACE_SECONDS"
_MAX_ATTEMPTS_ENV = "WORKSPACE_ATTEMPT_RECOVERY_MAX_ATTEMPTS_PER_SWEEP"
_ERROR_EVENT_GRACE_ENV = "WORKSPACE_ATTEMPT_RECOVERY_ERROR_EVENT_GRACE_SECONDS"
_ATTEMPT_CLEANUP_COUNT_RE = re.compile(r"\bmatched=(?P<count>\d+)\b")

_recovery: WorkspaceAttemptRecoveryService | None = None


def _enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV)
    if raw is None:
        return True  # always-on by default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


async def _enqueue_handoff_resume(
    attempt: WorkspaceTaskSessionAttempt,
    summary: str,
    actor_user_id: str,
) -> None:
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
        SqlWorkspacePlanOutboxRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
        SqlWorkspaceTaskRepository,
    )
    from src.infrastructure.agent.workspace.workspace_metadata_keys import (
        ROOT_GOAL_TASK_ID,
        WORKSPACE_PLAN_ID,
        WORKSPACE_PLAN_NODE_ID,
    )
    from src.infrastructure.agent.workspace_plan.outbox_handlers import HANDOFF_RESUME_EVENT

    async with async_session_factory() as db:
        task = await SqlWorkspaceTaskRepository(db).find_by_id(attempt.workspace_task_id)
        if task is None:
            return
        worker_agent_id = attempt.worker_agent_id or task.assignee_agent_id
        if not worker_agent_id:
            return

        metadata = dict(task.metadata or {})
        raw_plan_id = metadata.get(WORKSPACE_PLAN_ID)
        plan_id = raw_plan_id if isinstance(raw_plan_id, str) and raw_plan_id else None
        raw_node_id = metadata.get(WORKSPACE_PLAN_NODE_ID)
        node_id = raw_node_id if isinstance(raw_node_id, str) and raw_node_id else None
        root_goal_task_id = attempt.root_goal_task_id
        if not root_goal_task_id:
            raw_root_id = metadata.get(ROOT_GOAL_TASK_ID)
            root_goal_task_id = raw_root_id if isinstance(raw_root_id, str) else ""

        _ = await SqlWorkspacePlanOutboxRepository(db).enqueue(
            plan_id=plan_id,
            workspace_id=attempt.workspace_id,
            event_type=HANDOFF_RESUME_EVENT,
            payload={
                "workspace_id": attempt.workspace_id,
                "task_id": attempt.workspace_task_id,
                "node_id": node_id,
                "worker_agent_id": worker_agent_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": attempt.leader_agent_id,
                "previous_attempt_id": attempt.id,
                "root_goal_task_id": root_goal_task_id,
                "summary": summary,
                "reason": "worker_restart"
                if summary == "recovered_after_restart_no_heartbeat"
                else "retry",
                "force_schedule": True,
            },
            metadata={
                "source": "workspace_attempt_recovery",
                "previous_attempt_id": attempt.id,
            },
        )
        await db.commit()


def _attempt_runtime_cleanup_command(attempt_id: str) -> str:
    attempt_marker = shlex.quote(f"/.memstack/worktrees/{attempt_id}")
    quoted_attempt_id = shlex.quote(attempt_id)
    return "\n".join(
        [
            f"attempt_id={quoted_attempt_id}",
            f"attempt_marker={attempt_marker}",
            "cleanup_pgid=$(awk '/^NSpgid:/{print $2; exit}' /proc/$$/status 2>/dev/null || true)",
            "matched=0",
            "group_count=0",
            'groups=""',
            "for status_path in /proc/[0-9]*/status; do",
            '  [ -e "$status_path" ] || continue',
            "  proc_dir=${status_path%/status}",
            "  pid=${proc_dir##*/}",
            '  case "$pid" in ""|1|$$) continue ;; esac',
            '  cwd=$(readlink "$proc_dir/cwd" 2>/dev/null || true)',
            '  case "$cwd" in',
            '    *"$attempt_marker"|*"$attempt_marker"/*)',
            "      matched=$((matched + 1))",
            "      pgid=$(awk '/^NSpgid:/{print $2; exit}' \"$status_path\" 2>/dev/null || true)",
            '      if [ -n "$pgid" ] && [ "$pgid" != "1" ] && [ "$pgid" != "$cleanup_pgid" ]; then',
            '        case " $groups " in',
            '          *" $pgid "*) ;;',
            "          *)",
            '            groups="$groups $pgid"',
            "            group_count=$((group_count + 1))",
            '            kill -TERM "-$pgid" 2>/dev/null || true',
            "            ;;",
            "        esac",
            "      else",
            '        kill -TERM "$pid" 2>/dev/null || true',
            "      fi",
            "      ;;",
            "  esac",
            "done",
            "sleep 1",
            'for pgid in $groups; do kill -KILL "-$pgid" 2>/dev/null || true; done',
            "remaining=0",
            "for status_path in /proc/[0-9]*/status; do",
            '  [ -e "$status_path" ] || continue',
            "  proc_dir=${status_path%/status}",
            "  pid=${proc_dir##*/}",
            '  case "$pid" in ""|1|$$) continue ;; esac',
            '  cwd=$(readlink "$proc_dir/cwd" 2>/dev/null || true)',
            '  case "$cwd" in',
            '    *"$attempt_marker"|*"$attempt_marker"/*)',
            "      remaining=$((remaining + 1))",
            '      kill -KILL "$pid" 2>/dev/null || true',
            "      ;;",
            "  esac",
            "done",
            (
                'printf "[workspace_attempt_cleanup] attempt_id=%s matched=%s '
                + 'groups=%s remaining=%s\\n" "$attempt_id" "$matched" "$group_count" '
                + '"$remaining"'
            ),
        ]
    )


def _tool_result_text(raw: object) -> str:
    if not isinstance(raw, Mapping):
        return ""
    mapping = cast(Mapping[str, object], raw)
    content = mapping.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for item in cast(list[object], content):
            if isinstance(item, Mapping):
                item_mapping = cast(Mapping[str, object], item)
                text = item_mapping.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif item is not None:
                parts.append(str(item))
        return "\n".join(parts)
    for key in ("text", "stdout", "stderr"):
        value = mapping.get(key)
        if isinstance(value, str):
            return value
    return ""


def _attempt_cleanup_count(raw: object) -> int:
    match = _ATTEMPT_CLEANUP_COUNT_RE.search(_tool_result_text(raw))
    if match is None:
        return 0
    return int(match.group("count"))


async def _cleanup_attempt_runtime_processes(attempt: WorkspaceTaskSessionAttempt) -> int:
    from sqlalchemy import select

    from src.infrastructure.adapters.primary.web.routers.sandbox.utils import (
        ensure_sandbox_sync,
        get_sandbox_adapter,
    )
    from src.infrastructure.adapters.secondary.persistence.models import (
        ProjectSandbox,
        WorkspaceModel,
    )

    async with async_session_factory() as db:
        sandbox_id = (
            await db.execute(
                refresh_select_statement(
                    select(ProjectSandbox.sandbox_id)
                    .join(WorkspaceModel, WorkspaceModel.project_id == ProjectSandbox.project_id)
                    .where(
                        WorkspaceModel.id == attempt.workspace_id,
                        ProjectSandbox.tenant_id == WorkspaceModel.tenant_id,
                    )
                )
            )
        ).scalar_one_or_none()
    if not sandbox_id:
        return 0

    adapter = get_sandbox_adapter()
    with contextlib.suppress(Exception):
        await ensure_sandbox_sync()

    raw = await adapter.call_tool(
        sandbox_id,
        "bash",
        {
            "command": _attempt_runtime_cleanup_command(attempt.id),
            "timeout": 20,
        },
        timeout=25.0,
    )
    return _attempt_cleanup_count(raw)


async def initialize_attempt_recovery() -> WorkspaceAttemptRecoveryService | None:
    global _recovery

    if _recovery is not None and _recovery.is_running:
        return _recovery

    if not _enabled():
        logger.info(
            "workspace_attempt_recovery.disabled",
            extra={"event": "workspace_attempt_recovery.disabled"},
        )
        return None

    try:
        from src.application.services.agent.runtime_bootstrapper import AgentRuntimeBootstrapper
        from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
            schedule_autonomy_tick,
        )
        from src.infrastructure.agent.workspace.workspace_attempt_recovery import (
            DEFAULT_CHECK_INTERVAL_SECONDS,
            DEFAULT_ERROR_EVENT_GRACE_SECONDS,
            DEFAULT_MAX_ATTEMPTS_PER_SWEEP,
            DEFAULT_STALE_SECONDS,
            DEFAULT_STARTUP_GRACE_SECONDS,
            WorkspaceAttemptRecoveryService,
        )
        from src.infrastructure.agent.workspace.workspace_goal_runtime import (
            apply_workspace_worker_report,
        )
        from src.infrastructure.agent.workspace.workspace_supervisor import (
            get_workspace_supervisor,
        )

        stale_seconds = _int_env(_STALE_ENV, DEFAULT_STALE_SECONDS)
        check_interval_seconds = _int_env(_INTERVAL_ENV, DEFAULT_CHECK_INTERVAL_SECONDS)
        startup_grace_seconds = _int_env(_GRACE_ENV, DEFAULT_STARTUP_GRACE_SECONDS)
        max_attempts_per_sweep = _int_env(_MAX_ATTEMPTS_ENV, DEFAULT_MAX_ATTEMPTS_PER_SWEEP)
        error_event_grace_seconds = _int_env(
            _ERROR_EVENT_GRACE_ENV, DEFAULT_ERROR_EVENT_GRACE_SECONDS
        )

        def _liveness_lookup() -> list[str]:
            supervisor = get_workspace_supervisor()
            if supervisor is None:
                return []
            snapshot = supervisor.get_liveness_snapshot()
            current_monotonic = time.monotonic()
            max_live_age = stale_seconds + check_interval_seconds + 5
            live: list[str] = []
            for attempt_id, info in snapshot.items():
                last_seen = info.get("last_seen_monotonic")
                if not isinstance(last_seen, int | float):
                    continue
                if current_monotonic - last_seen <= max_live_age:
                    live.append(attempt_id)
            return live

        _recovery = WorkspaceAttemptRecoveryService(
            session_factory=async_session_factory,
            apply_report=apply_workspace_worker_report,
            schedule_tick=schedule_autonomy_tick,
            enqueue_resume=_enqueue_handoff_resume,
            cancel_conversation=AgentRuntimeBootstrapper.cancel_local_chat,
            cleanup_attempt_runtime=_cleanup_attempt_runtime_processes,
            runtime_active_lookup=AgentRuntimeBootstrapper.has_running_local_subprocess,
            liveness_lookup=_liveness_lookup,
            stale_seconds=stale_seconds,
            startup_grace_seconds=startup_grace_seconds,
            check_interval_seconds=check_interval_seconds,
            max_attempts_per_sweep=max_attempts_per_sweep,
            error_event_grace_seconds=error_event_grace_seconds,
        )
        await _recovery.start()
        return _recovery
    except Exception:
        logger.warning(
            "workspace_attempt_recovery.start_failed",
            exc_info=True,
            extra={"event": "workspace_attempt_recovery.start_failed"},
        )
        return None


async def recover_workspace_attempts_once(workspace_id: str) -> int:
    recovery = await initialize_attempt_recovery()
    if recovery is None:
        return 0
    return await recovery.workspace_sweep(workspace_id)


async def shutdown_attempt_recovery() -> None:
    global _recovery
    if _recovery is None:
        return
    try:
        await _recovery.stop()
    except Exception:
        logger.warning(
            "workspace_attempt_recovery.stop_failed",
            exc_info=True,
            extra={"event": "workspace_attempt_recovery.stop_failed"},
        )
    finally:
        _recovery = None
