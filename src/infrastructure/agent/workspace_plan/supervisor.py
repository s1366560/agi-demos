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
from typing import Any

from src.domain.model.workspace_plan import (
    Capability,
    CriterionKind,
    CriterionResult,
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

        reopened_pipeline_nodes = _reopen_done_nodes_with_failed_pipeline(plan)
        for node in reopened_pipeline_nodes:
            await self._emit_event(
                errors,
                workspace_id,
                node,
                "pipeline_failed_done_node_reopened",
                {
                    "attempt_id": node.current_attempt_id,
                    "pipeline_status": node.metadata.get("pipeline_status"),
                    "pipeline_run_id": node.metadata.get("pipeline_run_id"),
                    "summary": "done node reopened because required pipeline failed",
                },
            )

        # --- 1. verify any REPORTED nodes ------------------------------
        reported = [n for n in plan.nodes.values() if n.execution is TaskExecution.REPORTED]
        for node in reported:
            try:
                if (
                    repair_alternative := _completed_repair_alternative_superseding_reported_repair(
                        plan, node
                    )
                ) is not None:
                    superseded_node = _node_with_repair_alternative_disposition_from_metadata(
                        node,
                        repair_node=repair_alternative,
                        disposition="superseded_by_completed_repair_alternative",
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(superseded_node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                            summary=str(
                                superseded_node.metadata.get("last_verification_summary") or ""
                            ),
                        )
                    )
                    await self._emit_event(
                        errors,
                        workspace_id,
                        superseded_node,
                        "verification_feedback_disposition",
                        {
                            "attempt_id": node.current_attempt_id,
                            "disposition": "superseded_by_completed_repair_alternative",
                            "repair_node_id": repair_alternative.id,
                            "feedback_items": [],
                            "summary": superseded_node.metadata.get("last_verification_summary"),
                        },
                    )
                    nodes_done += 1
                    continue
                if _node_retry_not_before(node) > datetime.now(UTC):
                    continue
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
                feedback_items = _verification_feedback_items(report)
                if feedback_items:
                    await self._emit_event(
                        errors,
                        workspace_id,
                        node,
                        "verification_feedback_routed",
                        {
                            "attempt_id": report.attempt_id,
                            "feedback_items": feedback_items,
                            "feedback_counts": _verification_feedback_counts(feedback_items),
                            "summary": report.summary(),
                        },
                    )
                verifies_ran += 1
                if report.passed:
                    if _should_request_pipeline_after_verification(node, ctx.artifacts):
                        evidenced_node = _node_with_verification_evidence(
                            node,
                            report,
                            artifacts=ctx.artifacts,
                        )
                        pipeline_node = _node_with_pipeline_request(evidenced_node, report)
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
                    repair_turn = accepted_node.metadata.get("current_repair_turn")
                    if isinstance(repair_turn, Mapping):
                        await self._emit_event(
                            errors,
                            workspace_id,
                            accepted_node,
                            "worker_repair_turn_completed",
                            {
                                "attempt_id": report.attempt_id,
                                "repair_turn": dict(repair_turn),
                                "summary": report.summary(),
                            },
                        )
                    nodes_done += 1
                elif _verification_feedback_obsoletes_node(report):
                    obsolete_node = _node_with_verification_feedback_disposition(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                        disposition="obsolete_node",
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(obsolete_node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                            summary=report.summary(),
                        )
                    )
                    await self._emit_event(
                        errors,
                        workspace_id,
                        obsolete_node,
                        "verification_feedback_disposition",
                        {
                            "attempt_id": report.attempt_id,
                            "disposition": "obsolete_node",
                            "feedback_items": feedback_items,
                            "summary": report.summary(),
                        },
                    )
                    nodes_done += 1
                elif _should_request_pipeline_from_report(node, report):
                    evidenced_node = _node_with_verification_evidence(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                    )
                    pipeline_node = _node_with_pipeline_request(evidenced_node, report)
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
                elif (
                    repair_alternative := _completed_repair_alternative_for_original_report(
                        plan, node, report
                    )
                ) is not None:
                    accepted_node = _node_with_repair_alternative_disposition(
                        node,
                        report,
                        repair_node=repair_alternative,
                        artifacts=ctx.artifacts,
                        disposition="accepted_via_repair_alternative",
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(accepted_node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                            summary=str(
                                accepted_node.metadata.get("last_verification_summary") or ""
                            ),
                        )
                    )
                    await self._emit_event(
                        errors,
                        workspace_id,
                        accepted_node,
                        "verification_feedback_disposition",
                        {
                            "attempt_id": report.attempt_id,
                            "disposition": "accepted_via_repair_alternative",
                            "repair_node_id": repair_alternative.id,
                            "feedback_items": feedback_items,
                            "summary": accepted_node.metadata.get("last_verification_summary"),
                        },
                    )
                    nodes_done += 1
                elif (
                    repair_alternative := _completed_repair_alternative_superseding_repair_node(
                        plan, node, report
                    )
                ) is not None:
                    superseded_node = _node_with_repair_alternative_disposition(
                        node,
                        report,
                        repair_node=repair_alternative,
                        artifacts=ctx.artifacts,
                        disposition="superseded_by_completed_repair_alternative",
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(superseded_node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                            summary=str(
                                superseded_node.metadata.get("last_verification_summary") or ""
                            ),
                        )
                    )
                    await self._emit_event(
                        errors,
                        workspace_id,
                        superseded_node,
                        "verification_feedback_disposition",
                        {
                            "attempt_id": report.attempt_id,
                            "disposition": "superseded_by_completed_repair_alternative",
                            "repair_node_id": repair_alternative.id,
                            "feedback_items": feedback_items,
                            "summary": superseded_node.metadata.get("last_verification_summary"),
                        },
                    )
                    nodes_done += 1
                elif _verification_feedback_disposes_sandbox_docker_runtime_node(node, report):
                    disposed_node = _node_with_verification_feedback_disposition(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                        disposition="sandbox_docker_runtime_unavailable",
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(disposed_node, TaskExecution.IDLE),
                            TaskIntent.DONE,
                            summary=report.summary(),
                        )
                    )
                    await self._emit_event(
                        errors,
                        workspace_id,
                        disposed_node,
                        "verification_feedback_disposition",
                        {
                            "attempt_id": report.attempt_id,
                            "disposition": "sandbox_docker_runtime_unavailable",
                            "feedback_items": feedback_items,
                            "summary": report.summary(),
                        },
                    )
                    nodes_done += 1
                elif _hard_fail_report_requests_infrastructure_repair(report):
                    evidenced_node = _node_with_retry_infrastructure_repair_request(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                    )
                    plan.replace_node(evidenced_node)
                    await self._planner.replan(
                        plan,
                        ReplanTrigger(
                            kind="verification_failed",
                            node_id=evidenced_node.id,
                            detail=report.summary(),
                        ),
                    )
                elif report.hard_fail:
                    failed_node = _node_with_verification_evidence(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                    )
                    plan.replace_node(
                        _force_intent(
                            _force_execution(failed_node, TaskExecution.IDLE),
                            TaskIntent.BLOCKED,
                            summary=report.summary(),
                        )
                    )
                    nodes_blocked += 1
                elif _is_verification_judge_retry_report(report):
                    retry_node = _node_with_verification_retry_backoff(node, report)
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
                            "retry_verification_only": True,
                        },
                    )
                elif _retryable_infrastructure_report_requests_repair(report):
                    evidenced_node = _node_with_retry_infrastructure_repair_request(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                    )
                    plan.replace_node(evidenced_node)
                    await self._planner.replan(
                        plan,
                        ReplanTrigger(
                            kind="verification_failed",
                            node_id=evidenced_node.id,
                            detail=report.summary(),
                        ),
                    )
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
                    evidenced_node = _node_with_verification_evidence(
                        node,
                        report,
                        artifacts=ctx.artifacts,
                    )
                    plan.replace_node(evidenced_node)
                    await self._planner.replan(
                        plan,
                        ReplanTrigger(
                            kind="verification_failed",
                            node_id=evidenced_node.id,
                            detail=report.summary(),
                        ),
                    )
            except Exception as exc:
                errors.append(f"verify({node.id}): {exc}")

        invalidated_dependents = _invalidate_nodes_with_unmet_dependencies(plan)
        for invalidated_node in invalidated_dependents:
            await self._emit_event(
                errors,
                workspace_id,
                invalidated_node,
                "dependency_invalidated",
                {
                    "summary": "node reset because one or more dependencies are not ready",
                    "missing_dependency_ids": invalidated_node.metadata.get(
                        "dependency_invalidated_missing_ids",
                        [],
                    ),
                    "previous_attempt_id": invalidated_node.metadata.get(
                        "dependency_invalidated_previous_attempt_id"
                    ),
                    "previous_intent": invalidated_node.metadata.get(
                        "dependency_invalidated_previous_intent"
                    ),
                    "previous_execution": invalidated_node.metadata.get(
                        "dependency_invalidated_previous_execution"
                    ),
                },
            )

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
        accepted_via_repair = _accept_ready_nodes_with_completed_repair_alternatives(plan)
        for accepted_node, repair_alternative in accepted_via_repair:
            await self._emit_event(
                errors,
                workspace_id,
                accepted_node,
                "verification_feedback_disposition",
                {
                    "attempt_id": accepted_node.current_attempt_id,
                    "disposition": "accepted_via_repair_alternative",
                    "repair_node_id": repair_alternative.id,
                    "feedback_items": [],
                    "summary": accepted_node.metadata.get("last_verification_summary"),
                },
            )
        nodes_done += len(accepted_via_repair)
        ready_candidates = _ready_nodes_due(plan.ready_nodes(), now=datetime.now(UTC))
        ready_candidates, deferred_by_dependency_projection = (
            _select_ready_nodes_with_integrated_dependencies(ready_candidates, plan)
        )
        for deferred_node in deferred_by_dependency_projection:
            await self._emit_event(
                errors,
                workspace_id,
                deferred_node,
                "dispatch_deferred_dependency_projection",
                {
                    "summary": "node deferred because one or more dependencies are not ready",
                    "missing_dependency_ids": _dependency_blocking_ids(plan, deferred_node),
                },
            )
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
        max_iterations = _max_iterations(loop_metadata)
        if self._iteration_reviewer is None and loop_metadata.get("mode") == "auto":
            suspended = _replace_goal_loop_metadata(
                plan,
                status=PlanStatus.SUSPENDED,
                updates={
                    "mode": "auto",
                    "current_iteration": _max_iteration(_runnable_nodes(plan)),
                    "max_iterations": max_iterations,
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
                    "max_iterations": max_iterations,
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
                    "max_iterations": max_iterations,
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
                    "last_review_findings": _iteration_review_findings_payload(verdict),
                    "last_review_rejected_finding_count": verdict.rejected_finding_count,
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
                    "last_review_findings": _iteration_review_findings_payload(verdict),
                    "last_review_rejected_finding_count": verdict.rejected_finding_count,
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


def _max_iterations(loop_metadata: Mapping[str, Any] | None = None) -> int:
    raw_value = os.getenv(_ITERATION_LOOP_MAX_ITERATIONS_ENV)
    if raw_value is None:
        configured = _ITERATION_LOOP_DEFAULT_MAX_ITERATIONS
    else:
        try:
            configured = int(raw_value)
        except ValueError:
            configured = _ITERATION_LOOP_DEFAULT_MAX_ITERATIONS
    metadata_limit = _positive_int((loop_metadata or {}).get("max_iterations"))
    if metadata_limit is None:
        return max(1, configured)
    return max(1, configured, metadata_limit)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


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
        iteration_loop=_iteration_loop_review_payload(plan.goal_node),
    )


def _iteration_loop_review_payload(goal_node: PlanNode) -> dict[str, object]:
    loop = _goal_iteration_loop_metadata(goal_node)
    payload: dict[str, object] = {}
    for key in (
        "mode",
        "loop_status",
        "current_iteration",
        "max_iterations",
        "operator_action",
        "current_sprint_goal",
        "next_sprint_goal",
        "last_review_summary",
        "last_review_confidence",
        "feedback_items",
    ):
        value = loop.get(key)
        if value is not None:
            payload[key] = value
    history = loop.get("history")
    if isinstance(history, list) and history:
        latest = history[-1]
        if isinstance(latest, Mapping):
            payload["latest_history"] = dict(latest)
    return payload


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


def _node_protocol_evidence_refs(node: PlanNode) -> list[str]:
    metadata = dict(node.metadata or {})
    refs: list[str] = []
    for key in (
        "verification_evidence_refs",
        "candidate_verifications",
        "last_worker_report_verifications",
        "execution_verifications",
    ):
        refs.extend(_string_list(metadata.get(key)))
    return list(dict.fromkeys(refs))


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
        "findings": _iteration_review_findings_payload(verdict),
        "rejected_finding_count": verdict.rejected_finding_count,
    }


