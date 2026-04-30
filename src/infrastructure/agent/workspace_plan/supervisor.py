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

The supervisor deliberately avoids direct ``workspace_goal_runtime`` calls;
runtime wiring happens in :mod:`orchestrator`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

from src.domain.model.workspace_plan import (
    Capability,
    CriterionKind,
    FeatureCheckpoint,
    GoalProgress,
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskExecution,
    TaskIntent,
    VerificationReport,
    transition_execution,
    transition_intent,
)
from src.domain.ports.services.goal_planner_port import (
    GoalPlannerPort,
    ReplanTrigger,
)
from src.domain.ports.services.iteration_review_port import (
    IterationNextTask,
    IterationReviewContext,
    IterationReviewPort,
    IterationReviewVerdict,
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
from src.infrastructure.agent.workspace_plan.planner import (
    _default_acceptance_criteria,
    _infer_write_set,
    _iteration_phase_for_sequence,
    _planner_node_metadata,
)

logger = logging.getLogger(__name__)

_RETRYABLE_INFRASTRUCTURE_CRITERION = "retryable_infrastructure_failure"
_RETRY_BACKOFF_BASE_SECONDS = 60
_RETRY_BACKOFF_MAX_SECONDS = 900
_ITERATION_LOOP_ENABLED_ENV = "WORKSPACE_V2_ITERATION_LOOP_ENABLED"
_ITERATION_LOOP_MAX_ITERATIONS_ENV = "WORKSPACE_V2_MAX_ITERATIONS"
_ITERATION_LOOP_MAX_SUBTASKS_ENV = "WORKSPACE_V2_SOFTWARE_MAX_SUBTASKS"
_ITERATION_LOOP_DEFAULT_MAX_ITERATIONS = 8
_ITERATION_LOOP_DEFAULT_MAX_SUBTASKS = 6
_ITERATION_REVIEW_MIN_CONFIDENCE = 0.6
_ITERATION_PHASES = ("research", "plan", "implement", "test", "deploy", "review")
_CHANGE_EVIDENCE_PHASES = {"implement", "test", "deploy"}
_PIPELINE_CRITERION_KINDS = {
    CriterionKind.CI_PIPELINE,
    CriterionKind.PIPELINE_STAGE,
    CriterionKind.DEPLOYMENT_HEALTH,
    CriterionKind.PREVIEW_E2E,
}
_SCRUM_ARTIFACT_BY_PHASE = {
    "research": "product_discovery",
    "plan": "sprint_backlog",
    "implement": "increment",
    "test": "verification",
    "deploy": "release_candidate",
    "review": "feedback",
}


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

PlanEventSink = Callable[[str, PlanNode, str, dict[str, Any]], Awaitable[None]]
"""Called for durable, auditable plan lifecycle events."""


class WorkspaceSupervisor(WorkspaceSupervisorPort):
    """Async single-writer supervisor. One instance per process is fine — it
    keeps per-workspace state in ``self._tasks`` indexed by ``workspace_id``.
    """

    def __init__(  # noqa: PLR0913
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
        event_sink: PlanEventSink | None = None,
        iteration_reviewer: IterationReviewPort | None = None,
        heartbeat_seconds: float = 10.0,
        max_dispatches_per_tick: int = 2,
    ) -> None:
        if max_dispatches_per_tick <= 0:
            msg = f"max_dispatches_per_tick must be > 0, got {max_dispatches_per_tick}"
            raise ValueError(msg)
        self._repo = plan_repo
        self._allocator = allocator
        self._verifier = verifier
        self._projector = projector
        self._planner = planner
        self._agent_pool = agent_pool
        self._dispatcher = dispatcher
        self._attempt_context = attempt_context
        self._progress_sink = progress_sink
        self._event_sink = event_sink
        self._iteration_reviewer = iteration_reviewer
        self._heartbeat = heartbeat_seconds
        self._max_dispatches_per_tick = max_dispatches_per_tick

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
                await self._emit_event(
                    errors,
                    workspace_id,
                    node,
                    "verification_completed",
                    _verification_payload(report),
                )
                verifies_ran += 1
                if report.passed:
                    if _should_request_pipeline_after_verification(node, ctx.artifacts):
                        pipeline_node = _node_with_pipeline_request(node, report)
                        plan.replace_node(pipeline_node)
                        await self._emit_event(
                            errors,
                            workspace_id,
                            pipeline_node,
                            "pipeline_run_requested",
                            {
                                "attempt_id": report.attempt_id,
                                "summary": "harness-native CI/CD evidence required",
                                "reason": "pipeline_gate_missing",
                            },
                        )
                        continue
                    accepted_node = _node_with_verification_evidence(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(accepted_node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                        )
                    )
                    nodes_done += 1
                elif _should_request_pipeline_from_report(node, report):
                    pipeline_node = _node_with_pipeline_request(node, report)
                    plan.replace_node(pipeline_node)
                    await self._emit_event(
                        errors,
                        workspace_id,
                        pipeline_node,
                        "pipeline_run_requested",
                        {
                            "attempt_id": report.attempt_id,
                            "summary": report.summary(),
                            "reason": "pipeline_criterion_missing",
                        },
                    )
                elif report.hard_fail:
                    plan.replace_node(
                        _force_intent(
                            _force_execution(node, TaskExecution.IDLE),
                            TaskIntent.BLOCKED,
                            summary=report.summary(),
                        )
                    )
                    nodes_blocked += 1
                elif _is_retryable_infrastructure_report(report):
                    retry_node = _node_with_retry_backoff(node, report)
                    plan.replace_node(retry_node)
                    await self._emit_event(
                        errors,
                        workspace_id,
                        retry_node,
                        "verification_retry_scheduled",
                        {
                            "attempt_id": report.attempt_id,
                            "summary": report.summary(),
                            "retry_count": retry_node.metadata.get("retry_count"),
                            "retry_not_before": retry_node.metadata.get("retry_not_before"),
                        },
                    )
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
        repaired_phase_barriers = _repair_pending_iteration_phase_barriers(plan)
        if repaired_phase_barriers:
            await self._emit_event(
                errors,
                workspace_id,
                plan.goal_node,
                "iteration_phase_barriers_repaired",
                {
                    "summary": "pending sprint nodes were missing phase barrier dependencies",
                    "node_count": repaired_phase_barriers,
                },
            )
        ready_candidates = _ready_nodes_due(plan.ready_nodes(), now=datetime.now(UTC))
        ready, deferred_by_write_scope = _select_ready_nodes_without_write_conflicts(
            ready_candidates,
            active_nodes=_active_write_scope_nodes(plan),
        )
        for deferred_node in deferred_by_write_scope:
            await self._emit_event(
                errors,
                workspace_id,
                deferred_node,
                "dispatch_deferred_write_conflict",
                {
                    "summary": "node deferred because another ready node owns an overlapping write set",
                    "write_set": list(_node_write_set(deferred_node)),
                },
            )
        ready_to_dispatch = ready[: self._max_dispatches_per_tick]
        deferred_by_dispatch_limit = ready[self._max_dispatches_per_tick :]
        for deferred_node in deferred_by_dispatch_limit:
            await self._emit_event(
                errors,
                workspace_id,
                deferred_node,
                "dispatch_deferred_concurrency_limit",
                {
                    "summary": "node deferred because the per-tick dispatch limit was reached",
                    "max_dispatches_per_tick": self._max_dispatches_per_tick,
                },
            )
        if ready_to_dispatch:
            try:
                pool = await self._agent_pool(workspace_id)
                allocations = await self._allocator.allocate(ready_to_dispatch, pool)
            except Exception as exc:
                errors.append(f"allocate: {exc}")
                allocations = []
            for alloc in allocations:
                alloc_node = plan.nodes.get(_pid(alloc.node_id))
                if alloc_node is None:
                    continue
                try:
                    attempt_id = await self._dispatcher(workspace_id, alloc, alloc_node)
                except Exception as exc:
                    errors.append(f"dispatch({alloc_node.id}): {exc}")
                    continue
                if not attempt_id:
                    continue
                updated = _node_dispatched_with_fresh_attempt(
                    alloc_node,
                    assignee_agent_id=alloc.agent_id,
                    attempt_id=attempt_id,
                )
                try:
                    transition_intent(alloc_node.intent, TaskIntent.IN_PROGRESS)
                    transition_execution(alloc_node.execution, TaskExecution.DISPATCHED)
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
            plan = await self._handle_completed_progress(
                workspace_id=workspace_id,
                plan=plan,
                errors=errors,
            )
            progress = self._projector.project(plan)
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

    async def _handle_completed_progress(  # noqa: PLR0911
        self,
        *,
        workspace_id: str,
        plan: Plan,
        errors: list[str],
    ) -> Plan:
        if not _iteration_loop_enabled():
            completed = replace(
                plan,
                status=PlanStatus.COMPLETED,
                updated_at=datetime.now(UTC),
            )
            await self._repo.save(completed)
            return completed

        goal_node = plan.goal_node
        loop_metadata = _goal_iteration_loop_metadata(goal_node)
        if self._iteration_reviewer is None and loop_metadata.get("mode") == "auto":
            suspended = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.SUSPENDED,
                updates={
                    "mode": "auto",
                    "current_iteration": _max_iteration(_runnable_nodes(plan)),
                    "max_iterations": _max_iterations(),
                    "loop_status": "suspended",
                    "stop_reason": "iteration review agent is unavailable",
                },
            )
            await self._repo.save(suspended)
            await self._emit_event(
                errors,
                workspace_id,
                suspended.goal_node,
                "iteration_loop_suspended",
                {
                    "iteration_index": _max_iteration(_runnable_nodes(plan)),
                    "reason": "iteration review agent is unavailable",
                },
            )
            return suspended
        if self._iteration_reviewer is None:
            completed = replace(plan, status=PlanStatus.COMPLETED, updated_at=datetime.now(UTC))
            await self._repo.save(completed)
            return completed

        runnable_nodes = _runnable_nodes(plan)
        if not runnable_nodes:
            completed = replace(plan, status=PlanStatus.COMPLETED, updated_at=datetime.now(UTC))
            await self._repo.save(completed)
            return completed

        current_iteration = _max_iteration(runnable_nodes)
        if _has_iteration_nodes(plan, current_iteration + 1):
            active = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.ACTIVE,
                updates={
                    "mode": "auto",
                    "current_iteration": current_iteration + 1,
                    "max_iterations": _max_iterations(),
                    "loop_status": "active",
                    "stop_reason": "",
                },
            )
            await self._repo.save(active)
            return active

        if loop_metadata.get("loop_status") == "paused":
            suspended = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.SUSPENDED,
                updates={
                    "mode": "auto",
                    "current_iteration": current_iteration,
                    "max_iterations": _max_iterations(),
                    "loop_status": "paused",
                    "stop_reason": str(loop_metadata.get("stop_reason") or "auto-loop paused"),
                },
            )
            await self._repo.save(suspended)
            await self._emit_event(
                errors,
                workspace_id,
                suspended.goal_node,
                "iteration_loop_suspended",
                {
                    "iteration_index": current_iteration,
                    "reason": "auto-loop paused",
                },
            )
            return suspended

        max_iterations = _max_iterations()
        if current_iteration >= max_iterations:
            suspended = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.SUSPENDED,
                updates={
                    "mode": "auto",
                    "current_iteration": current_iteration,
                    "max_iterations": max_iterations,
                    "loop_status": "suspended",
                    "stop_reason": f"max iterations reached: {max_iterations}",
                },
            )
            await self._repo.save(suspended)
            await self._emit_event(
                errors,
                workspace_id,
                suspended.goal_node,
                "iteration_loop_suspended",
                {
                    "iteration_index": current_iteration,
                    "reason": f"max iterations reached: {max_iterations}",
                },
            )
            return suspended

        if current_iteration in _reviewed_iterations(loop_metadata):
            suspended = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.SUSPENDED,
                updates={
                    "mode": "auto",
                    "current_iteration": current_iteration,
                    "max_iterations": max_iterations,
                    "loop_status": "suspended",
                    "stop_reason": "iteration already reviewed without a next sprint",
                },
            )
            await self._repo.save(suspended)
            return suspended

        max_next_tasks = _current_iteration_task_budget(plan, current_iteration)
        verdict = await self._iteration_reviewer.review(
            _iteration_review_context(
                workspace_id=workspace_id,
                plan=plan,
                iteration_index=current_iteration,
                max_next_tasks=max_next_tasks,
            )
        )
        verdict = _clamp_iteration_verdict_tasks(verdict, max_next_tasks=max_next_tasks)
        await self._emit_event(
            errors,
            workspace_id,
            goal_node,
            "iteration_review_completed",
            _iteration_review_payload(current_iteration, verdict),
        )

        if verdict.verdict == "complete_goal":
            completed = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.COMPLETED,
                updates={
                    "mode": "auto",
                    "current_iteration": current_iteration,
                    "max_iterations": max_iterations,
                    "loop_status": "completed",
                    "last_review_summary": verdict.summary,
                    "last_review_confidence": verdict.confidence,
                    "stop_reason": "",
                    "completed_iterations": _append_int(
                        loop_metadata.get("completed_iterations"),
                        current_iteration,
                    ),
                    "reviewed_iterations": _append_int(
                        loop_metadata.get("reviewed_iterations"),
                        current_iteration,
                    ),
                    "history": _append_history(
                        loop_metadata.get("history"), current_iteration, verdict
                    ),
                },
            )
            await self._repo.save(completed)
            await self._emit_event(
                errors,
                workspace_id,
                completed.goal_node,
                "iteration_loop_completed",
                _iteration_review_payload(current_iteration, verdict),
            )
            return completed

        if (
            verdict.verdict == "needs_human_review"
            or verdict.confidence < _ITERATION_REVIEW_MIN_CONFIDENCE
            or not verdict.next_tasks
        ):
            reason = verdict.summary or "iteration review requires human review"
            suspended = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.SUSPENDED,
                updates={
                    "mode": "auto",
                    "current_iteration": current_iteration,
                    "max_iterations": max_iterations,
                    "loop_status": "suspended",
                    "last_review_summary": verdict.summary,
                    "last_review_confidence": verdict.confidence,
                    "stop_reason": reason,
                    "feedback_items": list(verdict.feedback_items),
                    "reviewed_iterations": _append_int(
                        loop_metadata.get("reviewed_iterations"),
                        current_iteration,
                    ),
                    "history": _append_history(
                        loop_metadata.get("history"), current_iteration, verdict
                    ),
                },
            )
            await self._repo.save(suspended)
            await self._emit_event(
                errors,
                workspace_id,
                suspended.goal_node,
                "iteration_loop_suspended",
                {
                    **_iteration_review_payload(current_iteration, verdict),
                    "reason": reason,
                },
            )
            return suspended

        next_iteration = current_iteration + 1
        continued = _append_next_iteration(
            plan,
            verdict=verdict,
            next_iteration=next_iteration,
            max_iterations=max_iterations,
        )
        await self._repo.save(continued)
        await self._emit_event(
            errors,
            workspace_id,
            continued.goal_node,
            "iteration_next_sprint_planned",
            {
                **_iteration_review_payload(current_iteration, verdict),
                "next_iteration": next_iteration,
                "task_count": len(verdict.next_tasks),
            },
        )
        return continued

    async def _emit_event(
        self,
        errors: list[str],
        workspace_id: str,
        node: PlanNode,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if self._event_sink is None:
            return
        try:
            await self._event_sink(workspace_id, node, event_type, payload)
        except Exception as exc:
            errors.append(f"event_sink({event_type}:{node.id}): {exc}")


# --- helpers ---------------------------------------------------------


def _iteration_loop_enabled() -> bool:
    return os.getenv(_ITERATION_LOOP_ENABLED_ENV, "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _max_iterations() -> int:
    raw_value = os.getenv(_ITERATION_LOOP_MAX_ITERATIONS_ENV)
    if raw_value is None:
        return _ITERATION_LOOP_DEFAULT_MAX_ITERATIONS
    try:
        parsed = int(raw_value)
    except ValueError:
        return _ITERATION_LOOP_DEFAULT_MAX_ITERATIONS
    return max(1, parsed)


def _runnable_nodes(plan: Plan) -> list[PlanNode]:
    return [
        node
        for node in plan.nodes.values()
        if node.kind in {PlanNodeKind.TASK, PlanNodeKind.VERIFY}
    ]


def _max_iteration(nodes: list[PlanNode]) -> int:
    if not nodes:
        return 1
    return max(_node_iteration_index(node) for node in nodes)


def _has_iteration_nodes(plan: Plan, iteration_index: int) -> bool:
    return any(_node_iteration_index(node) == iteration_index for node in _runnable_nodes(plan))


def _node_iteration_index(node: PlanNode) -> int:
    value = dict(node.metadata or {}).get("iteration_index")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return max(1, int(value))
    return 1


def _node_iteration_phase(node: PlanNode) -> str:
    phase = dict(node.metadata or {}).get("iteration_phase")
    if isinstance(phase, str) and phase in _ITERATION_PHASES:
        return phase
    sequence = node.feature_checkpoint.sequence if node.feature_checkpoint is not None else 0
    return _iteration_phase_for_sequence(sequence)


def _goal_iteration_loop_metadata(goal_node: PlanNode) -> dict[str, Any]:
    value = dict(goal_node.metadata or {}).get("iteration_loop")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _replace_goal_loop_metadata(
    plan: Plan,
    *,
    status: PlanStatus,
    updates: dict[str, Any],
) -> Plan:
    goal_node = plan.goal_node
    metadata = dict(goal_node.metadata or {})
    loop = _goal_iteration_loop_metadata(goal_node)
    loop.update(updates)
    metadata["iteration_loop"] = loop
    plan.replace_node(replace(goal_node, metadata=metadata, updated_at=datetime.now(UTC)))
    return replace(plan, status=status, updated_at=datetime.now(UTC))


def _reviewed_iterations(loop_metadata: dict[str, Any]) -> set[int]:
    return {
        item
        for item in _int_list(loop_metadata.get("reviewed_iterations"))
        if isinstance(item, int)
    }


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list | tuple | set):
        return []
    items: list[int] = []
    for item in value:
        if isinstance(item, int):
            items.append(item)
        elif isinstance(item, str) and item.isdigit():
            items.append(int(item))
    return items


def _append_int(value: object, item: int) -> list[int]:
    items = _int_list(value)
    if item not in items:
        items.append(item)
    return items


def _append_history(
    value: object,
    iteration_index: int,
    verdict: IterationReviewVerdict,
) -> list[dict[str, Any]]:
    history = (
        [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    )
    history.append(
        {
            "iteration_index": iteration_index,
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "summary": verdict.summary,
            "next_sprint_goal": verdict.next_sprint_goal,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    return history[-12:]


def _clamp_iteration_verdict_tasks(
    verdict: IterationReviewVerdict,
    *,
    max_next_tasks: int,
) -> IterationReviewVerdict:
    if len(verdict.next_tasks) <= max_next_tasks:
        return verdict
    return replace(verdict, next_tasks=verdict.next_tasks[:max_next_tasks])


def _iteration_review_context(
    *,
    workspace_id: str,
    plan: Plan,
    iteration_index: int,
    max_next_tasks: int,
) -> IterationReviewContext:
    nodes = [
        node for node in _runnable_nodes(plan) if _node_iteration_index(node) == iteration_index
    ]
    return IterationReviewContext(
        workspace_id=workspace_id,
        plan_id=plan.id,
        iteration_index=iteration_index,
        goal_title=plan.goal_node.title,
        goal_description=plan.goal_node.description,
        completed_tasks=tuple(_completed_task_payload(node) for node in nodes),
        deliverables=tuple(_iteration_deliverables(nodes)),
        feedback_items=tuple(_iteration_feedback_items(nodes)),
        max_next_tasks=max_next_tasks,
    )


def _completed_task_payload(node: PlanNode) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": node.id,
        "title": node.title,
        "description": node.description,
        "phase": _node_iteration_phase(node),
        "intent": node.intent.value,
    }
    evidence_refs = _node_evidence_refs(node)
    if evidence_refs:
        payload["evidence_refs"] = evidence_refs
    artifacts = _node_artifacts(node)
    if artifacts:
        payload["artifacts"] = artifacts
    if node.feature_checkpoint is not None and node.feature_checkpoint.expected_artifacts:
        payload["expected_artifacts"] = list(node.feature_checkpoint.expected_artifacts)
    summary = _node_verification_summary(node)
    if isinstance(summary, str) and summary:
        payload["verification_summary"] = summary
    return payload


def _iteration_deliverables(nodes: list[PlanNode]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        if node.feature_checkpoint is not None:
            values.extend(node.feature_checkpoint.expected_artifacts)
        values.extend(_node_artifacts(node))
        write_set = dict(node.metadata or {}).get("write_set")
        if isinstance(write_set, list):
            values.extend(item for item in write_set if isinstance(item, str) and item)
    return list(dict.fromkeys(values))[:12]


def _iteration_feedback_items(nodes: list[PlanNode]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        metadata = dict(node.metadata or {})
        if _node_has_accepted_terminal_attempt(metadata) and (
            metadata.get("last_verification_passed") is not True
        ):
            continue
        for key in ("last_verification_summary", "retry_last_reason"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return list(dict.fromkeys(values))[:8]


def _node_verification_summary(node: PlanNode) -> str:
    metadata = dict(node.metadata or {})
    summary = metadata.get("last_verification_summary")
    if metadata.get("last_verification_passed") is True:
        return summary if isinstance(summary, str) else "verified"
    if _node_has_accepted_terminal_attempt(metadata):
        return "accepted terminal attempt"
    return summary if isinstance(summary, str) else ""


def _node_has_accepted_terminal_attempt(metadata: dict[str, Any]) -> bool:
    return str(metadata.get("terminal_attempt_status") or "").lower() == "accepted"


def _node_evidence_refs(node: PlanNode) -> list[str]:
    raw = dict(node.metadata or {}).get("verification_evidence_refs")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str) and item]
    return []


def _node_artifacts(node: PlanNode) -> list[str]:
    metadata = dict(node.metadata or {})
    values: list[str] = []
    for key in (
        "candidate_artifacts",
        "last_worker_report_artifacts",
        "execution_artifacts",
        "expected_artifacts",
    ):
        values.extend(_string_list(metadata.get(key)))
    return list(dict.fromkeys(values))


def _current_iteration_task_budget(plan: Plan, iteration_index: int) -> int:
    _ = (plan, iteration_index)
    raw_value = os.getenv(_ITERATION_LOOP_MAX_SUBTASKS_ENV)
    if raw_value is None:
        return _ITERATION_LOOP_DEFAULT_MAX_SUBTASKS
    try:
        parsed = int(raw_value)
    except ValueError:
        return _ITERATION_LOOP_DEFAULT_MAX_SUBTASKS
    return max(1, min(parsed, len(_ITERATION_PHASES)))


def _iteration_review_payload(
    iteration_index: int,
    verdict: IterationReviewVerdict,
) -> dict[str, Any]:
    return {
        "iteration_index": iteration_index,
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "summary": verdict.summary,
        "next_sprint_goal": verdict.next_sprint_goal,
        "feedback_items": list(verdict.feedback_items),
        "next_tasks": [
            {
                "id": task.id,
                "description": task.description,
                "target_subagent": task.target_subagent,
                "dependencies": list(task.dependencies),
                "priority": task.priority,
                "phase": task.phase,
                "expected_artifacts": list(task.expected_artifacts),
            }
            for task in verdict.next_tasks
        ],
    }


def _append_next_iteration(
    plan: Plan,
    *,
    verdict: IterationReviewVerdict,
    next_iteration: int,
    max_iterations: int,
) -> Plan:
    loop_metadata = _goal_iteration_loop_metadata(plan.goal_node)
    id_map = {
        task.id: PlanNodeId(f"node-{uuid.uuid4().hex[:12]}")
        for task in verdict.next_tasks
        if task.id
    }
    task_specs: list[tuple[int, IterationNextTask, PlanNodeId, str]] = []
    nodes_by_phase: dict[str, list[PlanNodeId]] = {phase: [] for phase in _ITERATION_PHASES}
    normalized_phases = _normalized_next_iteration_task_phases(verdict.next_tasks)
    sequence_by_task_id = {
        task.id: sequence for sequence, task in enumerate(verdict.next_tasks, start=1) if task.id
    }
    for sequence, task in enumerate(verdict.next_tasks, start=1):
        node_id = id_map.get(task.id) or PlanNodeId(f"node-{uuid.uuid4().hex[:12]}")
        phase = normalized_phases[sequence - 1]
        task_specs.append((sequence, task, node_id, phase))
        nodes_by_phase.setdefault(phase, []).append(node_id)
    dependencies_by_node: dict[PlanNodeId, tuple[PlanNodeId, ...]] = {}
    for sequence, task, node_id, phase in task_specs:
        explicit_dependencies = tuple(
            id_map[dep]
            for dep in task.dependencies
            if dep in id_map
            and id_map[dep] != node_id
            and sequence_by_task_id.get(dep, sequence + 1) < sequence
        )
        dependencies_by_node[node_id] = tuple(
            dict.fromkeys(
                (
                    *explicit_dependencies,
                    *_phase_barrier_dependencies(phase, nodes_by_phase),
                )
            )
        )
        _add_next_iteration_node(
            plan,
            task=task,
            node_id=node_id,
            next_iteration=next_iteration,
            sequence=sequence,
            phase=phase,
        )
    for node_id, dependencies in dependencies_by_node.items():
        node = plan.nodes[node_id]
        plan.replace_node(replace(node, depends_on=frozenset(dependencies)))
    return _replace_goal_loop_metadata(
        plan,
        status=PlanStatus.ACTIVE,
        updates={
            "mode": "auto",
            "current_iteration": next_iteration,
            "max_iterations": max_iterations,
            "loop_status": "active",
            "last_review_summary": verdict.summary,
            "last_review_confidence": verdict.confidence,
            "current_sprint_goal": verdict.next_sprint_goal,
            "next_sprint_goal": verdict.next_sprint_goal,
            "stop_reason": "",
            "feedback_items": list(verdict.feedback_items),
            "completed_iterations": _append_int(
                loop_metadata.get("completed_iterations"),
                next_iteration - 1,
            ),
            "reviewed_iterations": _append_int(
                loop_metadata.get("reviewed_iterations"),
                next_iteration - 1,
            ),
            "history": _append_history(loop_metadata.get("history"), next_iteration - 1, verdict),
        },
    )


def _add_next_iteration_node(
    plan: Plan,
    *,
    task: IterationNextTask,
    node_id: PlanNodeId,
    next_iteration: int,
    sequence: int,
    phase: str,
) -> None:
    metadata = _planner_node_metadata(
        task.description,
        node_id=node_id,
        sequence=sequence,
    )
    metadata.update(
        {
            "iteration_index": next_iteration,
            "iteration_phase": phase,
            "iteration_loop": "scrum_feedback_loop_v1",
            "scrum_artifact": _SCRUM_ARTIFACT_BY_PHASE[phase],
        }
    )
    write_set = _infer_write_set(task.description)
    expected_artifacts = _feature_checkpoint_expected_artifacts(
        task,
        phase=phase,
        write_set=write_set,
    )
    if task.expected_artifacts:
        metadata["expected_artifacts"] = list(task.expected_artifacts)
    if write_set:
        metadata["write_set"] = list(write_set)
    plan.add_node(
        PlanNode(
            id=node_id.value,
            plan_id=plan.id,
            parent_id=plan.goal_id,
            kind=PlanNodeKind.TASK,
            title=task.description[:120] or f"Iteration {next_iteration} task {sequence}",
            description=task.description,
            depends_on=frozenset(),
            recommended_capabilities=(Capability(name=f"agent:{task.target_subagent}", weight=2.0),)
            if task.target_subagent
            else (),
            preferred_agent_id=task.target_subagent,
            priority=max(0, task.priority),
            acceptance_criteria=_default_acceptance_criteria(task.description),
            feature_checkpoint=FeatureCheckpoint(
                feature_id=f"iteration-{next_iteration}-{sequence}-{node_id.value}",
                sequence=sequence,
                title=task.description[:120],
                expected_artifacts=expected_artifacts,
            ),
            metadata=metadata,
        )
    )


def _next_iteration_task_phase(task: IterationNextTask, sequence: int) -> str:
    return (
        task.phase if task.phase in _ITERATION_PHASES else _iteration_phase_for_sequence(sequence)
    )


def _normalized_next_iteration_task_phases(tasks: tuple[IterationNextTask, ...]) -> list[str]:
    phases = [
        _next_iteration_task_phase(task, sequence) for sequence, task in enumerate(tasks, start=1)
    ]
    if _phases_are_monotonic(phases):
        return phases
    return [_iteration_phase_for_sequence(sequence) for sequence in range(1, len(tasks) + 1)]


def _normalized_pending_iteration_phases(nodes: list[PlanNode]) -> dict[PlanNodeId, str]:
    ordered = _ordered_iteration_nodes(nodes)
    phases = [_node_iteration_phase(node) for node in ordered]
    if not _phases_are_monotonic(phases):
        phases = [_iteration_phase_for_sequence(index) for index in range(1, len(ordered) + 1)]
    return {node.node_id: phase for node, phase in zip(ordered, phases, strict=False)}


def _phases_are_monotonic(phases: list[str]) -> bool:
    phase_indexes = [_phase_index(phase) for phase in phases]
    return all(current >= previous for previous, current in pairwise(phase_indexes))


def _phase_index(phase: str) -> int:
    try:
        return _ITERATION_PHASES.index(phase)
    except ValueError:
        return 0


def _ordered_iteration_nodes(nodes: list[PlanNode]) -> list[PlanNode]:
    return sorted(nodes, key=lambda node: (_node_sequence(node), node.created_at, node.id))


def _node_sequence(node: PlanNode) -> int:
    if node.feature_checkpoint is not None and node.feature_checkpoint.sequence > 0:
        return node.feature_checkpoint.sequence
    value = dict(node.metadata or {}).get("sequence")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return max(1, int(value))
    return 999_999


def _phase_barrier_dependencies(
    phase: str,
    nodes_by_phase: dict[str, list[PlanNodeId]],
) -> tuple[PlanNodeId, ...]:
    if phase not in _ITERATION_PHASES:
        return ()
    phase_index = _ITERATION_PHASES.index(phase)
    dependencies: list[PlanNodeId] = []
    for prior_phase in _ITERATION_PHASES[:phase_index]:
        dependencies.extend(nodes_by_phase.get(prior_phase, ()))
    return tuple(dependencies)


def _repair_pending_iteration_phase_barriers(plan: Plan) -> int:
    """Repair persisted next-sprint nodes created before phase barriers existed.

    The append path now writes these dependencies up front. This tick-time repair keeps
    already persisted, not-yet-started sprint nodes from dispatching test/deploy/review
    work before the implementation phase has produced evidence.
    """
    nodes_by_iteration: dict[int, list[PlanNode]] = {}
    for node in _runnable_nodes(plan):
        nodes_by_iteration.setdefault(_node_iteration_index(node), []).append(node)

    repaired = 0
    now = datetime.now(UTC)
    for iteration_index, nodes in nodes_by_iteration.items():
        if iteration_index <= 1 or len(nodes) < 2:
            continue
        ordered_nodes = _ordered_iteration_nodes(nodes)
        sequence_by_node = {
            node.node_id: sequence for sequence, node in enumerate(ordered_nodes, start=1)
        }
        normalized_phases = _normalized_pending_iteration_phases(ordered_nodes)
        phase_nodes: dict[str, list[PlanNodeId]] = {phase: [] for phase in _ITERATION_PHASES}
        for node in ordered_nodes:
            phase_nodes.setdefault(normalized_phases[node.node_id], []).append(node.node_id)
        iteration_node_ids = frozenset(sequence_by_node)
        for node in ordered_nodes:
            if node.intent is not TaskIntent.TODO or node.current_attempt_id:
                continue
            phase = normalized_phases[node.node_id]
            node_sequence = sequence_by_node[node.node_id]
            desired_dependencies = {
                dep
                for dep in node.depends_on
                if dep not in iteration_node_ids
                or sequence_by_node.get(dep, node_sequence + 1) < node_sequence
            }
            desired_dependencies.update(
                dep
                for dep in _phase_barrier_dependencies(phase, phase_nodes)
                if sequence_by_node.get(dep, node_sequence + 1) < node_sequence
            )
            desired_dependencies.discard(node.node_id)
            desired = frozenset(desired_dependencies)
            metadata = dict(node.metadata or {})
            phase_changed = metadata.get("iteration_phase") != phase
            if desired == node.depends_on and not phase_changed:
                continue
            metadata["iteration_phase"] = phase
            metadata["scrum_artifact"] = _SCRUM_ARTIFACT_BY_PHASE[phase]
            metadata["phase_barrier_dependencies_repaired_at"] = now.isoformat()
            plan.replace_node(
                replace(
                    node,
                    depends_on=desired,
                    metadata=metadata,
                    updated_at=now,
                )
            )
            repaired += 1
    return repaired


def _feature_checkpoint_expected_artifacts(
    task: IterationNextTask,
    *,
    phase: str,
    write_set: tuple[str, ...],
) -> tuple[str, ...]:
    if write_set:
        return write_set
    if phase in _CHANGE_EVIDENCE_PHASES:
        return task.expected_artifacts
    return ()


def _pid(value: str) -> PlanNodeId:
    return PlanNodeId(value)


_STALE_ATTEMPT_METADATA_KEYS = frozenset(
    {
        "last_verification_summary",
        "last_verification_passed",
        "last_verification_hard_fail",
        "last_verification_attempt_id",
        "last_verification_ran_at",
        "verification_evidence_refs",
        "verified_commit_ref",
        "verified_git_diff_summary",
        "verified_test_commands",
        "retry_last_reason",
        "terminal_attempt_status",
        "terminal_attempt_reconciled_at",
        "pipeline_status",
        "pipeline_gate_status",
        "pipeline_run_id",
        "pipeline_evidence_refs",
        "pipeline_last_summary",
    }
)


def _clear_stale_attempt_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    for key in _STALE_ATTEMPT_METADATA_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _node_dispatched_with_fresh_attempt(
    node: PlanNode,
    *,
    assignee_agent_id: str,
    attempt_id: str,
) -> PlanNode:
    metadata = _clear_stale_attempt_metadata(node.metadata)
    return replace(
        node,
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.DISPATCHED,
        assignee_agent_id=assignee_agent_id,
        current_attempt_id=attempt_id,
        metadata=metadata,
        updated_at=datetime.now(UTC),
    )


def _force_execution(node: PlanNode, target: TaskExecution) -> PlanNode:
    return replace(node, execution=target, updated_at=datetime.now(UTC))


def _force_intent(node: PlanNode, target: TaskIntent, *, summary: str = "") -> PlanNode:
    meta = dict(node.metadata)
    if summary:
        meta["last_verification_summary"] = summary
    return replace(node, intent=target, metadata=meta, updated_at=datetime.now(UTC))


def _is_retryable_infrastructure_report(report: VerificationReport) -> bool:
    for result in report.results:
        if not result.criterion.required or result.passed:
            continue
        if result.criterion.spec.get("name") == _RETRYABLE_INFRASTRUCTURE_CRITERION:
            return True
    return False


def _should_request_pipeline_after_verification(
    node: PlanNode,
    artifacts: Mapping[str, Any],
) -> bool:
    if not _node_requires_pipeline_gate(node):
        return False
    if _node_has_pipeline_success(node, artifacts):
        return False
    return _pipeline_gate_status(node) not in {"requested", "running"}


def _should_request_pipeline_from_report(node: PlanNode, report: VerificationReport) -> bool:
    if _pipeline_gate_status(node) in {"requested", "running"}:
        return False
    for result in report.failed_required:
        if result.criterion.kind in _PIPELINE_CRITERION_KINDS:
            return True
    return _node_requires_pipeline_gate(node) and not report.hard_fail


def _node_requires_pipeline_gate(node: PlanNode) -> bool:
    if node.kind is PlanNodeKind.GOAL:
        return False
    raw_required = node.metadata.get("pipeline_required")
    if isinstance(raw_required, bool):
        return raw_required
    return False


def _node_has_pipeline_success(node: PlanNode, artifacts: Mapping[str, Any]) -> bool:
    values = set(_string_list(node.metadata.get("pipeline_evidence_refs")))
    values.update(_string_list(node.metadata.get("execution_verifications")))
    values.update(_string_list(artifacts.get("pipeline_evidence_refs")))
    values.update(_string_list(artifacts.get("execution_verifications")))
    return "ci_pipeline:passed" in values or any(
        value.startswith("pipeline_run:success:") for value in values
    )


def _pipeline_gate_status(node: PlanNode) -> str:
    value = node.metadata.get("pipeline_status") or node.metadata.get("pipeline_gate_status")
    return value.strip().lower() if isinstance(value, str) else ""


def _node_with_pipeline_request(node: PlanNode, report: VerificationReport) -> PlanNode:
    metadata = dict(node.metadata)
    request_count = _coerce_positive_int(metadata.get("pipeline_request_count")) + 1
    metadata.update(
        {
            "pipeline_required": True,
            "pipeline_provider": metadata.get("pipeline_provider") or "sandbox_native",
            "pipeline_status": "requested",
            "pipeline_gate_status": "requested",
            "pipeline_request_count": request_count,
            "pipeline_requested_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "last_verification_summary": report.summary(),
            "last_verification_passed": False,
            "last_verification_hard_fail": False,
        }
    )
    if report.attempt_id:
        metadata["last_verification_attempt_id"] = report.attempt_id
    return replace(
        node,
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.IDLE,
        metadata=metadata,
        updated_at=datetime.now(UTC),
    )


def _node_with_retry_backoff(node: PlanNode, report: VerificationReport) -> PlanNode:
    metadata = dict(node.metadata)
    retry_count = _coerce_positive_int(metadata.get("retry_count")) + 1
    delay_seconds = min(
        _RETRY_BACKOFF_BASE_SECONDS * (2 ** (retry_count - 1)),
        _RETRY_BACKOFF_MAX_SECONDS,
    )
    retry_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    metadata["retry_count"] = retry_count
    metadata["retry_not_before"] = retry_at.isoformat().replace("+00:00", "Z")
    metadata["retry_last_reason"] = report.summary()
    return replace(
        node,
        intent=TaskIntent.TODO,
        execution=TaskExecution.IDLE,
        current_attempt_id=None,
        metadata=metadata,
        updated_at=datetime.now(UTC),
    )


def _ready_nodes_due(ready_nodes: list[PlanNode], *, now: datetime) -> list[PlanNode]:
    return [node for node in ready_nodes if _node_retry_not_before(node) <= now]


def _node_retry_not_before(node: PlanNode) -> datetime:
    raw = node.metadata.get("retry_not_before")
    if not isinstance(raw, str) or not raw.strip():
        return datetime.min.replace(tzinfo=UTC)
    value = raw.strip()
    if value.endswith("Z"):
        value = value.removesuffix("Z") + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_positive_int(value: object) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return 0


def _verification_payload(report: VerificationReport) -> dict[str, Any]:
    return {
        "attempt_id": report.attempt_id,
        "passed": report.passed,
        "hard_fail": report.hard_fail,
        "summary": report.summary(),
        "ran_at": report.ran_at.isoformat().replace("+00:00", "Z"),
        "results": [
            {
                "kind": result.criterion.kind.value,
                "required": result.criterion.required,
                "passed": result.passed,
                "confidence": result.confidence,
                "message": result.message,
                "evidence": [
                    {"kind": evidence.kind, "ref": evidence.ref, "note": evidence.note}
                    for evidence in result.evidence
                ],
            }
            for result in report.results
        ],
    }


def _node_with_verification_evidence(
    node: PlanNode,
    report: VerificationReport,
    *,
    artifacts: Mapping[str, Any] | None = None,
) -> PlanNode:
    refs = _report_evidence_refs(report)
    commit_ref = _first_prefixed_value(refs, "commit_ref:")
    git_diff_summary = _first_prefixed_value(refs, "git_diff_summary:")
    test_commands = tuple(
        dict.fromkeys(ref.removeprefix("test_run:") for ref in refs if ref.startswith("test_run:"))
    )
    metadata = dict(node.metadata)
    metadata["last_verification_summary"] = report.summary()
    metadata["last_verification_passed"] = report.passed
    metadata["last_verification_hard_fail"] = report.hard_fail
    metadata["last_verification_ran_at"] = report.ran_at.isoformat().replace("+00:00", "Z")
    if report.attempt_id:
        metadata["last_verification_attempt_id"] = report.attempt_id
    metadata["verification_evidence_refs"] = refs
    if commit_ref:
        metadata["verified_commit_ref"] = commit_ref
    if git_diff_summary:
        metadata["verified_git_diff_summary"] = git_diff_summary
    if test_commands:
        metadata["verified_test_commands"] = list(test_commands)
    pipeline_status, pipeline_run_id = _pipeline_status_from_refs(
        _pipeline_refs_for_verification(refs, artifacts)
    )
    if pipeline_status:
        metadata["pipeline_status"] = pipeline_status
        metadata["pipeline_gate_status"] = pipeline_status
    if pipeline_run_id:
        metadata["pipeline_run_id"] = pipeline_run_id
    if artifacts:
        _copy_verification_artifacts(metadata, artifacts)

    feature_checkpoint = node.feature_checkpoint
    if feature_checkpoint is not None and commit_ref:
        feature_checkpoint = replace(feature_checkpoint, commit_ref=commit_ref)

    handoff_package = node.handoff_package
    if handoff_package is not None:
        handoff_package = replace(
            handoff_package,
            git_head=commit_ref or handoff_package.git_head,
            git_diff_summary=git_diff_summary or handoff_package.git_diff_summary,
            test_commands=test_commands or handoff_package.test_commands,
            verification_notes=report.summary(),
        )

    return replace(
        node,
        metadata=metadata,
        feature_checkpoint=feature_checkpoint,
        handoff_package=handoff_package,
        updated_at=datetime.now(UTC),
    )


def _report_evidence_refs(report: VerificationReport) -> list[str]:
    refs: list[str] = []
    for result in report.results:
        refs.extend(evidence.ref for evidence in result.evidence if evidence.ref)
    return list(dict.fromkeys(refs))


def _pipeline_refs_for_verification(
    refs: list[str],
    artifacts: Mapping[str, Any] | None,
) -> list[str]:
    pipeline_refs: list[str] = []
    if artifacts:
        pipeline_refs.extend(_string_list(artifacts.get("pipeline_evidence_refs")))
    if pipeline_refs:
        return list(dict.fromkeys(pipeline_refs))

    pipeline_refs = list(refs)
    if artifacts:
        for key in ("evidence_refs", "execution_verifications", "verification_evidence_refs"):
            pipeline_refs.extend(_string_list(artifacts.get(key)))
    return list(dict.fromkeys(pipeline_refs))


def _pipeline_status_from_refs(refs: list[str]) -> tuple[str | None, str | None]:
    status: str | None = None
    run_id: str | None = None
    if "ci_pipeline:passed" in refs:
        status = "success"
    elif "ci_pipeline:failed" in refs:
        status = "failed"
    for ref in refs:
        if ref.startswith("pipeline_run:success:"):
            status = "success"
            run_id = ref.removeprefix("pipeline_run:success:")
        elif ref.startswith("pipeline_run:failed:"):
            status = "failed"
            run_id = ref.removeprefix("pipeline_run:failed:")
    return status, run_id


def _copy_verification_artifacts(
    metadata: dict[str, Any],
    artifacts: Mapping[str, Any],
) -> None:
    for key in (
        "candidate_artifacts",
        "last_worker_report_artifacts",
        "execution_artifacts",
        "pipeline_evidence_refs",
    ):
        values = _string_list(artifacts.get(key))
        if values:
            metadata[key] = values
    for key in (
        "candidate_verifications",
        "last_worker_report_verifications",
        "execution_verifications",
    ):
        values = _string_list(artifacts.get(key))
        if values:
            metadata[key] = values


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple):
        return [str(item) for item in value if item]
    return []


def _first_prefixed_value(values: list[str], prefix: str) -> str | None:
    for value in values:
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return None


def _select_ready_nodes_without_write_conflicts(
    ready_nodes: list[PlanNode],
    *,
    active_nodes: list[PlanNode] | None = None,
) -> tuple[list[PlanNode], list[PlanNode]]:
    """Keep parallel dispatch from assigning overlapping write sets."""

    selected: list[PlanNode] = []
    deferred: list[PlanNode] = []
    claimed: set[str] = set()
    for active_node in active_nodes or ():
        claimed.update(_node_write_set(active_node))
    for node in sorted(ready_nodes, key=lambda n: n.priority, reverse=True):
        write_set = _node_write_set(node)
        if write_set and not claimed.isdisjoint(write_set):
            deferred.append(node)
            continue
        selected.append(node)
        claimed.update(write_set)
    return selected, deferred


def _active_write_scope_nodes(plan: Plan) -> list[PlanNode]:
    return [
        node
        for node in plan.leaf_tasks()
        if node.execution
        in {
            TaskExecution.DISPATCHED,
            TaskExecution.RUNNING,
            TaskExecution.REPORTED,
            TaskExecution.VERIFYING,
        }
    ]


def _node_write_set(node: PlanNode) -> frozenset[str]:
    value = node.metadata.get("write_set")
    if not isinstance(value, list):
        return frozenset()
    return frozenset(str(item) for item in value if isinstance(item, str) and item)


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
