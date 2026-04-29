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
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from src.domain.model.workspace_plan import (
    Capability,
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
                    accepted_node = _node_with_verification_evidence(node, report)
                    plan.replace_node(
                        _force_intent(
                            _force_execution(accepted_node, TaskExecution.IDLE),
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
        ready_candidates = _ready_nodes_due(plan.ready_nodes(), now=datetime.now(UTC))
        ready, deferred_by_write_scope = _select_ready_nodes_without_write_conflicts(
            ready_candidates
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
                updated = replace(
                    alloc_node,
                    intent=TaskIntent.IN_PROGRESS,
                    execution=TaskExecution.DISPATCHED,
                    assignee_agent_id=alloc.agent_id,
                    current_attempt_id=attempt_id,
                    updated_at=datetime.now(UTC),
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
        if not _iteration_loop_enabled() or self._iteration_reviewer is None:
            completed = replace(
                plan,
                status=PlanStatus.COMPLETED,
                updated_at=datetime.now(UTC),
            )
            await self._repo.save(completed)
            return completed

        goal_node = plan.goal_node
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

        loop_metadata = _goal_iteration_loop_metadata(goal_node)
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
    if node.feature_checkpoint is not None and node.feature_checkpoint.expected_artifacts:
        payload["expected_artifacts"] = list(node.feature_checkpoint.expected_artifacts)
    summary = dict(node.metadata or {}).get("last_verification_summary")
    if isinstance(summary, str) and summary:
        payload["verification_summary"] = summary
    return payload


def _iteration_deliverables(nodes: list[PlanNode]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        if node.feature_checkpoint is not None:
            values.extend(node.feature_checkpoint.expected_artifacts)
        write_set = dict(node.metadata or {}).get("write_set")
        if isinstance(write_set, list):
            values.extend(item for item in write_set if isinstance(item, str) and item)
    return list(dict.fromkeys(values))[:12]


def _iteration_feedback_items(nodes: list[PlanNode]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        metadata = dict(node.metadata or {})
        for key in ("last_verification_summary", "retry_last_reason"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                values.append(value)
    return list(dict.fromkeys(values))[:8]


def _node_evidence_refs(node: PlanNode) -> list[str]:
    raw = dict(node.metadata or {}).get("verification_evidence_refs")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str) and item]
    return []


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
    for sequence, task in enumerate(verdict.next_tasks, start=1):
        _add_next_iteration_node(
            plan,
            task=task,
            node_id=id_map.get(task.id) or PlanNodeId(f"node-{uuid.uuid4().hex[:12]}"),
            id_map=id_map,
            next_iteration=next_iteration,
            sequence=sequence,
        )
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
    id_map: dict[str, PlanNodeId],
    next_iteration: int,
    sequence: int,
) -> None:
    phase = (
        task.phase if task.phase in _ITERATION_PHASES else _iteration_phase_for_sequence(sequence)
    )
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
    if task.expected_artifacts:
        metadata["expected_artifacts"] = list(task.expected_artifacts)
    write_set = _infer_write_set(task.description)
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
            depends_on=frozenset(id_map[dep] for dep in task.dependencies if dep in id_map),
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
                expected_artifacts=task.expected_artifacts,
            ),
            metadata=metadata,
        )
    )


def _pid(value: str) -> PlanNodeId:
    return PlanNodeId(value)


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


def _node_with_verification_evidence(node: PlanNode, report: VerificationReport) -> PlanNode:
    refs = _report_evidence_refs(report)
    commit_ref = _first_prefixed_value(refs, "commit_ref:")
    git_diff_summary = _first_prefixed_value(refs, "git_diff_summary:")
    test_commands = tuple(
        dict.fromkeys(ref.removeprefix("test_run:") for ref in refs if ref.startswith("test_run:"))
    )
    metadata = dict(node.metadata)
    if commit_ref:
        metadata["verified_commit_ref"] = commit_ref
    if git_diff_summary:
        metadata["verified_git_diff_summary"] = git_diff_summary
    if test_commands:
        metadata["verified_test_commands"] = list(test_commands)

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


def _first_prefixed_value(values: list[str], prefix: str) -> str | None:
    for value in values:
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return None


def _select_ready_nodes_without_write_conflicts(
    ready_nodes: list[PlanNode],
) -> tuple[list[PlanNode], list[PlanNode]]:
    """Keep parallel dispatch from assigning overlapping write sets in one tick."""

    selected: list[PlanNode] = []
    deferred: list[PlanNode] = []
    claimed: set[str] = set()
    for node in sorted(ready_nodes, key=lambda n: n.priority, reverse=True):
        write_set = _node_write_set(node)
        if write_set and not claimed.isdisjoint(write_set):
            deferred.append(node)
            continue
        selected.append(node)
        claimed.update(write_set)
    return selected, deferred


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