def _iteration_review_findings_payload(
    verdict: IterationReviewVerdict,
) -> list[dict[str, Any]]:
    return [
        {
            "file": finding.file,
            "line": finding.line,
            "category": finding.category,
            "severity": finding.severity.value,
            "raw_confidence": finding.raw_confidence,
            "validated_confidence": finding.validated_confidence,
            "description": finding.description,
            "suggestion": finding.suggestion,
            "concrete_evidence": finding.concrete_evidence,
            "verdict": finding.verdict.value,
            "reasoning": finding.reasoning,
        }
        for finding in verdict.findings
    ]


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
    phase_by_task_id = {
        task.id: normalized_phases[sequence - 1]
        for sequence, task in enumerate(verdict.next_tasks, start=1)
        if task.id
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
            and _phase_index(phase_by_task_id.get(dep, _ITERATION_PHASES[0])) <= _phase_index(phase)
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
            "last_review_findings": _iteration_review_findings_payload(verdict),
            "last_review_rejected_finding_count": verdict.rejected_finding_count,
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
    return [
        _next_iteration_task_phase(task, sequence) for sequence, task in enumerate(tasks, start=1)
    ]


def _normalized_pending_iteration_phases(nodes: list[PlanNode]) -> dict[PlanNodeId, str]:
    ordered = _ordered_iteration_nodes(nodes)
    return {node.node_id: _node_iteration_phase(node) for node in ordered}


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
            repair_dependency = _repair_blocking_dependency_id(node)
            if repair_dependency is not None and repair_dependency != node.node_id:
                desired_dependencies.add(repair_dependency)
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


def _invalidate_nodes_with_unmet_dependencies(plan: Plan) -> list[PlanNode]:
    """Reset already-active downstream nodes when a dependency regresses.

    ``Plan.ready_nodes()`` prevents future dispatch before dependencies are done, but a
    dependency can later regress when terminal attempt reconciliation rejects a previously
    projected success. Any already-running or already-done downstream node is then stale
    and must not keep accepting reports from its old attempt.
    """

    now = datetime.now(UTC)
    invalidated: list[PlanNode] = []
    for node in list(plan.nodes.values()):
        if node.kind not in {PlanNodeKind.TASK, PlanNodeKind.VERIFY} or not node.depends_on:
            continue
        missing = tuple(_dependency_blocking_ids(plan, node))
        if not missing:
            continue
        if (
            node.intent is TaskIntent.TODO
            and node.execution is TaskExecution.IDLE
            and not node.current_attempt_id
        ):
            continue
        metadata = _clear_stale_attempt_metadata(node.metadata)
        metadata.update(
            {
                "dependency_invalidated_at": now.isoformat().replace("+00:00", "Z"),
                "dependency_invalidated_missing_ids": list(missing),
                "dependency_invalidated_reason": "dependencies_not_done_or_not_integrated",
                "dependency_invalidated_previous_attempt_id": node.current_attempt_id,
                "dependency_invalidated_previous_intent": node.intent.value,
                "dependency_invalidated_previous_execution": node.execution.value,
            }
        )
        updated = replace(
            node,
            intent=TaskIntent.TODO,
            execution=TaskExecution.IDLE,
            assignee_agent_id=None,
            current_attempt_id=None,
            feature_checkpoint=_reset_stale_feature_checkpoint(node.feature_checkpoint),
            metadata=metadata,
            updated_at=now,
            completed_at=None,
        )
        plan.replace_node(updated)
        invalidated.append(updated)
    return invalidated


def _select_ready_nodes_with_integrated_dependencies(
    ready_nodes: list[PlanNode],
    plan: Plan,
) -> tuple[list[PlanNode], list[PlanNode]]:
    ready: list[PlanNode] = []
    deferred: list[PlanNode] = []
    for node in ready_nodes:
        if _dependency_blocking_ids(plan, node):
            deferred.append(node)
        else:
            ready.append(node)
    return ready, deferred


def _reopen_done_nodes_with_failed_pipeline(plan: Plan) -> list[PlanNode]:
    reopened: list[PlanNode] = []
    now = datetime.now(UTC)
    for node in list(plan.nodes.values()):
        if node.intent is not TaskIntent.DONE or node.execution is not TaskExecution.IDLE:
            continue
        if not _node_requires_pipeline_gate(node):
            continue
        if _pipeline_gate_status(node) != "failed":
            continue
        metadata = dict(node.metadata or {})
        metadata["pipeline_failed_done_reopened_at"] = now.isoformat().replace("+00:00", "Z")
        metadata["last_verification_passed"] = False
        metadata["last_verification_summary"] = str(
            metadata.get("pipeline_last_summary") or "required pipeline failed after verification"
        )
        updated = replace(
            node,
            intent=TaskIntent.IN_PROGRESS,
            execution=TaskExecution.REPORTED,
            metadata=metadata,
            updated_at=now,
            completed_at=None,
        )
        plan.replace_node(updated)
        reopened.append(updated)
    return reopened


_SUCCESSFUL_WORKTREE_INTEGRATION_STATUSES = frozenset({"merged", "already_merged", "skipped"})


def _dependency_blocking_ids(plan: Plan, node: PlanNode) -> list[str]:
    blocking: list[str] = []
    dependency_ids = set(node.depends_on)
    repair_dependency = _repair_blocking_dependency_id(node)
    if repair_dependency is not None:
        dependency_ids.add(repair_dependency)
    for dep_id in sorted(dependency_ids, key=lambda item: item.value):
        dependency = plan.nodes.get(dep_id)
        if dependency is None or dependency.intent is not TaskIntent.DONE:
            blocking.append(dep_id.value)
            continue
        if _dependency_commit_needs_integration(dependency):
            blocking.append(dep_id.value)
    return blocking


def _repair_blocking_dependency_id(node: PlanNode) -> PlanNodeId | None:
    repair_id = dict(node.metadata or {}).get("blocked_by_repair_node_id")
    if isinstance(repair_id, str) and repair_id.strip():
        return PlanNodeId(repair_id.strip())
    return None


def _dependency_commit_needs_integration(node: PlanNode) -> bool:
    commit_ref = _node_verified_commit_ref(node)
    if not commit_ref:
        return False
    worktree_path = _node_attempt_worktree_path(node)
    if not _looks_like_attempt_worktree(worktree_path):
        return False
    status = _metadata_text(node.metadata.get("worktree_integration_status"))
    if (
        status == "failed"
        and node.metadata.get("terminal_attempt_status") == "accepted"
        and node.metadata.get("worktree_integration_dirty_signature") is None
        and "commit_ref not found in attempt worktree"
        in _metadata_text(node.metadata.get("worktree_integration_summary")).lower()
    ):
        return False
    if _node_pipeline_published_commit(node, commit_ref=commit_ref):
        return False
    return status not in _SUCCESSFUL_WORKTREE_INTEGRATION_STATUSES


def _node_pipeline_published_commit(node: PlanNode, *, commit_ref: str) -> bool:
    metadata = dict(node.metadata or {})
    if _pipeline_gate_status(node) != "success":
        return False
    if _metadata_text(metadata.get("source_publish_status")) != "published":
        return False
    published_commit = _metadata_text(metadata.get("source_publish_commit_ref"))
    return _commit_refs_match(published_commit, commit_ref)


def _commit_refs_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left = left.strip()
    right = right.strip()
    if left == right:
        return True
    if min(len(left), len(right)) < 7:
        return False
    return left.startswith(right) or right.startswith(left)


def _node_verified_commit_ref(node: PlanNode) -> str | None:
    metadata = dict(node.metadata or {})
    commit_ref = _metadata_text(metadata.get("verified_commit_ref")) or _metadata_text(
        metadata.get("worktree_integration_commit_ref")
    )
    if commit_ref:
        return commit_ref
    if node.feature_checkpoint is not None:
        return _metadata_text(node.feature_checkpoint.commit_ref)
    return None


def _node_attempt_worktree_path(node: PlanNode) -> str | None:
    metadata = dict(node.metadata or {})
    worktree_path = (
        _metadata_text(metadata.get("worktree_integration_worktree_path"))
        or _metadata_text(metadata.get("active_execution_root"))
        or _metadata_text(metadata.get("worktree_path"))
    )
    if worktree_path:
        return worktree_path
    if node.feature_checkpoint is not None:
        return _metadata_text(node.feature_checkpoint.worktree_path)
    return None


def _looks_like_attempt_worktree(path: str | None) -> bool:
    return bool(path and "/.memstack/worktrees/" in path)


def _metadata_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


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
        "candidate_artifacts",
        "candidate_verifications",
        "deploy_mode",
        "deployment_status",
        "evidence_refs",
        "execution_verifications",
        "external_id",
        "external_provider",
        "external_url",
        "last_verification_summary",
        "last_verification_passed",
        "last_verification_hard_fail",
        "last_verification_attempt_id",
        "last_verification_ran_at",
        "last_verification_judge_confidence",
        "last_verification_judge_failed_criteria",
        "last_verification_judge_next_action_kind",
        "last_verification_judge_rationale",
        "last_verification_judge_repair_brief",
        "last_verification_judge_required_next_action",
        "last_verification_judge_verdict",
        "last_verification_feedback_items",
        "last_worker_report_attempt_id",
        "last_worker_report_artifacts",
        "last_worker_report_summary",
        "last_worker_report_type",
        "last_worker_report_verifications",
        "verification_feedback_disposition",
        "obsolete_by_verifier_feedback",
        "obsolete_feedback_items",
        "current_repair_turn",
        "pipeline_finished_at",
        "pipeline_request_count",
        "pipeline_requested_at",
        "verification_evidence_refs",
        "verified_commit_ref",
        "verified_git_diff_summary",
        "verified_test_commands",
        "reported_attempt_reconciled_at",
        "reported_attempt_status",
        "retry_last_reason",
        "source_publish_branch",
        "source_publish_commit_ref",
        "source_publish_provider",
        "source_publish_reason",
        "source_publish_source_commit_ref",
        "source_publish_status",
        "source_publish_token_env",
        "terminal_attempt_status",
        "terminal_attempt_reconciled_at",
        "terminal_attempt_superseded_attempt_id",
        "terminal_attempt_superseded_reason",
        "terminal_attempt_superseded_status",
        "pipeline_status",
        "pipeline_gate_status",
        "pipeline_run_id",
        "pipeline_evidence_refs",
        "pipeline_last_summary",
        "worktree_integration_attempt_id",
        "worktree_integration_commit_ref",
        "worktree_integration_dirty_signature",
        "worktree_integration_ran_at",
        "worktree_integration_status",
        "worktree_integration_summary",
        "worktree_integration_worktree_path",
    }
)


