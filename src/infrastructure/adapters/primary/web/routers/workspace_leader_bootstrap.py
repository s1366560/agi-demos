from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_agent_autonomy import is_goal_root_task
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.configuration.di_container import DIContainer
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_message import MessageSenderType
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.infrastructure.adapters.primary.web.routers.agent.utils import get_container_with_db
from src.infrastructure.adapters.primary.web.routers.workspace_chat import (
    _fire_mention_routing,
    get_message_service,
)
from src.infrastructure.adapters.primary.web.startup.container import get_app_container
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentDefinitionModel,
    User,
    WorkspaceMessageModel,
)
from src.infrastructure.agent.sisyphus.builtin_agent import (
    BUILTIN_AGENT_NAMESPACE,
    BUILTIN_SISYPHUS_DISPLAY_NAME,
    BUILTIN_SISYPHUS_ID,
    BUILTIN_SISYPHUS_NAME,
    build_builtin_sisyphus_agent,
)
from src.infrastructure.agent.state.agent_worker_state import get_redis_client

logger = logging.getLogger(__name__)

AUTO_TRIGGER_COOLDOWN_SECONDS = 60
_AUTO_TRIGGER_COOLDOWN_KEY = "workspace:autonomy:last_trigger:{workspace_id}:{root_task_id}"
_REMEDIATION_STATUSES_NEEDING_PROGRESS = frozenset({"replan_required", "ready_for_completion"})

_AUTO_TICK_ENV = "WORKSPACE_AUTONOMY_AUTO_TICK_ENABLED"
_AUTO_COMPLETE_ENV = "WORKSPACE_AUTONOMY_AUTO_COMPLETE_ENABLED"
_background_tasks: set[asyncio.Task[Any]] = set()
# Per-workspace dedup so a storm of worker terminal reports against the same
# workspace does not queue a pile of ticks. At most one tick can be in-flight
# per workspace; subsequent schedules are dropped until it finishes. The 60s
# Redis cooldown remains the secondary guard against repeat triggers once the
# tick itself completes.
_inflight_ticks: dict[str, asyncio.Task[Any]] = {}


