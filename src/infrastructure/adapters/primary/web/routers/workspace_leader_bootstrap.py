from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_agent_autonomy import is_goal_root_task
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.configuration.di_container import DIContainer
from src.domain.model.workspace.workspace_task import WorkspaceTask
from src.infrastructure.adapters.primary.web.routers.agent.utils import get_container_with_db
from src.infrastructure.adapters.primary.web.startup.container import get_app_container
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.agent.state.agent_worker_state import get_redis_client
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.system_actor import WORKSPACE_PLAN_SYSTEM_ACTOR_ID

logger = logging.getLogger(__name__)

AUTO_TRIGGER_COOLDOWN_SECONDS = 60
REPLAN_TRIGGER_COOLDOWN_SECONDS = 300
_AUTO_TRIGGER_COOLDOWN_KEY = "workspace:autonomy:last_trigger:{workspace_id}:{root_task_id}"
_REMEDIATION_STATUSES_NEEDING_PROGRESS = frozenset({"replan_required", "ready_for_completion"})
_NON_OPEN_ROOT_STATUSES = frozenset({"done", "blocked"})
_WORKER_SESSION_HEAL_MAX_PER_TICK_ENV = "WORKSPACE_AUTONOMY_MAX_WORKER_SESSION_HEAL_PER_TICK"
_DEFAULT_WORKER_SESSION_HEAL_MAX_PER_TICK = 2

_AUTO_TICK_ENV = "WORKSPACE_AUTONOMY_AUTO_TICK_ENABLED"
_AUTO_COMPLETE_ENV = "WORKSPACE_AUTONOMY_AUTO_COMPLETE_ENABLED"
_background_tasks: set[asyncio.Task[Any]] = set()
# Per-workspace dedup so a storm of worker terminal reports against the same
# workspace does not queue a pile of ticks. At most one tick can be in-flight
# per workspace; subsequent schedules are dropped until it finishes. The 60s
# Redis cooldown remains the secondary guard against repeat triggers once the
# tick itself completes.
_inflight_ticks: dict[str, asyncio.Task[Any]] = {}


class _WorkspaceTaskChildrenRepository(Protocol):
    async def find_by_root_goal_task_id(
        self,
        workspace_id: str,
        root_goal_task_id: str,
    ) -> Sequence[WorkspaceTask]: ...


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


def _worker_session_heal_max_per_tick() -> int:
    raw = os.environ.get(_WORKER_SESSION_HEAL_MAX_PER_TICK_ENV)
    if raw is None:
        return _DEFAULT_WORKER_SESSION_HEAL_MAX_PER_TICK
    try:
        parsed = int(raw.strip())
    except ValueError:
        return _DEFAULT_WORKER_SESSION_HEAL_MAX_PER_TICK
    return parsed if parsed > 0 else _DEFAULT_WORKER_SESSION_HEAL_MAX_PER_TICK


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


async def _mark_autonomy_trigger_cooldown(
    workspace_id: str,
    root_task_id: str,
    *,
    remediation_status: str,
) -> None:
    seconds = (
        REPLAN_TRIGGER_COOLDOWN_SECONDS
        if remediation_status == "replan_required"
        else AUTO_TRIGGER_COOLDOWN_SECONDS
    )
    try:
        redis_client = await get_redis_client()
    except Exception:
        return
    key = _AUTO_TRIGGER_COOLDOWN_KEY.format(workspace_id=workspace_id, root_task_id=root_task_id)
    try:
        await redis_client.set(key, "1", ex=seconds)
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
        if force:
            return root_task, True
    return None, False


_EXECUTION_TASK_ROLES = frozenset({"execution_task"})


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

    Recovers from the class of bug where a V2-projected execution child has
    ``assignee_agent_id`` set but no active ``workspace_task_session_attempt``.

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
    max_heals = _worker_session_heal_max_per_tick()
    healed = 0
    for child in children:
        if healed >= max_heals:
            break
        worker_agent_id = getattr(child, "assignee_agent_id", None)
        if not worker_agent_id:
            continue
        if getattr(child, "archived_at", None) is not None:
            continue
        status_value = getattr(child.status, "value", child.status)
        if status_value in {WorkspaceTaskStatus.DONE.value, WorkspaceTaskStatus.BLOCKED.value}:
            continue
        metadata = child.metadata or {}
        role = metadata.get("task_role") if isinstance(metadata, dict) else None
        if role not in _EXECUTION_TASK_ROLES:
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
                "max_heals": max_heals,
            },
        )
    return healed