def _clear_stale_attempt_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = dict(metadata)
    for key in _STALE_ATTEMPT_METADATA_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _reset_stale_feature_checkpoint(
    feature_checkpoint: FeatureCheckpoint | None,
) -> FeatureCheckpoint | None:
    if feature_checkpoint is None:
        return None
    return replace(
        feature_checkpoint,
        worktree_path=None,
        branch_name=None,
        base_ref="HEAD",
        commit_ref=None,
    )


def _node_dispatched_with_fresh_attempt(
    node: PlanNode,
    *,
    assignee_agent_id: str,
    attempt_id: str,
) -> PlanNode:
    metadata = _clear_stale_attempt_metadata(node.metadata)
    repair_turn = node.metadata.get("current_repair_turn")
    if isinstance(repair_turn, Mapping) and repair_turn.get("attempt_id") == attempt_id:
        metadata["current_repair_turn"] = dict(repair_turn)
        repair_count = node.metadata.get("same_conversation_repair_turn_count")
        if isinstance(repair_count, int) and repair_count > 0:
            metadata["same_conversation_repair_turn_count"] = repair_count
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


def _is_verification_judge_retry_report(report: VerificationReport) -> bool:
    for result in report.results:
        if not result.criterion.required or result.passed:
            continue
        if result.criterion.spec.get("name") != _RETRYABLE_INFRASTRUCTURE_CRITERION:
            continue
        if result.criterion.spec.get("judge_verdict") != "retry_infrastructure":
            continue
        next_action_kind = str(result.criterion.spec.get("next_action_kind") or "")
        failed = set(_string_list(result.criterion.spec.get("failed_criteria")))
        if next_action_kind == "retry_same_node" and "workspace_verification_judge" in failed:
            return True
    return False