def _auto_tick_enabled() -> bool:
    raw = os.environ.get(_AUTO_TICK_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _auto_complete_enabled() -> bool:
    raw = os.environ.get(_AUTO_COMPLETE_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _resolve_container(request: Request | None, db: AsyncSession) -> DIContainer:
    """Build a DIContainer bound to ``db``.

    When called from an HTTP request, use the request's app state container.
    When called from a background task (``request is None``), fall back to the
    module-level application container initialized during startup.
    """
    if request is not None:
        return get_container_with_db(request, db)
    app_container = get_app_container()
    if app_container is None:
        raise RuntimeError(
            "Application DI container is not initialized; "
            "cannot run headless workspace autonomy tick."
        )
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


def _format_agent_mention(display_name: str | None, agent_id: str) -> str:
    handle = (display_name or "").strip() or agent_id
    return f'@"{handle}"' if " " in handle else f"@{handle}"


def _legacy_builtin_conflict_name(agent_id: str) -> str:
    suffix = agent_id.replace(":", "-")
    candidate = f"{BUILTIN_SISYPHUS_NAME}-legacy-{suffix}"
    return candidate[:100]


async def _rename_legacy_sisyphus_name_conflict(db: AsyncSession) -> AgentDefinitionModel | None:
    result = await db.execute(
        refresh_select_statement(
            select(AgentDefinitionModel)
            .where(AgentDefinitionModel.name == BUILTIN_SISYPHUS_NAME)
            .where(AgentDefinitionModel.id != BUILTIN_SISYPHUS_ID)
            .limit(1)
        )
    )
    conflicting_row = cast(AgentDefinitionModel | None, result.scalar_one_or_none())
    if conflicting_row is None:
        return None

    old_name = conflicting_row.name
    conflicting_row.name = _legacy_builtin_conflict_name(conflicting_row.id)
    metadata = dict(conflicting_row.metadata_json or {})
    metadata["renamed_from_builtin_name"] = old_name
    metadata["renamed_for_builtin_id"] = BUILTIN_SISYPHUS_ID
    conflicting_row.metadata_json = metadata
    logger.warning(
        "Renaming legacy agent definition that conflicts with built-in Sisyphus bootstrap",
        extra={
            "agent_id": conflicting_row.id,
            "old_name": old_name,
            "new_name": conflicting_row.name,
        },
    )
    await db.flush()
    return conflicting_row


async def ensure_workspace_leader_binding(
    *,
    request: Request | None = None,
    db: AsyncSession,
    workspace_id: str,
) -> tuple[WorkspaceAgent, bool]:
    container = _resolve_container(request, db)
    bindings = await container.workspace_agent_repository().find_by_workspace(
        workspace_id=workspace_id,
        active_only=True,
        limit=1,
        offset=0,
    )
    if bindings:
        return bindings[0], False

    builtin_row = await db.get(AgentDefinitionModel, BUILTIN_SISYPHUS_ID)
    if builtin_row is None:
        await _rename_legacy_sisyphus_name_conflict(db)
        builtin_agent = build_builtin_sisyphus_agent(tenant_id=BUILTIN_AGENT_NAMESPACE)
        db.add(
            AgentDefinitionModel(
                id=builtin_agent.id,
                tenant_id=BUILTIN_AGENT_NAMESPACE,
                project_id=None,
                name=builtin_agent.name,
                display_name=builtin_agent.display_name,
                system_prompt=builtin_agent.system_prompt,
                trigger_description=builtin_agent.trigger.description,
                trigger_examples=list(builtin_agent.trigger.examples),
                trigger_keywords=list(builtin_agent.trigger.keywords),
                model=builtin_agent.model.value,
                persona_files=list(builtin_agent.persona_files),
                allowed_tools=list(builtin_agent.allowed_tools),
                allowed_skills=list(builtin_agent.allowed_skills),
                allowed_mcp_servers=list(builtin_agent.allowed_mcp_servers),
                max_tokens=builtin_agent.max_tokens,
                temperature=builtin_agent.temperature,
                max_iterations=builtin_agent.max_iterations,
                workspace_dir=builtin_agent.workspace_dir,
                workspace_config=builtin_agent.workspace_config.to_dict(),
                can_spawn=builtin_agent.can_spawn,
                max_spawn_depth=builtin_agent.max_spawn_depth,
                agent_to_agent_enabled=builtin_agent.agent_to_agent_enabled,
                agent_to_agent_allowlist=builtin_agent.agent_to_agent_allowlist,
                discoverable=builtin_agent.discoverable,
                source=builtin_agent.source.value,
                enabled=builtin_agent.enabled,
                max_retries=builtin_agent.max_retries,
                fallback_models=list(builtin_agent.fallback_models),
                total_invocations=builtin_agent.total_invocations,
                avg_execution_time_ms=builtin_agent.avg_execution_time_ms,
                success_rate=builtin_agent.success_rate,
                metadata_json=builtin_agent.metadata,
                session_policy=builtin_agent.session_policy.to_dict()
                if builtin_agent.session_policy
                else None,
                delegate_config=builtin_agent.delegate_config.to_dict()
                if builtin_agent.delegate_config
                else None,
                created_at=builtin_agent.created_at,
                updated_at=builtin_agent.updated_at,
            )
        )
        await db.flush()

    binding = await container.workspace_agent_repository().save(
        WorkspaceAgent(
            id=WorkspaceAgent.generate_id(),
            workspace_id=workspace_id,
            agent_id=BUILTIN_SISYPHUS_ID,
            display_name=BUILTIN_SISYPHUS_DISPLAY_NAME,
            description="Auto-bound builtin workspace leader",
            config={"auto_bound_builtin": True, "workspace_role": "leader"},
            is_active=True,
            label="Leader",
            status="idle",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    return binding, True


async def _is_on_cooldown(workspace_id: str, root_task_id: str) -> bool:
    try:
        redis_client = await get_redis_client()
    except Exception:
        logger.warning(
            "Workspace autonomy cooldown unavailable (redis); skipping cooldown check",
            extra={"workspace_id": workspace_id, "root_task_id": root_task_id},
        )
        return False
    key = _AUTO_TRIGGER_COOLDOWN_KEY.format(workspace_id=workspace_id, root_task_id=root_task_id)
    try:
        return bool(await redis_client.exists(key))
    except Exception:
        logger.warning(
            "Workspace autonomy cooldown read failed; treating as not-on-cooldown",
            exc_info=True,
            extra={"workspace_id": workspace_id, "root_task_id": root_task_id},
        )
        return False


async def _mark_cooldown(workspace_id: str, root_task_id: str) -> None:
    try:
        redis_client = await get_redis_client()
    except Exception:
        return
    key = _AUTO_TRIGGER_COOLDOWN_KEY.format(workspace_id=workspace_id, root_task_id=root_task_id)
    try:
        await redis_client.set(key, "1", ex=AUTO_TRIGGER_COOLDOWN_SECONDS)
    except Exception:
        logger.warning(
            "Workspace autonomy cooldown write failed",
            exc_info=True,
            extra={"workspace_id": workspace_id, "root_task_id": root_task_id},
        )


def _root_task_sort_key(task: Any) -> tuple[int, str]:  # noqa: ANN401
    """Lower sort key == higher priority."""
    metadata = task.metadata or {}
    remediation_status = metadata.get("remediation_status") or "none"
    if remediation_status == "ready_for_completion":
        priority = 0
    elif remediation_status == "replan_required":
        priority = 1
    else:
        priority = 2
    return (priority, task.id)


async def _select_root_task_needing_progress(
    *,
    task_repo: Any,  # noqa: ANN401
    workspace_id: str,
    root_tasks: list[Any],
    force: bool = False,
) -> tuple[Any | None, bool]:
    """Pick the first root task that should be advanced.

    Returns ``(task, has_children)``. A root task is eligible when:
    - it has no children yet (needs initial decomposition), OR
    - its ``remediation_status`` indicates follow-up is needed, OR
    - any child is still in a pre-execution state (TODO/DISPATCHED) meaning
      worker sessions haven't been launched or haven't started yet, OR
    - ``force=True`` (always eligible — used by the UI tick button).
    """
    from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

    _PRE_EXECUTION_STATUSES = frozenset(
        {
            WorkspaceTaskStatus.TODO,
            WorkspaceTaskStatus.DISPATCHED,
        }
    )

    prioritized = sorted(root_tasks, key=_root_task_sort_key)
    for root_task in prioritized:
        metadata = root_task.metadata or {}
        remediation_status = metadata.get("remediation_status") or "none"
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task.id)
        has_children = bool(children)
        if not has_children:
            return root_task, False
        if remediation_status in _REMEDIATION_STATUSES_NEEDING_PROGRESS:
            return root_task, True
        if any(c.status in _PRE_EXECUTION_STATUSES for c in children):
            return root_task, True
        # Detect children awaiting auto-adjudication (worker completed but
        # report not yet adjudicated). This ensures the tick fires so the
        # auto-adjudication step can close them out.
        if any(
            isinstance(c.metadata, dict) and c.metadata.get("pending_leader_adjudication") is True
            for c in children
        ):
            return root_task, True
        if force:
            return root_task, True
    return None, False


_SWEEPABLE_EXECUTION_ROLES = frozenset({"execution", "execution_task"})


async def _sweep_orphan_execution_tasks(
    *,
    task_repo: Any,  # noqa: ANN401
    workspace_agent_repo: Any,  # noqa: ANN401
    command_service: Any,  # noqa: ANN401
    workspace_id: str,
    root_task_id: str,
    leader_agent_id: str | None,
    actor_user_id: str,
) -> int:
    """Dispatch any orphan execution tasks under the root that never got assigned.

    Belt-and-suspenders safety net for P5a: if any code path creates an
    execution task but forgets to route it (or the dispatch failed
    transiently), the next autonomy tick self-heals by routing them round-robin
    to active workspace agents. Returns the number of orphans dispatched.

    An orphan is an unarchived task under ``root_task_id`` with
    ``metadata.task_role`` in ``{execution, execution_task}``,
    ``assignee_agent_id IS NULL``, and status ``todo``.
    """
    from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus

    if not leader_agent_id:
        return 0

    try:
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    except Exception:
        logger.warning(
            "autonomy_tick.orphan_sweep.list_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.orphan_sweep.list_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
            },
        )
        return 0

    orphans: list[WorkspaceTask] = []
    for child in children:
        if child.assignee_agent_id:
            continue
        if getattr(child, "archived_at", None) is not None:
            continue
        if child.status != WorkspaceTaskStatus.TODO:
            continue
        metadata = child.metadata or {}
        role = metadata.get("task_role") if isinstance(metadata, dict) else None
        if role not in _SWEEPABLE_EXECUTION_ROLES:
            continue
        orphans.append(child)

    if not orphans:
        return 0

    from src.infrastructure.agent.workspace.workspace_goal_runtime import (
        _assign_execution_tasks_to_workers,
    )

    try:
        await _assign_execution_tasks_to_workers(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            created_tasks=orphans,
            workspace_agent_repo=workspace_agent_repo,
            command_service=command_service,
            leader_agent_id=leader_agent_id,
            reason="autonomy_tick.orphan_sweep",
        )
    except Exception:
        logger.warning(
            "autonomy_tick.orphan_sweep.dispatch_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.orphan_sweep.dispatch_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
                "orphan_count": len(orphans),
            },
        )
        return 0

    logger.info(
        "autonomy_tick.orphan_sweep.dispatched",
        extra={
            "event": "autonomy_tick.orphan_sweep.dispatched",
            "workspace_id": workspace_id,
            "root_task_id": root_task_id,
            "orphan_count": len(orphans),
            "orphan_ids": [t.id for t in orphans],
            "leader_agent_id": leader_agent_id,
        },
    )
    return len(orphans)


async def _heal_assigned_execution_tasks_without_sessions(
    *,
    db: AsyncSession,
    task_repo: Any,  # noqa: ANN401
    workspace_id: str,
    root_task_id: str,
    leader_agent_id: str | None,
    actor_user_id: str,
) -> int:
    """Launch a worker session for any assigned execution task missing one.

    Recovers from the class of bug that left workspace ``2c11849d-…`` stuck:
    every execution child had ``assignee_agent_id`` set yet
    ``workspace_task_session_attempts`` was empty. The sweep above filters
    to ``assignee IS NULL`` so it cannot self-heal already-assigned tasks.

    For each assigned ``execution_task`` under the root that is not DONE and
    has no active attempt, fire ``worker_launch.schedule_worker_session``.
    ``schedule_worker_session`` is idempotent (Redis cooldown +
    ``_ensure_execution_attempt`` re-uses active attempts), so repeated
    ticks are safe. Returns the number of sessions scheduled.
    """
    from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
        SqlWorkspaceTaskSessionAttemptRepository,
    )
    from src.infrastructure.agent.workspace import worker_launch as worker_launch_mod

    try:
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    except Exception:
        logger.warning(
            "autonomy_tick.worker_session_heal.list_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.worker_session_heal.list_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
            },
        )
        return 0

    attempt_repo = SqlWorkspaceTaskSessionAttemptRepository(db)
    healed = 0
    for child in children:
        worker_agent_id = getattr(child, "assignee_agent_id", None)
        if not worker_agent_id:
            continue
        if getattr(child, "archived_at", None) is not None:
            continue
        if child.status == WorkspaceTaskStatus.DONE:
            continue
        metadata = child.metadata or {}
        role = metadata.get("task_role") if isinstance(metadata, dict) else None
        if role not in _SWEEPABLE_EXECUTION_ROLES:
            continue

        try:
            active_attempt = await attempt_repo.find_active_by_workspace_task_id(child.id)
        except Exception:
            logger.warning(
                "autonomy_tick.worker_session_heal.attempt_lookup_failed",
                exc_info=True,
                extra={
                    "event": "autonomy_tick.worker_session_heal.attempt_lookup_failed",
                    "workspace_id": workspace_id,
                    "task_id": child.id,
                },
            )
            continue
        if active_attempt is not None:
            continue

        try:
            worker_launch_mod.schedule_worker_session(
                workspace_id=workspace_id,
                task=child,
                worker_agent_id=worker_agent_id,
                actor_user_id=actor_user_id,
                leader_agent_id=leader_agent_id,
            )
            healed += 1
        except Exception:
            logger.warning(
                "autonomy_tick.worker_session_heal.schedule_failed",
                exc_info=True,
                extra={
                    "event": "autonomy_tick.worker_session_heal.schedule_failed",
                    "workspace_id": workspace_id,
                    "task_id": child.id,
                    "worker_agent_id": worker_agent_id,
                },
            )

    if healed:
        logger.info(
            "autonomy_tick.worker_session_heal.dispatched",
            extra={
                "event": "autonomy_tick.worker_session_heal.dispatched",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
                "healed_count": healed,
            },
        )
    return healed


