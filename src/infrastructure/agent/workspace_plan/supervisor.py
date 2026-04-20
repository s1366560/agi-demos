"""M4 — :class:`WorkspaceSupervisorPort` implementation.

Design:

* one asyncio task per ``workspace_id``, single-writer on the plan
* tick loop: ``(progress_ready_nodes → allocate → dispatch → verify → project)``
* event-driven: a :class:`WorkspaceSupervisor.kick` call triggers an immediate
  out-of-band tick on top of the ``heartbeat_seconds`` timer
* idempotent: every step is safe to re-run; callers can always call :meth:`tick`

Ray-actor wrapper is provided by :class:`RaySupervisor` — a thin shell that
delegates to :class:`WorkspaceSupervisor` so the core logic stays testable
without a Ray cluster.

The supervisor deliberately avoids touching the legacy
``workspace_goal_runtime`` paths; wiring happens in
:mod:`orchestrator`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from src.domain.model.workspace_plan import (
    GoalProgress,
    PlanNode,
    PlanStatus,
    TaskExecution,
    TaskIntent,
    transition_execution,
    transition_intent,
)
from src.domain.ports.services.goal_planner_port import (
    GoalPlannerPort,
    ReplanTrigger,
)
from src.domain.ports.services.plan_repository_port import PlanRepositoryPort
from src.domain.ports.services.progress_projector_port import ProgressProjectorPort
from src.domain.ports.services.task_allocator_port import (
    Allocation,
    TaskAllocatorPort,
    WorkspaceAgent,
)
from src.domain.ports.services.verifier_port import (
    VerificationContext,
    VerifierPort,
)
from src.domain.ports.services.workspace_supervisor_port import (
    TickReport,
    WorkspaceSupervisorPort,
)

logger = logging.getLogger(__name__)


# Callbacks keep the supervisor pure — infrastructure injects concrete impls.
AgentPoolProvider = Callable[[str], Awaitable[list[WorkspaceAgent]]]
Dispatcher = Callable[[str, Allocation, PlanNode], Awaitable[str | None]]
"""Dispatcher: launches a worker for ``(workspace_id, allocation, node)``.
Returns an ``attempt_id`` or ``None`` on failure."""

AttemptContextProvider = Callable[[str, PlanNode], Awaitable[VerificationContext]]
"""Supplies a :class:`VerificationContext` for a reported node (sandbox,
artifacts, stdout)."""

ProgressSink = Callable[[GoalProgress], Awaitable[None]]
"""Called on every tick with the fresh :class:`GoalProgress` snapshot."""


class WorkspaceSupervisor(WorkspaceSupervisorPort):
    """Async single-writer supervisor. One instance per process is fine — it
    keeps per-workspace state in ``self._tasks`` indexed by ``workspace_id``.
    """

    def __init__(
        self,
        *,
        plan_repo: PlanRepositoryPort,
        allocator: TaskAllocatorPort,
        verifier: VerifierPort,
        projector: ProgressProjectorPort,
        planner: GoalPlannerPort,
        agent_pool: AgentPoolProvider,
        dispatcher: Dispatcher,
        attempt_context: AttemptContextProvider,
        progress_sink: ProgressSink | None = None,
        heartbeat_seconds: float = 10.0,
    ) -> None:
        self._repo = plan_repo
        self._allocator = allocator
        self._verifier = verifier
        self._projector = projector
        self._planner = planner
        self._agent_pool = agent_pool
        self._dispatcher = dispatcher
        self._attempt_context = attempt_context
        self._progress_sink = progress_sink
        self._heartbeat = heartbeat_seconds

        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._kick: dict[str, asyncio.Event] = {}
        self._stop_flags: dict[str, asyncio.Event] = {}

    # --- lifecycle ------------------------------------------------------

    async def start(self, workspace_id: str) -> None:
        if workspace_id in self._tasks and not self._tasks[workspace_id].done():
            return
        stop = asyncio.Event()
        kick = asyncio.Event()
        self._stop_flags[workspace_id] = stop
        self._kick[workspace_id] = kick
        self._tasks[workspace_id] = asyncio.create_task(
            self._run(workspace_id, stop, kick),
            name=f"workspace-supervisor:{workspace_id}",
        )
        logger.info("supervisor started for workspace %s", workspace_id)

    async def stop(self, workspace_id: str) -> None:
        stop = self._stop_flags.get(workspace_id)
        task = self._tasks.get(workspace_id)
        if stop is not None:
            stop.set()
        kick = self._kick.get(workspace_id)
        if kick is not None:
            kick.set()
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()
        self._tasks.pop(workspace_id, None)
        self._stop_flags.pop(workspace_id, None)
        self._kick.pop(workspace_id, None)
        logger.info("supervisor stopped for workspace %s", workspace_id)

    async def is_running(self, workspace_id: str) -> bool:
        task = self._tasks.get(workspace_id)
        return task is not None and not task.done()

    def kick(self, workspace_id: str) -> None:
        """Event-driven wake: ask the supervisor to tick now, out of band."""
        kick = self._kick.get(workspace_id)
        if kick is not None:
            kick.set()

    # --- core loop -----------------------------------------------------

    async def _run(self, workspace_id: str, stop: asyncio.Event, kick: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                report = await self.tick(workspace_id)
                if report.errors:
                    logger.warning(
                        "workspace %s tick errors: %s",
                        workspace_id,
                        report.errors,
                    )
            except Exception as exc:
                logger.exception("supervisor tick failed: %s", exc)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(kick.wait(), timeout=self._heartbeat)
            kick.clear()

    async def tick(self, workspace_id: str) -> TickReport:  # noqa: C901, PLR0912, PLR0915
        plan = await self._repo.get_by_workspace(workspace_id)
        if plan is None or plan.status not in (PlanStatus.ACTIVE, PlanStatus.DRAFT):
            return TickReport(workspace_id=workspace_id)

        errors: list[str] = []
        allocs_made = 0
        verifies_ran = 0
        nodes_done = 0
        nodes_blocked = 0

        # --- 1. verify any REPORTED nodes ------------------------------
        reported = [n for n in plan.nodes.values() if n.execution is TaskExecution.REPORTED]
        for node in reported:
            try:
                plan.replace_node(_force_execution(node, TaskExecution.VERIFYING))
                ctx = await self._attempt_context(workspace_id, node)
                report = await self._verifier.verify(ctx)
                verifies_ran += 1
                if report.passed:
                    plan.replace_node(
                        _force_intent(
                            _force_execution(node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                        )
                    )
                    nodes_done += 1
                elif report.hard_fail:
                    plan.replace_node(
                        _force_intent(
                            _force_execution(node, TaskExecution.IDLE),
                            TaskIntent.BLOCKED,
                            summary=report.summary(),
                        )
                    )
                    nodes_blocked += 1
                else:
                    # Soft fail → ask the planner to replan this node.
                    await self._planner.replan(
                        plan,
                        ReplanTrigger(
                            kind="verification_failed",
                            node_id=node.id,
                            detail=report.summary(),
                        ),
                    )
            except Exception as exc:
                errors.append(f"verify({node.id}): {exc}")

        # --- 2. allocate ready nodes -----------------------------------
        ready = plan.ready_nodes()
        if ready:
            try:
                pool = await self._agent_pool(workspace_id)
                allocations = await self._allocator.allocate(ready, pool)
            except Exception as exc:
                errors.append(f"allocate: {exc}")
                allocations = []
            for alloc in allocations:
                node = plan.nodes.get(_pid(alloc.node_id))
                if node is None:
                    continue
                try:
                    attempt_id = await self._dispatcher(workspace_id, alloc, node)
                except Exception as exc:
                    errors.append(f"dispatch({node.id}): {exc}")
                    continue
                if not attempt_id:
                    continue
                updated = replace(
                    node,
                    intent=TaskIntent.IN_PROGRESS,
                    execution=TaskExecution.DISPATCHED,
                    assignee_agent_id=alloc.agent_id,
                    current_attempt_id=attempt_id,
                )
                try:
                    transition_intent(node.intent, TaskIntent.IN_PROGRESS)
                    transition_execution(node.execution, TaskExecution.DISPATCHED)
                except Exception:
                    # If the node already moved (e.g. concurrent worker_report),
                    # skip. Single-writer means this is rare but possible when
                    # callbacks arrive between load and replace.
                    continue
                plan.replace_node(updated)
                allocs_made += 1

        # --- 3. persist plan + project progress ------------------------
        await self._repo.save(plan)
        progress = self._projector.project(plan)
        if progress.is_complete:
            plan_final = plan
            # Mark plan completed if every executable leaf is DONE.
            from dataclasses import replace as _r

            plan_final = _r(plan, status=PlanStatus.COMPLETED)
            await self._repo.save(plan_final)
        if self._progress_sink is not None:
            try:
                await self._progress_sink(progress)
            except Exception as exc:
                errors.append(f"progress_sink: {exc}")

        return TickReport(
            workspace_id=workspace_id,
            allocations_made=allocs_made,
            verifications_ran=verifies_ran,
            nodes_completed=nodes_done,
            nodes_blocked=nodes_blocked,
            errors=tuple(errors),
        )


# --- helpers ---------------------------------------------------------


def _pid(value: str) -> Any:
    from src.domain.model.workspace_plan import PlanNodeId

    return PlanNodeId(value)


def _force_execution(node: PlanNode, target: TaskExecution) -> PlanNode:
    return replace(node, execution=target)


def _force_intent(node: PlanNode, target: TaskIntent, *, summary: str = "") -> PlanNode:
    meta = dict(node.metadata)
    if summary:
        meta["last_verification_summary"] = summary
    return replace(node, intent=target, metadata=meta)


# --- optional Ray actor wrapper --------------------------------------


class RaySupervisorActor:
    """Ray actor adapter — imports Ray lazily.

    Instantiate with ``ray.remote(num_cpus=0.1)(RaySupervisorActor).remote(cfg)``
    per workspace if horizontal distribution is needed. Unit tests exercise
    :class:`WorkspaceSupervisor` directly.
    """

    def __init__(self, supervisor: WorkspaceSupervisor) -> None:  # pragma: no cover
        self._sup = supervisor

    async def start(self, workspace_id: str) -> None:  # pragma: no cover
        await self._sup.start(workspace_id)

    async def stop(self, workspace_id: str) -> None:  # pragma: no cover
        await self._sup.stop(workspace_id)

    async def tick(self, workspace_id: str) -> TickReport:  # pragma: no cover
        return await self._sup.tick(workspace_id)