def _retryable_infrastructure_report_requests_repair(report: VerificationReport) -> bool:
    for result in report.results:
        if not result.criterion.required or result.passed:
            continue
        if result.criterion.spec.get("name") != _RETRYABLE_INFRASTRUCTURE_CRITERION:
            continue
        if result.criterion.spec.get("judge_verdict") != "retry_infrastructure":
            continue
        if result.criterion.spec.get("next_action_kind") == "create_repair_node":
            return True
        if _is_nontransient_sandbox_docker_runtime_failure(result):
            return True
    return False


def _hard_fail_report_requests_infrastructure_repair(report: VerificationReport) -> bool:
    if not report.hard_fail:
        return False
    return _report_has_nontransient_sandbox_docker_runtime_failure(report)


def _report_has_nontransient_sandbox_docker_runtime_failure(report: VerificationReport) -> bool:
    return any(
        result.criterion.required
        and not result.passed
        and _is_nontransient_sandbox_docker_runtime_failure(result)
        for result in report.results
    )


def _is_nontransient_sandbox_docker_runtime_failure(result: CriterionResult) -> bool:
    markers: list[object] = [
        result.message,
        result.criterion.spec.get("required_next_action"),
        result.criterion.spec.get("failure_signature"),
        result.criterion.spec.get("summary"),
        result.criterion.spec.get("rationale"),
    ]
    markers.extend(_string_list(result.criterion.spec.get("failed_criteria")))
    feedback_items = result.criterion.spec.get("feedback_items")
    if isinstance(feedback_items, list):
        for item in feedback_items:
            if not isinstance(item, Mapping):
                continue
            markers.extend(
                [
                    item.get("failure_signature"),
                    item.get("summary"),
                    item.get("recommended_action"),
                ]
            )
            markers.extend(_string_list(item.get("evidence_refs")))
    normalized = "\n".join(str(marker).lower() for marker in markers if marker)
    if "sandbox-no-docker-runtime" in normalized:
        return True
    docker_runtime_missing = "docker runtime" in normalized and any(
        token in normalized
        for token in (
            "not available",
            "unavailable",
            "absent",
            "no socket",
            "without docker",
            "lacks docker",
            "docker cli absent",
        )
    )
    return docker_runtime_missing and "sandbox" in normalized