async def _auto_adjudicate_pending_reports(
    *,
    task_repo: Any,  # noqa: ANN401
    workspace_id: str,
    root_task_id: str,
    leader_agent_id: str | None,
    actor_user_id: str,
) -> int:
    """Auto-adjudicate worker reports that are pending leader adjudication.

    This is an **auto-accept policy** executed in the tick path (not the worker
    launch path).  For each execution child with
    ``pending_leader_adjudication=True``, the report type determines the
    adjudication status:

    - ``completed`` → DONE
    - ``blocked`` / ``failed`` → BLOCKED
    - anything else → skip (leave for manual review)

    Returns the number of tasks adjudicated.  Each call to
    :func:`adjudicate_workspace_worker_report` opens its own DB session and
    commits independently.  Runs sequentially so the reconciliation inside
    ``complete_task()`` sees the latest committed state.
    """
    from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
    from src.infrastructure.agent.workspace.workspace_goal_runtime import (
        adjudicate_workspace_worker_report,
    )

    try:
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    except Exception:
        logger.warning(
            "autonomy_tick.auto_adjudicate.list_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.auto_adjudicate.list_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
            },
        )
        return 0

    _REPORT_TYPE_TO_STATUS: dict[str, WorkspaceTaskStatus] = {
        "completed": WorkspaceTaskStatus.DONE,
        "blocked": WorkspaceTaskStatus.BLOCKED,
        "failed": WorkspaceTaskStatus.BLOCKED,
        "needs_replan": WorkspaceTaskStatus.BLOCKED,
    }

    adjudicated = 0
    for child in children:
        metadata = child.metadata if isinstance(child.metadata, dict) else {}
        if metadata.get("pending_leader_adjudication") is not True:
            continue
        report_type = metadata.get("last_worker_report_type")
        target_status = _REPORT_TYPE_TO_STATUS.get(report_type or "")
        if target_status is None:
            continue
        attempt_id = metadata.get("current_attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            attempt_id = None
        try:
            result = await adjudicate_workspace_worker_report(
                workspace_id=workspace_id,
                task_id=child.id,
                attempt_id=attempt_id,
                actor_user_id=actor_user_id,
                status=target_status,
                leader_agent_id=leader_agent_id,
            )
            if result is not None:
                adjudicated += 1
                logger.info(
                    "autonomy_tick.auto_adjudicate.success",
                    extra={
                        "event": "autonomy_tick.auto_adjudicate.success",
                        "workspace_id": workspace_id,
                        "task_id": child.id,
                        "report_type": report_type,
                        "target_status": target_status.value,
                    },
                )
        except Exception:
            logger.warning(
                "autonomy_tick.auto_adjudicate.failed",
                exc_info=True,
                extra={
                    "event": "autonomy_tick.auto_adjudicate.failed",
                    "workspace_id": workspace_id,
                    "task_id": child.id,
                    "report_type": report_type,
                },
            )
    if adjudicated:
        logger.info(
            "autonomy_tick.auto_adjudicate.summary",
            extra={
                "event": "autonomy_tick.auto_adjudicate.summary",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
                "adjudicated_count": adjudicated,
            },
        )
    return adjudicated


def _build_message_service(
    request: Request | None, db: AsyncSession, container: DIContainer
) -> Any:  # noqa: ANN401
    """Build a WorkspaceMessageService usable with or without a live Request."""
    if request is not None:
        return get_message_service(request, db)

    redis_client = container.redis_client

    async def _publish_event(workspace_id: str, event_name: str, payload: dict[str, Any]) -> None:
        from src.domain.events.types import AgentEventType
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event,
        )

        event_type = AgentEventType(event_name)
        await publish_workspace_event(
            redis_client,
            workspace_id=workspace_id,
            event_type=event_type,
            payload=payload,
        )

    return container.workspace_message_service(
        workspace_event_publisher=_publish_event if redis_client is not None else None,
    )


