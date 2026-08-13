"""Tests for the retired Plan controller and its pure snapshot gate."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.domain.model.workspace_plan import (
    Plan,
    PlanNode,
    PlanNodeId,
    PlanNodeKind,
    PlanStatus,
    TaskIntent,
)
from src.infrastructure.agent.workspace_plan.run_contract import WorkspaceRunContract
from src.infrastructure.agent.workspace_plan.run_controller import (
    LegacyWorkspacePlanRuntimeRetiredError,
    WorkspaceRunController,
    completion_gate_for_plan,
)


def _completed_plan(*, metadata: dict[str, object] | None = None) -> Plan:
    goal_id = PlanNodeId("goal-1")
    plan = Plan(
        id="plan-1",
        workspace_id="workspace-1",
        goal_id=goal_id,
        status=PlanStatus.COMPLETED,
    )
    plan.add_node(
        PlanNode(
            id="goal-1",
            plan_id="plan-1",
            parent_id=None,
            kind=PlanNodeKind.GOAL,
            title="Ship feature",
            description="",
            intent=TaskIntent.DONE,
            metadata=metadata
            or {
                "last_verification_passed": True,
                "last_verification_summary": "tests passed",
                "verification_evidence_refs": ["test_run:pytest"],
            },
        )
    )
    return plan


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retired_controller_entrypoints_fail_closed() -> None:
    controller = WorkspaceRunController(object())

    for call in (
        controller.tick(reason="test"),
        controller.retry_queue("workspace-1"),
        controller.active_attempts("workspace-1"),
    ):
        with pytest.raises(
            LegacyWorkspacePlanRuntimeRetiredError,
            match="Avernet Workspace Core",
        ):
            await call


@pytest.mark.unit
def test_completion_gate_accepts_a_complete_materialized_snapshot() -> None:
    result = completion_gate_for_plan(
        _completed_plan(),
        retry_queue=[],
        active_attempts=[],
        contract=WorkspaceRunContract(),
    )

    assert result["allowed"] is True


@pytest.mark.unit
def test_completion_gate_blocks_retry_and_active_attempt_snapshots() -> None:
    result = completion_gate_for_plan(
        _completed_plan(),
        retry_queue=[{"outbox_id": "outbox-1"}],
        active_attempts=[{"attempt_id": "attempt-1"}],
        contract=WorkspaceRunContract(),
    )

    assert result["allowed"] is False
    assert result["checks"]["no_active_retry_outbox"] is False
    assert result["checks"]["no_running_attempts"] is False


@pytest.mark.unit
def test_completion_gate_blocks_unintegrated_attempt_worktree() -> None:
    plan = _completed_plan()
    node = plan.nodes[PlanNodeId("goal-1")]
    plan.replace_node(
        replace(
            node,
            metadata={
                **dict(node.metadata),
                "verified_commit_ref": "abc1234",
                "worktree_integration_status": "blocked_dirty_main",
                "worktree_integration_worktree_path": (
                    "/workspace/.memstack/worktrees/attempt-1"
                ),
            },
        )
    )

    result = completion_gate_for_plan(
        plan,
        retry_queue=[],
        active_attempts=[],
        contract=WorkspaceRunContract(),
    )

    assert result["allowed"] is False
    assert result["checks"]["worktrees_integrated"] is False
