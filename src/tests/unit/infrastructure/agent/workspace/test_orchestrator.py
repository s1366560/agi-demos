"""Unit tests for WorkspaceAutonomyOrchestrator facade (P2d M5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.workspace_task import (
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.workspace import orchestrator as orchestrator_module
from src.infrastructure.agent.workspace.orchestrator import WorkspaceAutonomyOrchestrator


@pytest.fixture
def facade() -> WorkspaceAutonomyOrchestrator:
    return WorkspaceAutonomyOrchestrator()


def test_dataclass_is_frozen(facade: WorkspaceAutonomyOrchestrator) -> None:
    with pytest.raises(Exception):
        facade.foo = "bar"  # type: ignore[attr-defined]


class TestShouldActivate:
    def test_forwards_kwargs(
        self, facade: WorkspaceAutonomyOrchestrator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = MagicMock(return_value=True)
        monkeypatch.setattr(
            orchestrator_module._runtime,
            "should_activate_workspace_authority",
            spy,
        )
        assert (
            facade.should_activate("do something", has_workspace_binding=True, has_open_root=False)
            is True
        )
        spy.assert_called_once_with("do something", has_workspace_binding=True, has_open_root=False)


class TestMaterializeGoalCandidate:
    @pytest.mark.asyncio
    async def test_forwards_positional_and_kwargs(
        self, facade: WorkspaceAutonomyOrchestrator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = AsyncMock(return_value=None)
        monkeypatch.setattr(
            orchestrator_module._runtime,
            "maybe_materialize_workspace_goal_candidate",
            stub,
        )
        result = await facade.materialize_goal_candidate(
            "proj", "tenant", "user", leader_agent_id="leader", user_query="hi"
        )
        assert result is None
        stub.assert_awaited_once_with(
            "proj",
            "tenant",
            "user",
            leader_agent_id="leader",
            user_query="hi",
        )


class TestApplyWorkerReport:
    @pytest.mark.asyncio
    async def test_forwards_all_kwargs(
        self, facade: WorkspaceAutonomyOrchestrator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = AsyncMock(return_value=None)
        monkeypatch.setattr(orchestrator_module._runtime, "apply_workspace_worker_report", stub)
        await facade.apply_worker_report(
            workspace_id="ws",
            root_goal_task_id="root",
            task_id="task",
            actor_user_id="user",
            worker_agent_id="worker",
            report_type="success",
            summary="done",
            artifacts=["a1"],
            verifications=["preflight:git-status"],
            leader_agent_id="leader",
        )
        stub.assert_awaited_once_with(
            workspace_id="ws",
            root_goal_task_id="root",
            task_id="task",
            attempt_id=None,
            conversation_id=None,
            actor_user_id="user",
            worker_agent_id="worker",
            report_type="success",
            summary="done",
            artifacts=["a1"],
            verifications=["preflight:git-status"],
            leader_agent_id="leader",
            report_id=None,
        )


class TestAdjudicateWorkerReport:
    @pytest.mark.asyncio
    async def test_forwards_status_and_priority(
        self, facade: WorkspaceAutonomyOrchestrator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = AsyncMock(return_value=None)
        monkeypatch.setattr(
            orchestrator_module._runtime,
            "adjudicate_workspace_worker_report",
            stub,
        )
        await facade.adjudicate_worker_report(
            workspace_id="ws",
            task_id="task",
            actor_user_id="user",
            status=WorkspaceTaskStatus.DONE,
            leader_agent_id="leader",
            priority=WorkspaceTaskPriority.P1,
        )
        stub.assert_awaited_once_with(
            workspace_id="ws",
            task_id="task",
            attempt_id=None,
            actor_user_id="user",
            status=WorkspaceTaskStatus.DONE,
            leader_agent_id="leader",
            title=None,
            priority=WorkspaceTaskPriority.P1,
        )


class TestAutoCompleteReadyRoot:
    @pytest.mark.asyncio
    async def test_forwards(
        self, facade: WorkspaceAutonomyOrchestrator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = AsyncMock(return_value=None)
        monkeypatch.setattr(orchestrator_module._runtime, "auto_complete_ready_root", stub)
        task_repo = MagicMock()
        command_service = MagicMock()
        root_task = MagicMock()
        await facade.auto_complete_ready_root(
            workspace_id="ws",
            actor_user_id="user",
            root_task=root_task,
            task_repo=task_repo,
            command_service=command_service,
            leader_agent_id=None,
        )
        stub.assert_awaited_once_with(
            workspace_id="ws",
            actor_user_id="user",
            root_task=root_task,
            task_repo=task_repo,
            command_service=command_service,
            leader_agent_id=None,
        )


class TestPrepareSubagentDelegation:
    @pytest.mark.asyncio
    async def test_forwards(
        self, facade: WorkspaceAutonomyOrchestrator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stub = AsyncMock(return_value={"conversation_id": "c1"})
        monkeypatch.setattr(
            orchestrator_module._runtime,
            "prepare_workspace_subagent_delegation",
            stub,
        )
        result = await facade.prepare_subagent_delegation(
            workspace_id="ws",
            root_goal_task_id="root",
            actor_user_id="user",
            delegated_task_text="do X",
            subagent_name="coder",
            subagent_id="sub1",
            leader_agent_id="leader",
        )
        assert result == {"conversation_id": "c1"}
        stub.assert_awaited_once_with(
            workspace_id="ws",
            root_goal_task_id="root",
            actor_user_id="user",
            delegated_task_text="do X",
            subagent_name="coder",
            subagent_id="sub1",
            leader_agent_id="leader",
            workspace_task_id=None,
        )