async def _reconcile_durable_plan_after_root_auto_complete(
    *,
    db: AsyncSession,
    workspace_id: str,
    root_task_id: str,
    actor_user_id: str,
) -> bool:
    """Mark the durable V2 plan completed after root closeout.

    Workspace autonomy remains the authority that launches workers and closes
    the root task. Durable V2 is an observable/recoverable projection, so when
    the authoritative root is auto-completed we reconcile the projection instead
    of letting the plan stay visually active forever.
    """
    from src.domain.model.workspace_plan import PlanStatus
    from src.domain.model.workspace_plan.plan_node import (
        Progress,
        TaskExecution,
        TaskIntent,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
        SqlPlanRepository,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_events import (
        SqlWorkspacePlanEventRepository,
    )

    plan_repo = SqlPlanRepository(db)
    plan = await plan_repo.get_by_workspace(workspace_id)
    if plan is None or plan.status is PlanStatus.COMPLETED:
        return False

    now = datetime.now(UTC)
    reconciled_node_count = 0
    for node in list(plan.nodes.values()):
        already_closed = (
            node.intent is TaskIntent.DONE
            and node.execution is TaskExecution.IDLE
            and node.progress.percent >= 100.0
        )
        if already_closed:
            continue

        metadata = dict(node.metadata)
        metadata["completed_by_root_auto_complete"] = root_task_id
        plan.replace_node(
            replace(
                node,
                intent=TaskIntent.DONE,
                execution=TaskExecution.IDLE,
                progress=Progress(
                    percent=100.0,
                    confidence=1.0,
                    note="Closed after workspace root auto-completed.",
                ),
                metadata=metadata,
                updated_at=now,
                completed_at=node.completed_at or now,
            )
        )
        reconciled_node_count += 1

    plan.status = PlanStatus.COMPLETED
    plan.updated_at = now
    await plan_repo.save(plan)
    await SqlWorkspacePlanEventRepository(db).append(
        plan_id=plan.id,
        workspace_id=workspace_id,
        actor_id=actor_user_id,
        event_type="root_auto_completed_plan_reconciled",
        source="workspace_autonomy",
        payload={
            "root_task_id": root_task_id,
            "reconciled_node_count": reconciled_node_count,
        },
    )
    return True


async def _safe_reconcile_durable_plan_after_root_auto_complete(
    *,
    db: AsyncSession,
    workspace_id: str,
    root_task_id: str,
    actor_user_id: str,
) -> None:
    try:
        reconciled = await _reconcile_durable_plan_after_root_auto_complete(
            db=db,
            workspace_id=workspace_id,
            root_task_id=root_task_id,
            actor_user_id=actor_user_id,
        )
        if reconciled:
            logger.info(
                "autonomy_tick.plan_reconciled_after_root_auto_complete",
                extra={
                    "event": "autonomy_tick.plan_reconciled_after_root_auto_complete",
                    "workspace_id": workspace_id,
                    "root_task_id": root_task_id,
                },
            )
    except Exception:
        logger.warning(
            "autonomy_tick.plan_reconcile_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.plan_reconcile_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
            },
        )


def _is_workspace_plan_linked_task(task: WorkspaceTask) -> bool:
    metadata = getattr(task, "metadata", None)
    if not isinstance(metadata, Mapping):
        return False
    plan_id = metadata.get(WORKSPACE_PLAN_ID)
    node_id = metadata.get(WORKSPACE_PLAN_NODE_ID)
    return isinstance(plan_id, str) and bool(plan_id) and isinstance(node_id, str) and bool(node_id)


async def _root_has_workspace_plan_linked_children(
    *,
    task_repo: _WorkspaceTaskChildrenRepository,
    workspace_id: str,
    root_task_id: str,
) -> bool:
    try:
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    except Exception:
        logger.warning(
            "autonomy_tick.plan_linked_children_lookup_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.plan_linked_children_lookup_failed",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
            },
        )
        return False
    return any(_is_workspace_plan_linked_task(child) for child in children)


async def _durable_plan_allows_root_auto_complete(
    *,
    db: AsyncSession,
    workspace_id: str,
) -> bool:
    """Return True when the durable plan cannot still dispatch useful work."""
    from src.domain.model.workspace_plan import PlanStatus
    from src.domain.model.workspace_plan.plan_node import (
        PlanNodeKind,
        TaskExecution,
        TaskIntent,
    )
    from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
        SqlPlanRepository,
    )

    try:
        plan = await SqlPlanRepository(db).get_by_workspace(workspace_id)
    except Exception:
        logger.warning(
            "autonomy_tick.plan_auto_complete_gate_failed",
            exc_info=True,
            extra={
                "event": "autonomy_tick.plan_auto_complete_gate_failed",
                "workspace_id": workspace_id,
            },
        )
        return False
    allowed = plan is None or plan.status is PlanStatus.COMPLETED
    if not allowed and plan.status is PlanStatus.ACTIVE:
        nodes = list(plan.nodes.values()) if isinstance(plan.nodes, Mapping) else []
        actionable_nodes = [
            node for node in nodes if node.kind in {PlanNodeKind.TASK, PlanNodeKind.VERIFY}
        ]
        active_execution = {
            TaskExecution.DISPATCHED,
            TaskExecution.RUNNING,
            TaskExecution.REPORTED,
            TaskExecution.VERIFYING,
        }
        allowed = bool(actionable_nodes) and not any(
            node.execution in active_execution for node in actionable_nodes
        )
        allowed = allowed and all(
            node.intent in {TaskIntent.DONE, TaskIntent.BLOCKED} for node in actionable_nodes
        )
    return allowed