async def _try_auto_complete_root(
    *,
    request: Request | None,
    db: AsyncSession,
    container: DIContainer,
    task_service: WorkspaceTaskService,
    workspace_id: str,
    current_user: User,
    root_task: WorkspaceTask,
    title: str,
    conversation_scope: str,
    leader_binding: WorkspaceAgent,
    has_children: bool,
    force: bool,
) -> dict[str, Any] | None:
    """Close a ``ready_for_completion`` root task without human review.

    Returns the trigger-outcome dict when auto-completion succeeded (caller
    short-circuits and skips the mention flow), or ``None`` when auto-completion
    is not applicable / failed (caller falls through to the existing mention).
    Never raises — any error is logged and reported as a miss.
    """
    from src.application.services.workspace_task_command_service import (
        WorkspaceTaskCommandService,
    )
    from src.application.services.workspace_task_event_publisher import (
        WorkspaceTaskEventPublisher,
    )
    from src.infrastructure.agent.workspace.orchestrator import (
        WorkspaceAutonomyOrchestrator,
    )

    command_service = WorkspaceTaskCommandService(task_service)
    task_repo = container.workspace_task_repository()
    try:
        completed = await WorkspaceAutonomyOrchestrator().auto_complete_ready_root(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            root_task=root_task,
            task_repo=task_repo,  # pyright: ignore[reportArgumentType]
            command_service=command_service,
            leader_agent_id=leader_binding.agent_id,
        )
    except Exception:
        logger.warning(
            "autonomy_tick.auto_complete_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.auto_complete_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task.id,
            },
        )
        return None

    if completed is None or completed.status.value != "done":
        return None

    try:
        publisher = WorkspaceTaskEventPublisher(await get_redis_client())
        await publisher.publish_pending_events(command_service.consume_pending_events())
    except Exception:
        logger.warning(
            "autonomy_tick.auto_complete_publish_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.auto_complete_publish_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task.id,
            },
        )

    # Build a detailed completion report with child task summaries.
    child_report_lines: list[str] = []
    try:
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task.id)
        for idx, child in enumerate(children, 1):
            child_meta = child.metadata if isinstance(child.metadata, dict) else {}
            child_summary = child_meta.get("last_worker_report_summary") or ""
            child_status = getattr(child.status, "value", str(child.status))
            line = f"  {idx}. [{child_status.upper()}] {child.title}"
            if child_summary:
                line += f"\n     Summary: {child_summary[:200]}"
            child_report_lines.append(line)
    except Exception:
        pass
    child_report = "\n".join(child_report_lines)
    progress_summary = (root_task.metadata or {}).get("goal_progress_summary", "")

    info_content = (
        f"✅ 工作区目标「{title}」的所有子任务已完成，根任务已自动关闭并生成完成证据。\n"
        f"All child tasks completed; the root goal has been auto-closed "
        f"with synthesized evidence.\n\n"
    )
    if progress_summary:
        info_content += f"📊 Progress: {progress_summary}\n\n"
    if child_report:
        info_content += f"📋 Task Report:\n{child_report}\n"
    message_service = _build_message_service(request, db, container)
    info_message = await message_service.send_message(
        workspace_id=workspace_id,
        sender_id=current_user.id,
        sender_type=MessageSenderType.HUMAN,
        sender_name=current_user.email,
        content=info_content,
    )
    info_message.metadata["conversation_scope"] = conversation_scope
    info_message.metadata["autonomy_trigger"] = {
        "root_task_id": root_task.id,
        "remediation_status": "ready_for_completion",
        "has_children": has_children,
        "force": force,
        "auto_completed": True,
    }
    info_row = await db.get(WorkspaceMessageModel, info_message.id)
    if info_row is not None:
        info_row.metadata_json = dict(info_message.metadata)
        info_row.mentions_json = list(info_message.mentions)
        await db.flush()
    await db.commit()
    await _mark_cooldown(workspace_id, root_task.id)
    logger.info(
        "autonomy_tick.auto_completed",
        extra={
            "event": "autonomy_tick.auto_completed",
            "workspace_id": workspace_id,
            "root_task_id": root_task.id,
            "actor_user_id": current_user.id,
        },
    )
    return {
        "triggered": True,
        "root_task_id": root_task.id,
        "reason": "auto_completed",
        "auto_completed": True,
    }