def _completed_repair_alternative_for_original_report(
    plan: Plan,
    node: PlanNode,
    report: VerificationReport,
) -> PlanNode | None:
    if not _report_has_nontransient_sandbox_docker_runtime_failure(report):
        return None
    return _completed_repair_alternative_for_node(plan, node, exclude_node_id=node.id)


def _completed_repair_alternative_superseding_repair_node(
    plan: Plan,
    node: PlanNode,
    report: VerificationReport,
) -> PlanNode | None:
    if not _report_has_nontransient_sandbox_docker_runtime_failure(report):
        return None
    original_node_id = dict(node.metadata or {}).get("repair_for_node_id")
    if not isinstance(original_node_id, str) or not original_node_id.strip():
        return None
    original = plan.nodes.get(PlanNodeId(original_node_id.strip()))
    if original is None:
        return None
    return _completed_repair_alternative_for_node(plan, original, exclude_node_id=node.id)


def _completed_repair_alternative_superseding_reported_repair(
    plan: Plan,
    node: PlanNode,
) -> PlanNode | None:
    if node.intent is not TaskIntent.IN_PROGRESS or node.execution is not TaskExecution.REPORTED:
        return None
    original_node_id = dict(node.metadata or {}).get("repair_for_node_id")
    if not isinstance(original_node_id, str) or not original_node_id.strip():
        return None
    original = plan.nodes.get(PlanNodeId(original_node_id.strip()))
    if original is None:
        return None
    return _completed_repair_alternative_for_node(plan, original, exclude_node_id=node.id)


def _accept_ready_nodes_with_completed_repair_alternatives(
    plan: Plan,
) -> list[tuple[PlanNode, PlanNode]]:
    accepted: list[tuple[PlanNode, PlanNode]] = []
    for node in list(plan.nodes.values()):
        if node.kind not in {PlanNodeKind.TASK, PlanNodeKind.VERIFY}:
            continue
        if node.intent is not TaskIntent.TODO or node.execution is not TaskExecution.IDLE:
            continue
        if node.current_attempt_id:
            continue
        if _dependency_blocking_ids(plan, node):
            continue
        repair_alternative = _completed_repair_alternative_for_node(
            plan,
            node,
            exclude_node_id=node.id,
        )
        if repair_alternative is None:
            continue
        accepted_node = _node_with_repair_alternative_disposition_from_metadata(
            node,
            repair_node=repair_alternative,
            disposition="accepted_via_repair_alternative",
        )
        plan.replace_node(
            _force_intent(
                _force_execution(accepted_node, TaskExecution.IDLE),
                TaskIntent.DONE,
                summary=str(accepted_node.metadata.get("last_verification_summary") or ""),
            )
        )
        accepted.append((accepted_node, repair_alternative))
    return accepted


def _completed_repair_alternative_for_node(
    plan: Plan,
    node: PlanNode,
    *,
    exclude_node_id: str,
) -> PlanNode | None:
    for candidate in sorted(plan.nodes.values(), key=lambda item: item.id):
        if candidate.id == exclude_node_id:
            continue
        if candidate.metadata.get("repair_for_node_id") != node.id:
            continue
        if candidate.intent is not TaskIntent.DONE:
            continue
        if candidate.metadata.get("last_verification_passed") is not True:
            continue
        if _repair_alternative_evidence_is_sufficient(candidate):
            if not _repair_alternative_pipeline_gate_is_satisfied(
                original=node,
                repair=candidate,
            ):
                continue
            return candidate
    return None


def _repair_alternative_pipeline_gate_is_satisfied(
    *,
    original: PlanNode,
    repair: PlanNode,
) -> bool:
    if not _node_requires_pipeline_gate(original):
        return True

    repair_refs = _node_protocol_evidence_refs(repair)
    if "ci_pipeline:passed" in repair_refs or any(
        ref.startswith("pipeline_run:success:") for ref in repair_refs
    ):
        return True

    repair_commit = _first_prefixed_value(repair_refs, "commit_ref:")
    if not repair_commit:
        repair_commit = _first_prefixed_value(_node_artifacts(repair), "commit_ref:")
    if not repair_commit:
        return False

    if _pipeline_gate_status(original) != "success":
        return False
    metadata = dict(original.metadata or {})
    published_commit = _metadata_text(metadata.get("source_publish_commit_ref"))
    return _commit_refs_match(published_commit, repair_commit)


def _repair_alternative_evidence_is_sufficient(node: PlanNode) -> bool:
    if _verified_judge_repair_evidence_is_sufficient(node):
        return True

    refs = _node_protocol_evidence_refs(node)
    has_disposition = any(
        ref.startswith("contract_disposition:repair_node")
        or ref.startswith("contract_disposition:infrastructure_limitation")
        for ref in refs
    )
    has_registry = any(
        ref.startswith("docker_registry_reachability:")
        or ref.startswith("registry_verify:")
        or ref.startswith("pipeline_run:success:")
        for ref in refs
    )
    has_service_substitute = any(
        ref.startswith("health_check:")
        or ref.startswith("server:")
        or ref.startswith("pipeline_run:success:")
        for ref in refs
    )
    return has_disposition and has_registry and has_service_substitute