async def _try_auto_complete_root(
    *,
    db: AsyncSession,
    container: DIContainer,
    task_service: WorkspaceTaskService,
    workspace_id: str,
    current_user: User,
    root_task: WorkspaceTask,
    leader_agent_id: str | None,
) -> dict[str, Any] | None:
    """Close a ``ready_for_completion`` root task without human review.

    Returns the trigger-outcome dict when auto-completion succeeded, or ``None``
    when auto-completion is not applicable / failed.
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

    if not await _durable_plan_allows_root_auto_complete(db=db, workspace_id=workspace_id):
        return None

    command_service = WorkspaceTaskCommandService(task_service)
    task_repo = container.workspace_task_repository()
    try:
        completed = await WorkspaceAutonomyOrchestrator().auto_complete_ready_root(
            workspace_id=workspace_id,
            actor_user_id=current_user.id,
            root_task=root_task,
            task_repo=task_repo,  # pyright: ignore[reportArgumentType]
            command_service=command_service,
            leader_agent_id=leader_agent_id,
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

    await _safe_reconcile_durable_plan_after_root_auto_complete(
        db=db,
        workspace_id=workspace_id,
        root_task_id=root_task.id,
        actor_user_id=current_user.id,
    )

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


async def maybe_auto_trigger_existing_root_execution(  # noqa: C901, PLR0911, PLR0912
    *,
    request: Request | None = None,
    db: AsyncSession,
    workspace_id: str,
    current_user: User,
    force: bool = False,
) -> dict[str, Any]:
    """Advance an existing workspace root goal through the durable V2 plan.

    Returns a dict describing the outcome::

        {
            "triggered": bool,
            "root_task_id": str | None,
            "reason": "durable_plan_started" | "durable_plan_active" | "cooling_down"
                      | "no_open_root" | "no_root_needs_progress" | "workspace_not_found",
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

    leader_agent_id = WORKSPACE_PLAN_SYSTEM_ACTOR_ID
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
        and getattr(task.status, "value", task.status) not in _NON_OPEN_ROOT_STATUSES
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

    # V2 owns decomposition, assignment, verification, and closeout. The tick no
    # longer self-dispatches orphan V1 execution tasks or auto-adjudicates legacy
    # worker reports; it only heals already-assigned V2 children missing a launch.
    try:
        await _heal_assigned_execution_tasks_without_sessions(
            db=db,
            task_repo=task_repo,
            workspace_id=workspace_id,
            root_task_id=root_task.id,
            leader_agent_id=leader_agent_id,
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

    if not force and await _is_on_cooldown(workspace_id, root_task.id):
        return {"triggered": False, "root_task_id": root_task.id, "reason": "cooling_down"}

    objective_id = root_task.metadata.get("objective_id") if root_task.metadata else None
    title = root_task.title
    description = root_task.description or ""
    if isinstance(objective_id, str) and objective_id:
        objective = await container.cyber_objective_repository().find_by_id(objective_id)
        if objective is not None:
            title = objective.title
            description = objective.description or description

    remediation_status = (
        (root_task.metadata or {}).get("remediation_status") or "none" if has_children else "none"
    )

    if has_children and _auto_complete_enabled():
        auto_outcome = await _try_auto_complete_root(
            db=db,
            container=container,
            task_service=task_service,
            workspace_id=workspace_id,
            current_user=current_user,
            root_task=root_task,
            leader_agent_id=leader_agent_id,
        )
        if auto_outcome is not None:
            return auto_outcome

    if remediation_status == "ready_for_completion":
        await _mark_cooldown(workspace_id, root_task.id)
        return {
            "triggered": False,
            "root_task_id": root_task.id,
            "reason": "root_auto_complete_pending",
        }

    durable_plan_started = False
    try:
        from src.infrastructure.agent.workspace.goal_runtime import (
            kickoff_v2_plan,
        )

        durable_plan_started = await kickoff_v2_plan(
            workspace_id=workspace_id,
            title=title,
            description=description,
            created_by=current_user.id,
            root_task_id=root_task.id,
            leader_agent_id=leader_agent_id,
        )
    except Exception:
        logger.warning(
            "workspace_v2.kickoff_failed",
            exc_info=True,
            extra={"workspace_id": workspace_id, "root_task_id": root_task.id},
        )
    if durable_plan_started:
        await _mark_cooldown(workspace_id, root_task.id)
        return {
            "triggered": False,
            "root_task_id": root_task.id,
            "reason": "durable_plan_started",
        }

    if await _root_has_workspace_plan_linked_children(
        task_repo=task_repo,
        workspace_id=workspace_id,
        root_task_id=root_task.id,
    ):
        await _mark_cooldown(workspace_id, root_task.id)
        return {
            "triggered": False,
            "root_task_id": root_task.id,
            "reason": "durable_plan_active",
        }

    await _mark_autonomy_trigger_cooldown(
        workspace_id,
        root_task.id,
        remediation_status=remediation_status,
    )
    return {"triggered": False, "root_task_id": root_task.id, "reason": "durable_plan_unavailable"}


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
