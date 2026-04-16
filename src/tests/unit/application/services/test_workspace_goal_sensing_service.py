from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.services.workspace_goal_sensing_service import WorkspaceGoalSensingService
from src.domain.model.workspace.blackboard_post import BlackboardPost, BlackboardPostStatus
from src.domain.model.workspace.cyber_objective import CyberObjective
from src.domain.model.workspace.workspace_message import MessageSenderType, WorkspaceMessage
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)

_NOW = datetime(2026, 4, 16, 3, 0, 0, tzinfo=UTC)


def _root_task(title: str, *, task_id: str = "task-1") -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id="ws-1",
        title=title,
        created_by="user-1",
        status=WorkspaceTaskStatus.TODO,
        priority=WorkspaceTaskPriority.P2,
        metadata={"task_role": "goal_root", "goal_origin": "human_defined"},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _objective(title: str, *, objective_id: str = "obj-1", progress: float = 0.25) -> CyberObjective:
    return CyberObjective(
        id=objective_id,
        workspace_id="ws-1",
        title=title,
        description="Objective description",
        progress=progress,
        created_by="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _post(content: str, *, title: str = "Directive", post_id: str = "post-1") -> BlackboardPost:
    return BlackboardPost(
        id=post_id,
        workspace_id="ws-1",
        author_id="user-1",
        title=title,
        content=content,
        status=BlackboardPostStatus.OPEN,
        is_pinned=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _message(content: str, *, message_id: str = "msg-1") -> WorkspaceMessage:
    return WorkspaceMessage(
        id=message_id,
        workspace_id="ws-1",
        sender_id="user-1",
        sender_type=MessageSenderType.HUMAN,
        content=content,
        mentions=[],
        created_at=_NOW,
    )


@pytest.mark.unit
class TestWorkspaceGoalSensingService:
    def test_existing_root_tasks_rank_as_adopt_existing_goal(self) -> None:
        service = WorkspaceGoalSensingService()

        candidates = service.sense_candidates(
            tasks=[_root_task("Ship rollback checklist")],
            objectives=[],
            posts=[],
            messages=[],
            now=_NOW,
        )

        assert candidates[0].decision == "adopt_existing_goal"
        assert candidates[0].candidate_kind == "existing"
        assert candidates[0].evidence_strength == 1.0

    def test_objective_candidates_rank_as_existing_goals(self) -> None:
        service = WorkspaceGoalSensingService()

        candidates = service.sense_candidates(
            tasks=[],
            objectives=[_objective("Reduce outage recovery time")],
            posts=[],
            messages=[],
            now=_NOW,
        )

        assert candidates[0].decision == "adopt_existing_goal"
        assert candidates[0].source_refs == ["objective:obj-1"]
        assert candidates[0].evidence_strength == 0.9

    def test_explicit_blackboard_directive_formalizes_new_goal(self) -> None:
        service = WorkspaceGoalSensingService()

        candidates = service.sense_candidates(
            tasks=[],
            objectives=[],
            posts=[_post("Please prepare the rollback checklist before deploy.")],
            messages=[],
            now=_NOW,
        )

        assert candidates[0].decision == "formalize_new_goal"
        assert candidates[0].formalizable is True
        assert candidates[0].evidence_strength >= 0.8

    def test_casual_message_is_rejected_as_non_goal(self) -> None:
        service = WorkspaceGoalSensingService()

        candidates = service.sense_candidates(
            tasks=[],
            objectives=[],
            posts=[],
            messages=[_message("Maybe we should think about migrations later")],
            now=_NOW,
        )

        assert candidates[0].decision == "reject_as_non_goal"
        assert candidates[0].formalizable is False
        assert candidates[0].evidence_strength <= 0.4

    def test_converged_blackboard_and_message_gain_bonus(self) -> None:
        service = WorkspaceGoalSensingService()
        text = "Please prepare rollback checklist"

        candidates = service.sense_candidates(
            tasks=[],
            objectives=[],
            posts=[_post(text, title="Rollback")],
            messages=[_message(text)],
            now=_NOW,
        )

        top = candidates[0]
        assert top.decision == "formalize_new_goal"
        assert top.evidence_strength == pytest.approx(0.95)
        assert len(top.source_refs) == 2

    def test_inferred_goal_overlapping_open_root_is_deferred(self) -> None:
        service = WorkspaceGoalSensingService()
        existing = _root_task("Prepare rollback checklist")

        candidates = service.sense_candidates(
            tasks=[existing],
            objectives=[],
            posts=[_post("Please prepare rollback checklist", title="Rollback checklist")],
            messages=[],
            now=_NOW,
        )

        assert any(
            candidate.candidate_text == "Prepare rollback checklist"
            and candidate.decision == "adopt_existing_goal"
            for candidate in candidates
        )
        assert any(candidate.decision == "defer" for candidate in candidates)