def _verified_judge_repair_evidence_is_sufficient(node: PlanNode) -> bool:
    metadata = dict(node.metadata or {})
    if metadata.get("repair_source") != "verification_judge_create_repair_node":
        return False
    if metadata.get("source_verification_judge_next_action_kind") != "create_repair_node":
        return False
    if metadata.get("last_verification_judge_verdict") != "accepted":
        return False

    refs = _node_protocol_evidence_refs(node)
    has_checkpoint = any(
        ref.startswith("commit_ref:") or ref.startswith("git_diff_summary:") for ref in refs
    )
    has_terminal_report = any(
        ref == "accepted" or ref.startswith("worker_report:completed") for ref in refs
    )
    has_verification = any(
        ref.startswith("test_run:")
        or ref.startswith("preflight:")
        or ref.startswith("pipeline_run:success:")
        for ref in refs
    )
    return has_checkpoint and has_terminal_report and has_verification


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
    failed_required = report.failed_required
    if not failed_required:
        return _node_requires_pipeline_gate(node)
    pipeline_failures = [
        result for result in failed_required if result.criterion.kind in _PIPELINE_CRITERION_KINDS
    ]
    if not pipeline_failures:
        return False
    non_pipeline_failures = [
        result
        for result in failed_required
        if result.criterion.kind not in _PIPELINE_CRITERION_KINDS
    ]
    pipeline_missing_evidence = _pipeline_failures_are_missing_evidence(pipeline_failures)
    pipeline_runtime_retryable = _pipeline_failures_are_runtime_retryable(pipeline_failures)
    pipeline_can_request_run = pipeline_missing_evidence or pipeline_runtime_retryable
    return all(
        _is_pipeline_only_judge_failure(result)
        or _is_pipeline_trigger_infrastructure_failure(result)
        or (pipeline_can_request_run and _is_verification_judge_inconclusive_failure(result))
        for result in non_pipeline_failures
    )


def _pipeline_failures_are_missing_evidence(results: list[CriterionResult]) -> bool:
    return any(
        "missing harness-native ci pipeline evidence" in str(result.message or "").lower()
        or "missing preview deployment health evidence" in str(result.message or "").lower()
        for result in results
    )


def _pipeline_failures_are_runtime_retryable(results: list[CriterionResult]) -> bool:
    return any(
        _is_pipeline_runtime_retry_marker(result.message)
        or any(
            _is_pipeline_runtime_retry_marker(evidence.ref)
            or _is_pipeline_runtime_retry_marker(evidence.note)
            for evidence in result.evidence
        )
        for result in results
    )


def _is_pipeline_runtime_retry_marker(value: object) -> bool:
    marker = value.strip().lower() if isinstance(value, str) else ""
    return bool(marker) and any(
        token in marker
        for token in (
            "source_publish",
            "drone_api",
            "all connection attempts failed",
            "failed to connect",
            "couldn't connect",
            "connection reset",
            "connection refused",
            "temporarily unavailable",
            "rate limit",
            "tls handshake timeout",
            "i/o timeout",
            "context deadline exceeded",
            "registry-1.docker.io",
            "docker.io/v2/",
        )
    )


def _is_verification_judge_inconclusive_failure(result: CriterionResult) -> bool:
    if result.criterion.kind is not CriterionKind.CUSTOM:
        return False
    spec = result.criterion.spec
    if spec.get("name") != _RETRYABLE_INFRASTRUCTURE_CRITERION:
        return False
    if spec.get("judge_verdict") != "retry_infrastructure":
        return False
    failed = set(_string_list(spec.get("failed_criteria")))
    if "workspace_verification_judge" in failed:
        return True
    feedback_items = spec.get("feedback_items")
    if not isinstance(feedback_items, list):
        return False
    return any(
        isinstance(item, Mapping)
        and item.get("failure_signature") == "workspace_verification_judge_failed"
        for item in feedback_items
    )


def _is_pipeline_only_judge_failure(result: CriterionResult) -> bool:
    spec = result.criterion.spec
    if result.criterion.kind is not CriterionKind.CUSTOM:
        return False
    if spec.get("name") != "workspace_verification_judge":
        return False
    failed = set(_string_list(spec.get("failed_criteria")))
    feedback_items = spec.get("feedback_items")
    failed_is_pipeline_only = bool(failed) and all(
        _is_pipeline_failure_marker(item) for item in failed
    )
    if not isinstance(feedback_items, list) or not feedback_items:
        return failed_is_pipeline_only
    if _feedback_items_require_worker_retry(feedback_items):
        return False
    feedback_signatures = [
        item.get("failure_signature") for item in feedback_items if isinstance(item, Mapping)
    ]
    feedback_items_are_pipeline_evidence_gaps = all(
        isinstance(item, Mapping) and _feedback_item_is_pipeline_evidence_gap(item)
        for item in feedback_items
    )
    if not feedback_signatures:
        return failed_is_pipeline_only
    feedback_signatures_match = feedback_items_are_pipeline_evidence_gaps or all(
        _is_pipeline_failure_marker(item) for item in feedback_signatures
    )
    return feedback_signatures_match and (not failed or failed_is_pipeline_only)


def _feedback_items_require_worker_retry(feedback_items: list[object]) -> bool:
    has_worker_retry = False
    has_stale_or_obsolete_disposition = False
    for item in feedback_items:
        if not isinstance(item, Mapping):
            continue
        if _feedback_item_is_pipeline_evidence_gap(item):
            continue
        target_layer = str(item.get("target_layer") or "").strip().lower()
        feedback_kind = str(item.get("feedback_kind") or "").strip().lower()
        recommended_action = str(item.get("recommended_action") or "").strip().lower()
        if (
            target_layer == "worker"
            or feedback_kind == "product_code_failure"
            or recommended_action == "retry_worker"
        ):
            has_worker_retry = True
        if feedback_kind == "stale_or_invalid_task_target" or recommended_action == "obsolete_node":
            has_stale_or_obsolete_disposition = True
    return has_worker_retry and not has_stale_or_obsolete_disposition


def _feedback_item_is_pipeline_evidence_gap(item: Mapping[str, object]) -> bool:
    markers = [
        item.get("feedback_kind"),
        item.get("recommended_action"),
        item.get("summary"),
        item.get("failure_signature"),
    ]
    markers.extend(_string_list(item.get("evidence_refs")))
    normalized = "\n".join(str(marker).lower() for marker in markers if marker)
    if not any(
        token in normalized
        for token in (
            "evidence",
            "not triggered",
            "not yet on main",
            "publish",
            "trigger",
            "worktree commit",
        )
    ):
        return False
    if not any(_is_pipeline_failure_marker(marker) for marker in markers):
        return False
    return any(
        token in normalized
        for token in (
            "missing",
            "not captured",
            "not found",
            "required",
            "not triggered",
            "not yet on main",
            "publish",
            "trigger",
        )
    )