def _build_autonomy_mention_content(mention: str, title: str, remediation_status: str) -> str:
    if remediation_status == "ready_for_completion":
        return (
            f"{mention} 工作区目标「{title}」的所有子任务已完成。"
            "请复核并关闭根任务，生成完成证据。 "
            "Please verify the child tasks, produce goal evidence, and mark the root goal complete."
        )
    if remediation_status == "replan_required":
        return (
            f"{mention} 工作区目标「{title}」有子任务阻塞或失败，需要重新规划。"
            "请根据最新状态调整执行计划或替换失败的子任务。 "
            "Please replan or remediate the blocked/failed child tasks and continue execution."
        )
    return (
        f"{mention} 中央黑板已有目标：{title}。"
        "你的职责是作为 leader：(1) 使用 todowrite 将目标拆解为子任务；"
        "(2) 子任务会自动分配给工作空间中的 worker agent，由独立会话执行，你不要亲自执行这些子任务；"
        "(3) 拆解并分派完成后即可停止本轮工作。后续的 worker 报告会由系统汇总并触发你进一步调度。 "
        "You are the leader. (1) Call todowrite to decompose this objective into child tasks. "
        "(2) Child tasks are dispatched to workspace worker agents that run in their own sessions; "
        "do NOT execute the child tasks yourself. "
        "(3) After decomposition and dispatch, stop this turn. "
        "Worker reports will be aggregated and you will be invoked again for further orchestration."
    )


