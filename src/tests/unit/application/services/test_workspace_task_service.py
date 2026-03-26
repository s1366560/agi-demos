"""Unit tests for WorkspaceTaskService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


def _make_workspace(workspace_id: str = "ws-1") -> Workspace:
    return Workspace(
        id=workspace_id,
        tenant_id="tenant-1",
        project_id="project-1",
        name="Workspace One",
        created_by="owner-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_member(
    user_id: str,
    role: WorkspaceRole,
    workspace_id: str = "ws-1",
) -> WorkspaceMember:
    return WorkspaceMember(
        id=f"wm-{workspace_id}-{user_id}",
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        invited_by="owner-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_task(
    task_id: str = "wt-1",
    workspace_id: str = "ws-1",
    status: WorkspaceTaskStatus = WorkspaceTaskStatus.TODO,
) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id=workspace_id,
        title="Investigate integration issue",
        description="details",
        created_by="owner-1",
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_agent_binding(
    binding_id: str = "wa-1",
    workspace_id: str = "ws-1",
    agent_id: str = "agent-1",
    is_active: bool = True,
) -> WorkspaceAgent:
    return WorkspaceAgent(
        id=binding_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        display_name="Agent",
        is_active=is_active,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_workspace_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_member_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_workspace_and_user = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_task_repo() -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.find_by_id = AsyncMock(return_value=None)
    repo.find_by_workspace = AsyncMock(return_value=[])
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def workspace_task_service(
    mock_workspace_repo: MagicMock,
    mock_member_repo: MagicMock,
    mock_agent_repo: MagicMock,
    mock_task_repo: MagicMock,
):
    from src.application.services.workspace_task_service import WorkspaceTaskService

    return WorkspaceTaskService(
        workspace_repo=mock_workspace_repo,
        workspace_member_repo=mock_member_repo,
        workspace_agent_repo=mock_agent_repo,
        workspace_task_repo=mock_task_repo,
    )


@pytest.mark.unit
class TestWorkspaceTaskService:
    @pytest.mark.asyncio
    async def test_create_task_requires_editor_permission(
        self,
        workspace_task_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "viewer-1", WorkspaceRole.VIEWER
        )

        with pytest.raises(PermissionError, match="permission"):
            await workspace_task_service.create_task(
                workspace_id="ws-1",
                actor_user_id="viewer-1",
                title="New task",
            )

    @pytest.mark.asyncio
    async def test_assign_agent_rejects_workspace_mismatch(
        self,
        workspace_task_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
        mock_task_repo: MagicMock,
    ) -> None:
        task = _make_task()
        mock_workspace_repo.find_by_id.return_value = _make_workspace("ws-1")
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "editor-1", WorkspaceRole.EDITOR, "ws-1"
        )
        mock_task_repo.find_by_id.return_value = task
        mock_agent_repo.find_by_id.return_value = _make_agent_binding(workspace_id="ws-2")

        with pytest.raises(ValueError, match="does not belong to workspace"):
            await workspace_task_service.assign_task_to_agent(
                workspace_id="ws-1",
                task_id="wt-1",
                actor_user_id="editor-1",
                workspace_agent_id="wa-1",
            )

    @pytest.mark.asyncio
    async def test_start_task_rejects_invalid_transition_from_done(
        self,
        workspace_task_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_task_repo: MagicMock,
    ) -> None:
        done_task = _make_task(status=WorkspaceTaskStatus.DONE)
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "member-1", WorkspaceRole.VIEWER
        )
        mock_task_repo.find_by_id.return_value = done_task

        with pytest.raises(ValueError, match="Cannot transition"):
            await workspace_task_service.start_task(
                workspace_id="ws-1",
                task_id="wt-1",
                actor_user_id="member-1",
            )

    @pytest.mark.asyncio
    async def test_complete_task_succeeds_from_in_progress(
        self,
        workspace_task_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_task_repo: MagicMock,
    ) -> None:
        in_progress = _make_task(status=WorkspaceTaskStatus.IN_PROGRESS)
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "member-1", WorkspaceRole.VIEWER
        )
        mock_task_repo.find_by_id.return_value = in_progress
        mock_task_repo.save.side_effect = lambda task: task

        updated = await workspace_task_service.complete_task(
            workspace_id="ws-1",
            task_id="wt-1",
            actor_user_id="member-1",
        )

        assert updated.status == WorkspaceTaskStatus.DONE