def _is_pipeline_trigger_infrastructure_failure(result: CriterionResult) -> bool:
    spec = result.criterion.spec
    if result.criterion.kind is not CriterionKind.CUSTOM:
        return False
    if spec.get("name") != _RETRYABLE_INFRASTRUCTURE_CRITERION:
        return False
    if spec.get("judge_verdict") != "retry_infrastructure":
        return False

    markers: list[object] = [
        result.message,
        spec.get("required_next_action"),
        spec.get("next_action_kind"),
        spec.get("failure_signature"),
        spec.get("summary"),
        spec.get("rationale"),
    ]
    markers.extend(_string_list(spec.get("failed_criteria")))

    feedback_items = spec.get("feedback_items")
    if isinstance(feedback_items, list):
        for item in feedback_items:
            if not isinstance(item, Mapping):
                continue
            markers.extend(
                [
                    item.get("target_layer"),
                    item.get("feedback_kind"),
                    item.get("recommended_action"),
                    item.get("summary"),
                    item.get("failure_signature"),
                ]
            )
            markers.extend(_string_list(item.get("evidence_refs")))

    for evidence in result.evidence:
        markers.extend([evidence.kind, evidence.ref, evidence.note])

    return any(_is_pipeline_failure_marker(marker) for marker in markers)


def _is_pipeline_failure_marker(value: object) -> bool:
    marker = value.strip().lower() if isinstance(value, str) else ""
    return bool(marker) and (
        marker.startswith("ci_pipeline")
        or marker.startswith("ci_")
        or marker.startswith("ci-")
        or marker.startswith("pipeline_")
        or marker.startswith("pipeline-")
        or marker.startswith("missing_ci_evidence")
        or marker.startswith("missing_drone_pipeline")
        or marker.startswith("harness_native_cicd")
        or marker.startswith("harness-native-cicd")
        or "ci_pipeline" in marker
        or "ci-pipeline" in marker
        or "ci pipeline" in marker
        or "ci/cd" in marker
        or "drone" in marker
        or "harness-native ci" in marker
        or "harness-native-ci" in marker
    )


def _node_requires_pipeline_gate(node: PlanNode) -> bool:
    if node.kind is PlanNodeKind.GOAL:
        return False
    raw_required = node.metadata.get("pipeline_required")
    if isinstance(raw_required, bool):
        return raw_required
    return False


