from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application.schemas.workspace_agent_autonomy import GoalCandidateRecordModel
from src.application.services.workspace_goal_materialization_service import (
    WorkspaceGoalMaterializationService,
)
from src.domain.model.workspace.cyber_objective import CyberObjective
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


def _candidate(
    *,
    decision: str,
    candidate_kind: str = "inferred",
    source_refs: list[str] | None = None,
    evidence_strength: float = 0.85,
    text: str = "Prepare rollback checklist",
) -> GoalCandidateRecordModel:
    return GoalCandidateRecordModel(
        candidate_id="candidate-1",
        candidate_text=text,
        candidate_kind=candidate_kind,
        source_refs=source_refs or ["message:msg-1"],
        evidence_strength=evidence_strength,
        source_breakdown=[
            {
                "source_type": "message_signal",
                "score": 0.85,
                "ref": "message:msg-1",
            }
        ],
        freshness=1.0,
        urgency=0.8,
        user_intent_confidence=evidence_strength,
        formalizable=decision == "formalize_new_goal",
        decision=decision,
    )


def _task(task_id: str = "task-1") -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id="ws-1",
        title="Existing root",
        created_by="user-1",
        status=WorkspaceTaskStatus.TODO,
        metadata={"task_role": "goal_root", "goal_origin": "human_defined"},
    )


def _objective(objective_id: str = "obj-1") -> CyberObjective:
    return CyberObjective(
        id=objective_id,
        workspace_id="ws-1",
        title="Objective root",
        description="Objective description",
        created_by="user-1",
    )


@pytest.mark.unit
class TestWorkspaceGoalMaterializationService:
    async def test_reject_candidate_returns_none(self) -> None:
        service = WorkspaceGoalMaterializationService(
            objective_repo=AsyncMock(),
            task_repo=AsyncMock(),
            task_service=AsyncMock(),
            task_command_service=AsyncMock(),
        )

        result = await service.materialize_candidate(
            workspace_id="ws-1",
            actor_user_id="user-1",
            candidate=_candidate(decision="reject_as_non_goal", evidence_strength=0.35),
        )

        assert result is None

    async def test_adopt_existing_task_returns_task(self) -> None:
        task_service = AsyncMock()
        task_service.get_task.return_value = _task("task-existing")
        service = WorkspaceGoalMaterializationService(
            objective_repo=AsyncMock(),
            task_repo=AsyncMock(),
            task_service=task_service,
            task_command_service=AsyncMock(),
        )

        result = await service.materialize_candidate(
            workspace_id="ws-1",
            actor_user_id="user-1",
            candidate=_candidate(
                decision="adopt_existing_goal",
                candidate_kind="existing",
                source_refs=["task:task-existing"],
            ),
        )

        assert result is not None
        assert result.id == "task-existing"

    async def test_adopt_objective_projects_when_no_existing_root(self) -> None:
        objective_repo = AsyncMock()
        objective_repo.find_by_id.return_value = _objective("obj-77")
        task_repo = AsyncMock()
        task_repo.find_root_by_objective_id.return_value = None
        task_command_service = AsyncMock()
        task_command_service.create_task.return_value = _task("projected-task")

        service = WorkspaceGoalMaterializationService(
            objective_repo=objective_repo,
            task_repo=task_repo,
            task_service=AsyncMock(),
            task_command_service=task_command_service,
        )

        result = await service.materialize_candidate(
            workspace_id="ws-1",
            actor_user_id="user-1",
            candidate=_candidate(
                decision="adopt_existing_goal",
                candidate_kind="existing",
                source_refs=["objective:obj-77"],
                text="Objective root",
            ),
        )

        assert result is not None
        assert result.id == "projected-task"
        task_command_service.create_task.assert_awaited_once()

    async def test_formalize_inferred_goal_creates_root_task(self) -> None:
        task_command_service = AsyncMock()
        task_command_service.create_task.return_value = _task("formalized-root")

        service = WorkspaceGoalMaterializationService(
            objective_repo=AsyncMock(),
            task_repo=AsyncMock(),
            task_service=AsyncMock(),
            task_command_service=task_command_service,
        )

        result = await service.materialize_candidate(
            workspace_id="ws-1",
            actor_user_id="user-1",
            candidate=_candidate(decision="formalize_new_goal"),
        )

        assert result is not None
        assert result.id == "formalized-root"
        task_command_service.create_task.assert_awaited_once()