async def maybe_auto_trigger_existing_root_execution(  # noqa: C901, PLR0912, PLR0915
    *,
    request: Request | None = None,
    db: AsyncSession,
    workspace_id: str,
    current_user: User,
    force: bool = False,
) -> dict[str, Any]:
    """Post a leader mention to advance an existing workspace root goal.

    Returns a dict describing the outcome::

        {
            "triggered": bool,
            "root_task_id": str | None,
            "reason": "triggered" | "cooling_down" | "no_open_root"
                      | "no_root_needs_progress" | "workspace_not_found",
        }

    When ``force=True`` the per-root cooldown is bypassed. The cooldown TTL
    is :data:`AUTO_TRIGGER_COOLDOWN_SECONDS` seconds, keyed on
    ``workspace:autonomy:last_trigger:{workspace_id}:{root_task_id}`` in Redis.

    ``request`` may be ``None`` when invoked from a background task; in that
    case the module-level app container is used instead.
    """
    container = _resolve_container(request, db)
    workspace = await container.workspace_repository().find_by_id(workspace_id)
    if workspace is None:
        return {"triggered": False, "root_task_id": None, "reason": "workspace_not_found"}

    leader_binding, _ = await ensure_workspace_leader_binding(
        request=request,
        db=db,
        workspace_id=workspace_id,
    )
    task_service = WorkspaceTaskService(
        workspace_repo=container.workspace_repository(),
        workspace_member_repo=container.workspace_member_repository(),
        workspace_agent_repo=container.workspace_agent_repository(),
        workspace_task_repo=container.workspace_task_repository(),
    )
    tasks = await task_service.list_tasks(
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        limit=100,
        offset=0,
    )
    root_tasks = [
        task
        for task in tasks
        if is_goal_root_task(task)
        and task.archived_at is None
        and getattr(task.status, "value", task.status) != "done"
    ]
    if not root_tasks:
        return {"triggered": False, "root_task_id": None, "reason": "no_open_root"}

    task_repo = container.workspace_task_repository()
    root_task, has_children = await _select_root_task_needing_progress(
        task_repo=task_repo,
        workspace_id=workspace_id,
        root_tasks=root_tasks,
        force=force,
    )
    if root_task is None:
        return {"triggered": False, "root_task_id": None, "reason": "no_root_needs_progress"}

    # P5b safety net: dispatch any orphan execution_task children before we
    # proceed. This self-heals cases where an earlier path created execution
    # tasks but missed the dispatch slot (transient failure, future path that
    # forgets _dispatch_created_workspace_tasks, etc). Best-effort; failures
    # are logged and never break the tick.
    sweep_command_service: Any = None
    try:
        from src.application.services.workspace_task_command_service import (
            WorkspaceTaskCommandService,
        )

        sweep_command_service = WorkspaceTaskCommandService(task_service)
        await _sweep_orphan_execution_tasks(
            task_repo=task_repo,
            workspace_agent_repo=container.workspace_agent_repository(),
            command_service=sweep_command_service,
            workspace_id=workspace_id,
            root_task_id=root_task.id,
            leader_agent_id=leader_binding.agent_id,
            actor_user_id=current_user.id,
        )
    except Exception:
        logger.warning(
            "autonomy_tick.orphan_sweep.unexpected_failure",
            exc_info=True,
            extra={
                "event": "autonomy_tick.orphan_sweep.unexpected_failure",
                "workspace_id": workspace_id,
                "root_task_id": root_task.id,
            },
        )
        sweep_command_service = None

    # Self-heal pass: even if the orphan sweep did nothing, there may be tasks
    # that are assigned but never got a worker session launched (the bug that
    # stranded workspace 2c11849d-…). Directly launch worker sessions for
    # those — ``schedule_worker_session`` is idempotent via cooldown and
    # ``_ensure_execution_attempt`` re-uses active attempts.
    try:
        await _heal_assigned_execution_tasks_without_sessions(
            db=db,
            task_repo=task_repo,
            workspace_id=workspace_id,
            root_task_id=root_task.id,
            leader_agent_id=leader_binding.agent_id,
            actor_user_id=current_user.id,
        )
    except Exception:
        logger.warning(
            "autonomy_tick.worker_session_heal.unexpected_failure",
            exc_info=True,
            extra={
                "event": "autonomy_tick.worker_session_heal.unexpected_failure",
                "workspace_id": workspace_id,
                "root_task_id": root_task.id,
            },
        )

    # Auto-adjudicate pending worker reports. This closes the loop for
    # workers that completed but whose reports were never adjudicated.
    # Runs in the tick path (not worker_launch) to keep authority separation.
    try:
        adjudicated_count = await _auto_adjudicate_pending_reports(
            task_repo=task_repo,
            workspace_id=workspace_id,
            root_task_id=root_task.id,
            leader_agent_id=leader_binding.agent_id,
            actor_user_id=current_user.id,
        )
        if adjudicated_count > 0:
            # Refresh root task to pick up reconciled metadata (e.g.
            # remediation_status may now be "ready_for_completion").
            refreshed = await task_repo.find_by_id(root_task.id)
            if refreshed is not None:
                root_task = refreshed
    except Exception:
        logger.warning(
            "autonomy_tick.auto_adjudicate.unexpected_failure",
            exc_info=True,
            extra={
                "event": "autonomy_tick.auto_adjudicate.unexpected_failure",
                "workspace_id": workspace_id,
                "root_task_id": root_task.id,
            },
        )

    if not force and await _is_on_cooldown(workspace_id, root_task.id):
        return {"triggered": False, "root_task_id": root_task.id, "reason": "cooling_down"}

    objective_id = root_task.metadata.get("objective_id") if root_task.metadata else None
    conversation_scope = (
        f"objective:{objective_id}"
        if isinstance(objective_id, str) and objective_id
        else f"root:{root_task.id}"
    )

    title = root_task.title
    description = root_task.description or ""
    if isinstance(objective_id, str) and objective_id:
        objective = await container.cyber_objective_repository().find_by_id(objective_id)
        if objective is not None:
            title = objective.title
            description = objective.description or description

    try:
        from src.infrastructure.agent.workspace.goal_runtime import (
            kickoff_v2_plan_if_enabled,
        )

        await kickoff_v2_plan_if_enabled(
            workspace_id=workspace_id,
            title=title,
            description=description,
            created_by=current_user.id,
            root_task_id=root_task.id,
            leader_agent_id=leader_binding.agent_id,
        )
    except Exception:
        logger.warning(
            "workspace_v2.kickoff_failed",
            exc_info=True,
            extra={"workspace_id": workspace_id, "root_task_id": root_task.id},
        )

    mention = _format_agent_mention(leader_binding.display_name, leader_binding.agent_id)
    remediation_status = (
        (root_task.metadata or {}).get("remediation_status") or "none" if has_children else "none"
    )

    if remediation_status == "ready_for_completion" and has_children and _auto_complete_enabled():
        auto_outcome = await _try_auto_complete_root(
            request=request,
            db=db,
            container=container,
            task_service=task_service,
            workspace_id=workspace_id,
            current_user=current_user,
            root_task=root_task,
            title=title,
            conversation_scope=conversation_scope,
            leader_binding=leader_binding,
            has_children=has_children,
            force=force,
        )
        if auto_outcome is not None:
            return auto_outcome

    content = _build_autonomy_mention_content(mention, title, remediation_status)
    message_service = _build_message_service(request, db, container)
    message = await message_service.send_message(
        workspace_id=workspace_id,
        sender_id=current_user.id,
        sender_type=MessageSenderType.HUMAN,
        sender_name=current_user.email,
        content=content,
    )
    message.metadata["conversation_scope"] = conversation_scope
    message.metadata["autonomy_trigger"] = {
        "root_task_id": root_task.id,
        "remediation_status": remediation_status,
        "has_children": has_children,
        "force": force,
    }
    if leader_binding.agent_id not in message.mentions:
        message.mentions = [*message.mentions, leader_binding.agent_id]
    message_row = await db.get(WorkspaceMessageModel, message.id)
    if message_row is not None:
        message_row.metadata_json = dict(message.metadata)
        message_row.mentions_json = list(message.mentions)
        await db.flush()
    await db.commit()
    # Drain worker launches queued by the orphan sweep now that the assignee
    # changes are durably committed. Missing this drain is what left
    # workspace 2c11849d-… in ``todo + assigned, zero sessions``.
    if sweep_command_service is not None:
        try:
            from src.infrastructure.agent.workspace.worker_launch_drain import (
                drain_pending_worker_launches,
            )

            drain_pending_worker_launches(sweep_command_service)
        except Exception:
            logger.warning(
                "autonomy_tick.orphan_sweep.drain_failed",
                exc_info=True,
                extra={
                    "event": "autonomy_tick.orphan_sweep.drain_failed",
                    "workspace_id": workspace_id,
                    "root_task_id": root_task.id,
                },
            )
    await _mark_cooldown(workspace_id, root_task.id)
    _fire_mention_routing(
        request=request,
        workspace_id=workspace_id,
        message=message,
        tenant_id=workspace.tenant_id,
        project_id=workspace.project_id,
        user_id=current_user.id,
    )
    return {"triggered": True, "root_task_id": root_task.id, "reason": "triggered"}