def _node_has_pipeline_success(node: PlanNode, artifacts: Mapping[str, Any]) -> bool:
    artifact_status = artifacts.get("pipeline_status")
    if isinstance(artifact_status, str) and artifact_status.strip().lower() not in {
        "",
        "success",
    }:
        return False

    artifact_pipeline_status, _ = _pipeline_status_from_refs(
        _pipeline_refs_for_verification([], artifacts)
    )
    if artifact_pipeline_status == "failed":
        return False

    if _pipeline_gate_status(node) != "success":
        return False

    candidate_refs = _artifact_evidence_refs(artifacts)
    candidate_commit = _first_prefixed_value(candidate_refs, "commit_ref:")
    if not candidate_commit:
        candidate_commit = _metadata_text(node.metadata.get("verified_commit_ref"))
    published_commit = _metadata_text(node.metadata.get("source_publish_commit_ref"))
    return not (
        candidate_commit
        and published_commit
        and not _commit_refs_match(published_commit, candidate_commit)
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


def _node_with_verification_retry_backoff(
    node: PlanNode,
    report: VerificationReport,
) -> PlanNode:
    evidenced = _node_with_verification_evidence(node, report)
    metadata = dict(evidenced.metadata)
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
        evidenced,
        intent=TaskIntent.IN_PROGRESS,
        execution=TaskExecution.REPORTED,
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
        "retryable_infrastructure": _is_retryable_infrastructure_report(report),
        "retry_verification_only": _is_verification_judge_retry_report(report),
        "summary": report.summary(),
        "ran_at": report.ran_at.isoformat().replace("+00:00", "Z"),
        "results": [
            {
                "kind": result.criterion.kind.value,
                "name": result.criterion.spec.get("name"),
                "judge_verdict": result.criterion.spec.get("judge_verdict"),
                "next_action_kind": result.criterion.spec.get("next_action_kind"),
                "required_next_action": result.criterion.spec.get("required_next_action"),
                "feedback_items": result.criterion.spec.get("feedback_items") or [],
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


def _verification_feedback_items(report: VerificationReport) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for result in report.results:
        raw_items = result.criterion.spec.get("feedback_items")
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                continue
            payload = {
                "target_layer": _feedback_string(raw.get("target_layer")),
                "feedback_kind": _feedback_string(raw.get("feedback_kind")),
                "severity": _feedback_string(raw.get("severity")),
                "recommended_action": _feedback_string(raw.get("recommended_action")),
                "summary": _feedback_string(raw.get("summary")),
                "failure_signature": _feedback_string(raw.get("failure_signature")),
                "evidence_refs": _string_list(raw.get("evidence_refs")),
            }
            payload = {key: value for key, value in payload.items() if value not in ("", [])}
            if {"target_layer", "feedback_kind", "recommended_action"} <= set(payload):
                items.append(payload)
    return items


def _feedback_string(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _verification_feedback_counts(feedback_items: list[dict[str, Any]]) -> dict[str, int]:
    counter: dict[str, int] = {}
    for item in feedback_items:
        for key, prefix in (
            ("target_layer", "layer"),
            ("feedback_kind", "kind"),
            ("recommended_action", "action"),
            ("severity", "severity"),
        ):
            value = item.get(key)
            if isinstance(value, str) and value:
                counter[f"{prefix}:{value}"] = counter.get(f"{prefix}:{value}", 0) + 1
    return counter


def _verification_feedback_obsoletes_node(report: VerificationReport) -> bool:
    items = _verification_feedback_items(report)
    has_obsolete_action = False
    for item in items:
        if item.get("recommended_action") != "obsolete_node":
            continue
        if item.get("target_layer") in {"planner", "reviewer"}:
            has_obsolete_action = True
            break
    if not has_obsolete_action:
        return False

    return not any(
        item.get("recommended_action") != "obsolete_node"
        and item.get("severity") in {"blocking", "critical"}
        for item in items
    )


def _verification_feedback_disposes_sandbox_docker_runtime_node(
    node: PlanNode,
    report: VerificationReport,
) -> bool:
    if _node_iteration_index(node) <= 1:
        return False
    if not _report_has_nontransient_sandbox_docker_runtime_failure(report):
        return False
    for result in report.results:
        if result.criterion.spec.get("judge_verdict") == "blocked_human_required":
            return True
        if result.criterion.spec.get("next_action_kind") == "human_required":
            return True
    return any(
        item.get("recommended_action") in {"escalate_human", "accept_with_disposition"}
        for item in _verification_feedback_items(report)
    )


def _node_with_verification_evidence(
    node: PlanNode,
    report: VerificationReport,
    *,
    artifacts: Mapping[str, Any] | None = None,
) -> PlanNode:
    refs = list(
        dict.fromkeys([*_report_evidence_refs(report), *_artifact_evidence_refs(artifacts)])
    )
    commit_ref = _last_prefixed_value(refs, "commit_ref:")
    git_diff_summary = _last_prefixed_value(refs, "git_diff_summary:")
    test_commands = tuple(
        dict.fromkeys(ref.removeprefix("test_run:") for ref in refs if ref.startswith("test_run:"))
    )
    metadata = dict(node.metadata)
    metadata["last_verification_summary"] = report.summary()
    metadata["last_verification_passed"] = report.passed
    metadata["last_verification_hard_fail"] = report.hard_fail
    metadata["last_verification_ran_at"] = report.ran_at.isoformat().replace("+00:00", "Z")
    metadata.update(_judge_result_metadata(report))
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


def _node_with_retry_infrastructure_repair_request(
    node: PlanNode,
    report: VerificationReport,
    *,
    artifacts: Mapping[str, Any] | None = None,
) -> PlanNode:
    evidenced = _node_with_verification_evidence(node, report, artifacts=artifacts)
    metadata = dict(evidenced.metadata)
    metadata["last_verification_judge_next_action_kind"] = "create_repair_node"
    if not metadata.get("last_verification_judge_required_next_action"):
        metadata["last_verification_judge_required_next_action"] = (
            "Revise the node so it can be verified with available infrastructure, "
            "or route it to a runtime that has the required Docker capability."
        )
    return replace(evidenced, metadata=metadata, updated_at=datetime.now(UTC))


def _node_with_verification_feedback_disposition(
    node: PlanNode,
    report: VerificationReport,
    *,
    artifacts: Mapping[str, Any] | None = None,
    disposition: str,
) -> PlanNode:
    evidenced = _node_with_verification_evidence(node, report, artifacts=artifacts)
    metadata = dict(evidenced.metadata)
    metadata["verification_feedback_disposition"] = disposition
    metadata["obsolete_by_verifier_feedback"] = disposition == "obsolete_node"
    metadata["obsolete_feedback_items"] = _verification_feedback_items(report)
    return replace(evidenced, metadata=metadata, updated_at=datetime.now(UTC))


def _node_with_repair_alternative_disposition(
    node: PlanNode,
    report: VerificationReport,
    *,
    repair_node: PlanNode,
    artifacts: Mapping[str, Any] | None = None,
    disposition: str,
) -> PlanNode:
    evidenced = _node_with_verification_evidence(node, report, artifacts=artifacts)
    repair_summary = _node_verification_summary(repair_node) or "completed repair alternative"
    summary = (
        f"{disposition}: {repair_node.id} supplied accepted Docker-runtime substitute "
        f"evidence. {repair_summary}"
    )
    metadata = dict(evidenced.metadata)
    metadata.update(
        {
            "last_verification_passed": True,
            "last_verification_hard_fail": False,
            "last_verification_summary": summary,
            "last_verification_judge_next_action_kind": "none",
            "verification_feedback_disposition": disposition,
            "accepted_repair_node_id": repair_node.id,
            "accepted_repair_evidence_refs": _node_protocol_evidence_refs(repair_node)[:24],
        }
    )
    metadata.pop("retry_not_before", None)
    metadata.pop("retry_last_reason", None)
    return replace(evidenced, metadata=metadata, updated_at=datetime.now(UTC))


def _node_with_repair_alternative_disposition_from_metadata(
    node: PlanNode,
    *,
    repair_node: PlanNode,
    disposition: str,
) -> PlanNode:
    repair_summary = _node_verification_summary(repair_node) or "completed repair alternative"
    summary = (
        f"{disposition}: {repair_node.id} supplied accepted Docker-runtime substitute "
        f"evidence. {repair_summary}"
    )
    metadata = dict(node.metadata)
    metadata.update(
        {
            "last_verification_passed": True,
            "last_verification_hard_fail": False,
            "last_verification_summary": summary,
            "last_verification_judge_next_action_kind": "none",
            "verification_feedback_disposition": disposition,
            "accepted_repair_node_id": repair_node.id,
            "accepted_repair_evidence_refs": _node_protocol_evidence_refs(repair_node)[:24],
        }
    )
    metadata.pop("retry_not_before", None)
    metadata.pop("retry_last_reason", None)
    return replace(
        node,
        assignee_agent_id=None,
        current_attempt_id=None,
        metadata=metadata,
        updated_at=datetime.now(UTC),
    )


def _report_evidence_refs(report: VerificationReport) -> list[str]:
    refs: list[str] = []
    for result in report.results:
        refs.extend(evidence.ref for evidence in result.evidence if evidence.ref)
    return list(dict.fromkeys(refs))


def _artifact_evidence_refs(artifacts: Mapping[str, Any] | None) -> list[str]:
    if not artifacts:
        return []
    refs: list[str] = []
    for key in (
        "candidate_artifacts",
        "last_worker_report_artifacts",
        "execution_artifacts",
        "evidence_refs",
        "candidate_verifications",
        "last_worker_report_verifications",
        "execution_verifications",
        "verification_evidence_refs",
    ):
        refs.extend(_string_list(artifacts.get(key)))
    return list(dict.fromkeys(refs))


def _judge_result_metadata(report: VerificationReport) -> dict[str, Any]:
    for result in report.results:
        verdict = result.criterion.spec.get("judge_verdict")
        if not isinstance(verdict, str) or not verdict:
            continue
        metadata: dict[str, Any] = {
            "last_verification_judge_verdict": verdict,
            "last_verification_judge_rationale": result.message,
            "last_verification_judge_confidence": result.confidence,
        }
        next_action_kind = result.criterion.spec.get("next_action_kind")
        if isinstance(next_action_kind, str) and next_action_kind.strip():
            metadata["last_verification_judge_next_action_kind"] = next_action_kind
        failed_criteria = result.criterion.spec.get("failed_criteria")
        if isinstance(failed_criteria, list):
            metadata["last_verification_judge_failed_criteria"] = [
                str(item) for item in failed_criteria if item
            ]
        required_next_action = result.criterion.spec.get("required_next_action")
        if isinstance(required_next_action, str) and required_next_action.strip():
            metadata["last_verification_judge_required_next_action"] = required_next_action
        repair_brief = result.criterion.spec.get("repair_brief")
        if isinstance(repair_brief, Mapping) and repair_brief:
            metadata["last_verification_judge_repair_brief"] = dict(repair_brief)
        feedback_items = result.criterion.spec.get("feedback_items")
        if isinstance(feedback_items, list):
            metadata["last_verification_feedback_items"] = [
                dict(item) for item in feedback_items if isinstance(item, Mapping)
            ]
        return metadata
    return {}


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


def _last_prefixed_value(values: list[str], prefix: str) -> str | None:
    matched: str | None = None
    for value in values:
        if value.startswith(prefix):
            matched = value.removeprefix(prefix)
    return matched


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
