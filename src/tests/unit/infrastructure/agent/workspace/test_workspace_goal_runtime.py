from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock

import pytest

from src.domain.model.workspace.workspace_task import WorkspaceTaskStatus
from src.domain.model.workspace_plan import Plan, PlanStatus
from src.domain.model.workspace_plan.plan_node import (
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    TaskExecution,
    TaskIntent,
)
from src.infrastructure.agent.workspace.workspace_goal_runtime import (
    _active_plan_is_effectively_complete,
    _effectively_complete_plan_tail_allows_root_completion,
    _launch_workspace_retry_attempt,
    adjudicate_workspace_worker_report,
    apply_workspace_worker_report,
    auto_complete_ready_root,
    maybe_materialize_workspace_goal_candidate,
    prepare_workspace_subagent_delegation,
    resolve_workspace_execution_task_for_delegate,
)
from src.infrastructure.workspace_core.legacy_runtime import LegacyWorkspaceRuntimeRetiredError


def _plan_with_nodes(*, status: PlanStatus, nodes: list[PlanNode]) -> Plan:
    plan = Plan(
        id="plan-1",
        workspace_id="ws-1",
        goal_id=PlanNodeId("goal-1"),
        status=status,
    )
    for node in nodes:
        plan.add_node(node)
    return plan


def _goal_node() -> PlanNode:
    return PlanNode(
        id="goal-1",
        plan_id="plan-1",
        kind=PlanNodeKind.GOAL,
        title="Ship goal",
        intent=TaskIntent.TODO,
        execution=TaskExecution.IDLE,
    )


def _task_node(
    *,
    intent: TaskIntent = TaskIntent.DONE,
    execution: TaskExecution = TaskExecution.IDLE,
    current_attempt_id: str | None = None,
) -> PlanNode:
    return PlanNode(
        id="task-1",
        plan_id="plan-1",
        parent_id=PlanNodeId("goal-1"),
        kind=PlanNodeKind.TASK,
        title="Done task",
        intent=intent,
        execution=execution,
        current_attempt_id=current_attempt_id,
    )


@pytest.mark.unit
class TestWorkspaceGoalRuntime:
    def test_active_plan_effectively_complete_allows_idle_root_tail(self) -> None:
        plan = _plan_with_nodes(
            status=PlanStatus.ACTIVE,
            nodes=[_goal_node(), _task_node(current_attempt_id="attempt-1")],
        )

        assert _active_plan_is_effectively_complete(plan) is True

    def test_active_plan_effectively_complete_rejects_remaining_work(self) -> None:
        active_task = _plan_with_nodes(
            status=PlanStatus.ACTIVE,
            nodes=[
                _goal_node(),
                _task_node(
                    intent=TaskIntent.IN_PROGRESS,
                    execution=TaskExecution.RUNNING,
                    current_attempt_id="attempt-1",
                ),
            ],
        )
        completed_plan = _plan_with_nodes(
            status=PlanStatus.COMPLETED,
            nodes=[_goal_node(), _task_node()],
        )

        assert _active_plan_is_effectively_complete(active_task) is False
        assert _active_plan_is_effectively_complete(completed_plan) is False

    def test_effectively_complete_plan_tail_allows_only_metadata_tail_blockers(self) -> None:
        plan = _plan_with_nodes(
            status=PlanStatus.ACTIVE,
            nodes=[_goal_node(), _task_node(current_attempt_id="attempt-1")],
        )
        gate = {
            "blocked_reasons": [
                "plan status is active",
                "active or retryable outbox items remain",
                "required acceptance criteria lack verifier evidence",
                "accepted worktree integration is incomplete",
            ],
        }

        assert _effectively_complete_plan_tail_allows_root_completion(
            plan=plan,
            gate=gate,
            retry_queue=[{"event_type": "supervisor_tick", "status": "processing"}],
            active_attempts=[],
        )
        assert not _effectively_complete_plan_tail_allows_root_completion(
            plan=plan,
            gate=gate,
            retry_queue=[{"event_type": "worker_launch", "status": "pending"}],
            active_attempts=[],
        )

    @pytest.mark.parametrize(
        ("operation", "kwargs"),
        [
            (
                maybe_materialize_workspace_goal_candidate,
                {"project_id": "project-1", "tenant_id": "tenant-1", "user_id": "user-1"},
            ),
            (
                auto_complete_ready_root,
                {
                    "workspace_id": "workspace-1",
                    "actor_user_id": "user-1",
                    "root_task": MagicMock(),
                    "task_repo": MagicMock(),
                    "command_service": MagicMock(),
                    "leader_agent_id": "leader-1",
                },
            ),
            (
                apply_workspace_worker_report,
                {
                    "workspace_id": "workspace-1",
                    "root_goal_task_id": "root-1",
                    "task_id": "task-1",
                    "actor_user_id": "user-1",
                    "worker_agent_id": "worker-1",
                    "report_type": "completed",
                    "summary": "done",
                },
            ),
            (
                adjudicate_workspace_worker_report,
                {
                    "workspace_id": "workspace-1",
                    "task_id": "task-1",
                    "actor_user_id": "user-1",
                    "status": WorkspaceTaskStatus.DONE,
                },
            ),
            (
                resolve_workspace_execution_task_for_delegate,
                {
                    "workspace_id": "workspace-1",
                    "root_goal_task_id": "root-1",
                    "delegated_task_text": "task_id=task-1",
                    "subagent_name": "worker",
                },
            ),
            (
                prepare_workspace_subagent_delegation,
                {
                    "workspace_id": "workspace-1",
                    "root_goal_task_id": "root-1",
                    "actor_user_id": "user-1",
                    "delegated_task_text": "task_id=task-1",
                    "subagent_name": "worker",
                    "subagent_id": "agent-1",
                    "leader_agent_id": "leader-1",
                },
            ),
            (
                _launch_workspace_retry_attempt,
                {
                    "workspace_id": "workspace-1",
                    "root_goal_task_id": "root-1",
                    "workspace_task_id": "task-1",
                    "attempt_id": "attempt-1",
                    "actor_user_id": "user-1",
                    "leader_agent_id": "leader-1",
                    "retry_feedback": "retry",
                },
            ),
        ],
    )
    async def test_retired_workspace_runtime_entrypoints_fail_closed(
        self,
        operation: Callable[..., Awaitable[object]],
        kwargs: dict[str, object],
    ) -> None:
        with pytest.raises(LegacyWorkspaceRuntimeRetiredError, match="Avernet Workspace Core"):
            await operation(**kwargs)