async def _run_autonomy_tick(workspace_id: str, actor_user_id: str) -> None:
    """Headless autonomy tick: resolve user, open own DB session, fire the trigger."""
    try:
        async with async_session_factory() as db:
            user_row = await db.get(User, actor_user_id)
            if user_row is None:
                logger.warning(
                    "autonomy_tick.skipped_user_missing",
                    extra={
                        "event": "autonomy_tick.skipped_user_missing",
                        "workspace_id": workspace_id,
                        "actor_user_id": actor_user_id,
                    },
                )
                return
            result = await maybe_auto_trigger_existing_root_execution(
                request=None,
                db=db,
                workspace_id=workspace_id,
                current_user=user_row,
                force=False,
            )
            logger.info(
                "autonomy_tick.done",
                extra={
                    "event": "autonomy_tick.done",
                    "workspace_id": workspace_id,
                    "actor_user_id": actor_user_id,
                    "triggered": bool(result.get("triggered")),
                    "reason": result.get("reason"),
                    "root_task_id": result.get("root_task_id"),
                },
            )
    except Exception:
        logger.warning(
            "autonomy_tick.failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.failed",
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
            },
        )


def schedule_autonomy_tick(workspace_id: str, actor_user_id: str) -> None:
    """Fire-and-forget auto-tick after a worker terminal report.

    Controlled by the ``WORKSPACE_AUTONOMY_AUTO_TICK_ENABLED`` env flag
    (default enabled). A per-workspace in-flight guard prevents tick
    storms when multiple workers report back-to-back. Task handle is held
    in :data:`_background_tasks` so it does not get garbage-collected
    before completion. Never raises.
    """
    if not _auto_tick_enabled():
        logger.debug(
            "autonomy_tick.skipped_flag_off",
            extra={
                "event": "autonomy_tick.skipped_flag_off",
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
            },
        )
        return
    existing = _inflight_ticks.get(workspace_id)
    if existing is not None and not existing.done():
        logger.debug(
            "autonomy_tick.skipped_dedup",
            extra={
                "event": "autonomy_tick.skipped_dedup",
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
            },
        )
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            "autonomy_tick.skipped_no_loop",
            extra={
                "event": "autonomy_tick.skipped_no_loop",
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
            },
        )
        return
    task = loop.create_task(_run_autonomy_tick(workspace_id, actor_user_id))
    _background_tasks.add(task)
    _inflight_ticks[workspace_id] = task

    def _on_done(finished: asyncio.Task[Any]) -> None:
        _background_tasks.discard(finished)
        # Only clear the inflight slot if it's still pointing at this task.
        if _inflight_ticks.get(workspace_id) is finished:
            _inflight_ticks.pop(workspace_id, None)

    task.add_done_callback(_on_done)
    logger.info(
        "autonomy_tick.scheduled",
        extra={
            "event": "autonomy_tick.scheduled",
            "workspace_id": workspace_id,
            "actor_user_id": actor_user_id,
        },
    )
