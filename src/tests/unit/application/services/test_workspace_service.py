"""Unit tests for WorkspaceService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_agent import WorkspaceAgent
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole


def _make_workspace(workspace_id: str = "ws-1") -> Workspace:
    return Workspace(
        id=workspace_id,
        tenant_id="tenant-1",
        project_id="project-1",
        name="Workspace One",
        created_by="owner-1",
        description="A test workspace",
        metadata={"source": "test"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_member(
    user_id: str,
    role: WorkspaceRole,
    workspace_id: str = "ws-1",
    member_id: str | None = None,
) -> WorkspaceMember:
    return WorkspaceMember(
        id=member_id or f"wm-{user_id}",
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        invited_by="owner-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_agent_binding(
    binding_id: str = "wa-1",
    workspace_id: str = "ws-1",
    agent_id: str = "agent-1",
) -> WorkspaceAgent:
    return WorkspaceAgent(
        id=binding_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        display_name="Agent One",
        description="helper agent",
        config={"mode": "assist"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_workspace_repo() -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.find_by_id = AsyncMock(return_value=None)
    repo.find_by_project = AsyncMock(return_value=[])
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_member_repo() -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.find_by_id = AsyncMock(return_value=None)
    repo.find_by_workspace = AsyncMock(return_value=[])
    repo.find_by_workspace_and_user = AsyncMock(return_value=None)
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.find_by_id = AsyncMock(return_value=None)
    repo.find_by_workspace = AsyncMock(return_value=[])
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def workspace_service(
    mock_workspace_repo: MagicMock, mock_member_repo: MagicMock, mock_agent_repo: MagicMock
):
    from src.application.services.workspace_service import WorkspaceService

    return WorkspaceService(
        workspace_repo=mock_workspace_repo,
        workspace_member_repo=mock_member_repo,
        workspace_agent_repo=mock_agent_repo,
    )


@pytest.fixture
def workspace_event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def workspace_service_with_events(
    mock_workspace_repo: MagicMock,
    mock_member_repo: MagicMock,
    mock_agent_repo: MagicMock,
    workspace_event_publisher: AsyncMock,
):
    from src.application.services.workspace_service import WorkspaceService

    return WorkspaceService(
        workspace_repo=mock_workspace_repo,
        workspace_member_repo=mock_member_repo,
        workspace_agent_repo=mock_agent_repo,
        workspace_event_publisher=workspace_event_publisher,
    )


class TestWorkspaceLifecycle:
    @pytest.mark.unit
    async def test_create_workspace_creates_owner_membership(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.save.side_effect = lambda workspace: workspace
        mock_member_repo.save.side_effect = lambda member: member

        created = await workspace_service.create_workspace(
            tenant_id="tenant-1",
            project_id="project-1",
            name="Team Space",
            created_by="owner-1",
        )

        assert created.name == "Team Space"
        assert created.created_by == "owner-1"
        assert mock_workspace_repo.save.await_count == 1
        saved_member = mock_member_repo.save.await_args.args[0]
        assert saved_member.user_id == "owner-1"
        assert saved_member.role == WorkspaceRole.OWNER

    @pytest.mark.unit
    async def test_update_workspace_forbidden_for_viewer(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="viewer-1",
            role=WorkspaceRole.VIEWER,
        )

        with pytest.raises(PermissionError, match="permission"):
            await workspace_service.update_workspace(
                workspace_id="ws-1",
                actor_user_id="viewer-1",
                name="New Name",
            )

    @pytest.mark.unit
    async def test_delete_workspace_requires_owner(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1",
            role=WorkspaceRole.EDITOR,
        )

        with pytest.raises(PermissionError, match="owner"):
            await workspace_service.delete_workspace(
                workspace_id="ws-1",
                actor_user_id="editor-1",
            )


class TestWorkspaceMemberManagement:
    @pytest.mark.unit
    async def test_add_member_publishes_workspace_member_joined_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.side_effect = [
            _make_member("owner-1", WorkspaceRole.OWNER),
            None,
        ]
        mock_member_repo.save.side_effect = lambda member: member

        await workspace_service_with_events.add_member(
            workspace_id="ws-1",
            actor_user_id="owner-1",
            target_user_id="user-2",
            role=WorkspaceRole.EDITOR,
        )

        assert workspace_event_publisher.await_count == 1
        assert workspace_event_publisher.await_args.args[1] == "workspace_member_joined"

    @pytest.mark.unit
    async def test_add_member_requires_owner_role(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.side_effect = [
            _make_member("viewer-1", WorkspaceRole.VIEWER),
            None,
        ]

        with pytest.raises(PermissionError, match="owner"):
            await workspace_service.add_member(
                workspace_id="ws-1",
                actor_user_id="viewer-1",
                target_user_id="new-user",
                role=WorkspaceRole.VIEWER,
            )

    @pytest.mark.unit
    async def test_add_member_rejects_duplicate_user(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.side_effect = [
            _make_member("owner-1", WorkspaceRole.OWNER),
            _make_member("target-1", WorkspaceRole.VIEWER),
        ]

        with pytest.raises(ValueError, match="already a member"):
            await workspace_service.add_member(
                workspace_id="ws-1",
                actor_user_id="owner-1",
                target_user_id="target-1",
                role=WorkspaceRole.EDITOR,
            )

    @pytest.mark.unit
    async def test_update_member_role_blocks_owner_self_demote(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        owner = _make_member("owner-1", WorkspaceRole.OWNER)
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.side_effect = [owner, owner]

        with pytest.raises(ValueError, match="Cannot change your own owner role"):
            await workspace_service.update_member_role(
                workspace_id="ws-1",
                actor_user_id="owner-1",
                target_user_id="owner-1",
                new_role=WorkspaceRole.EDITOR,
            )

    @pytest.mark.unit
    async def test_list_members_requires_existing_membership(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = None

        with pytest.raises(PermissionError, match="member"):
            await workspace_service.list_members(
                workspace_id="ws-1",
                actor_user_id="unknown-user",
            )


class TestWorkspaceAgentBinding:
    @pytest.mark.unit
    async def test_bind_agent_forbidden_for_viewer(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "viewer-1",
            WorkspaceRole.VIEWER,
        )

        with pytest.raises(PermissionError, match="permission"):
            await workspace_service.bind_agent(
                workspace_id="ws-1",
                actor_user_id="viewer-1",
                agent_id="agent-1",
            )

    @pytest.mark.unit
    async def test_bind_agent_updates_existing_relation(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
    ) -> None:
        existing = _make_agent_binding(binding_id="wa-existing", agent_id="agent-1")
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "editor-1",
            WorkspaceRole.EDITOR,
        )
        mock_agent_repo.find_by_workspace.return_value = [existing]
        mock_agent_repo.save.side_effect = lambda relation: relation

        updated = await workspace_service.bind_agent(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            agent_id="agent-1",
            display_name="Renamed Agent",
            is_active=False,
        )

        assert updated.id == "wa-existing"
        assert updated.display_name == "Renamed Agent"
        assert updated.is_active is False

    @pytest.mark.unit
    async def test_update_agent_binding_rejects_workspace_mismatch(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace(workspace_id="ws-1")
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "owner-1",
            WorkspaceRole.OWNER,
        )
        mock_agent_repo.find_by_id.return_value = _make_agent_binding(
            binding_id="wa-1",
            workspace_id="ws-2",
        )

        with pytest.raises(ValueError, match="does not belong to workspace"):
            await workspace_service.update_agent_binding(
                workspace_id="ws-1",
                actor_user_id="owner-1",
                workspace_agent_id="wa-1",
                description="updated",
            )


class TestWorkspaceEventPublishing:
    @pytest.mark.unit
    async def test_create_workspace_publishes_member_joined_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.save.side_effect = lambda workspace: workspace
        mock_member_repo.save.side_effect = lambda member: member

        await workspace_service_with_events.create_workspace(
            tenant_id="tenant-1",
            project_id="project-1",
            name="Team Space",
            created_by="owner-1",
        )

        assert workspace_event_publisher.await_count == 1
        call_args = workspace_event_publisher.await_args.args
        assert call_args[1] == "workspace_member_joined"
        payload = call_args[2]
        assert payload["user_id"] == "owner-1"
        assert payload["role"] == "owner"

    @pytest.mark.unit
    async def test_update_workspace_publishes_workspace_updated_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        ws = _make_workspace()
        mock_workspace_repo.find_by_id.return_value = ws
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "editor-1",
            WorkspaceRole.EDITOR,
        )
        mock_workspace_repo.save.side_effect = lambda workspace: workspace

        await workspace_service_with_events.update_workspace(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            name="Renamed",
        )

        assert workspace_event_publisher.await_count == 1
        call_args = workspace_event_publisher.await_args.args
        assert call_args[1] == "workspace_updated"
        payload = call_args[2]
        assert payload["workspace_id"] == "ws-1"
        assert payload["updated_by"] == "editor-1"

    @pytest.mark.unit
    async def test_delete_workspace_publishes_workspace_deleted_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "owner-1",
            WorkspaceRole.OWNER,
        )
        mock_workspace_repo.delete.return_value = True

        await workspace_service_with_events.delete_workspace(
            workspace_id="ws-1",
            actor_user_id="owner-1",
        )

        assert workspace_event_publisher.await_count == 1
        call_args = workspace_event_publisher.await_args.args
        assert call_args[1] == "workspace_deleted"
        payload = call_args[2]
        assert payload["workspace_id"] == "ws-1"
        assert payload["deleted_by"] == "owner-1"

    @pytest.mark.unit
    async def test_delete_workspace_no_event_when_delete_returns_false(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "owner-1",
            WorkspaceRole.OWNER,
        )
        mock_workspace_repo.delete.return_value = False

        await workspace_service_with_events.delete_workspace(
            workspace_id="ws-1",
            actor_user_id="owner-1",
        )

        workspace_event_publisher.assert_not_awaited()

    @pytest.mark.unit
    async def test_remove_member_publishes_member_left_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        target = _make_member("user-2", WorkspaceRole.VIEWER, member_id="wm-user-2")
        mock_member_repo.find_by_workspace_and_user.side_effect = [
            _make_member("owner-1", WorkspaceRole.OWNER),
            target,
        ]
        mock_member_repo.delete.return_value = True

        await workspace_service_with_events.remove_member(
            workspace_id="ws-1",
            actor_user_id="owner-1",
            target_user_id="user-2",
        )

        assert workspace_event_publisher.await_count == 1
        call_args = workspace_event_publisher.await_args.args
        assert call_args[1] == "workspace_member_left"
        payload = call_args[2]
        assert payload["user_id"] == "user-2"
        assert payload["removed_by"] == "owner-1"

    @pytest.mark.unit
    async def test_bind_agent_new_publishes_agent_bound_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "editor-1",
            WorkspaceRole.EDITOR,
        )
        mock_agent_repo.find_by_workspace.return_value = []
        mock_agent_repo.save.side_effect = lambda relation: relation

        await workspace_service_with_events.bind_agent(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            agent_id="agent-1",
            display_name="Helper",
        )

        assert workspace_event_publisher.await_count == 1
        call_args = workspace_event_publisher.await_args.args
        assert call_args[1] == "workspace_agent_bound"
        payload = call_args[2]
        assert payload["agent_id"] == "agent-1"
        assert payload["is_update"] is False
        assert payload["bound_by"] == "editor-1"

    @pytest.mark.unit
    async def test_bind_agent_update_publishes_agent_bound_event_with_is_update(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
    ) -> None:
        existing = _make_agent_binding(binding_id="wa-existing", agent_id="agent-1")
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "editor-1",
            WorkspaceRole.EDITOR,
        )
        mock_agent_repo.find_by_workspace.return_value = [existing]
        mock_agent_repo.save.side_effect = lambda relation: relation

        await workspace_service_with_events.bind_agent(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            agent_id="agent-1",
            display_name="Renamed Agent",
        )

        assert workspace_event_publisher.await_count == 1
        payload = workspace_event_publisher.await_args.args[2]
        assert payload["is_update"] is True

    @pytest.mark.unit
    async def test_unbind_agent_publishes_agent_unbound_event(
        self,
        workspace_service_with_events,
        workspace_event_publisher: AsyncMock,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
    ) -> None:
        binding = _make_agent_binding(binding_id="wa-1", agent_id="agent-1")
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            "editor-1",
            WorkspaceRole.EDITOR,
        )
        mock_agent_repo.find_by_id.return_value = binding
        mock_agent_repo.delete.return_value = True

        await workspace_service_with_events.unbind_agent(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            workspace_agent_id="wa-1",
        )

        assert workspace_event_publisher.await_count == 1
        call_args = workspace_event_publisher.await_args.args
        assert call_args[1] == "workspace_agent_unbound"
        payload = call_args[2]
        assert payload["agent_id"] == "agent-1"
        assert payload["unbound_by"] == "editor-1"

    @pytest.mark.unit
    async def test_no_publisher_does_not_raise(
        self,
        workspace_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.save.side_effect = lambda workspace: workspace
        mock_member_repo.save.side_effect = lambda member: member

        result = await workspace_service.create_workspace(
            tenant_id="tenant-1",
            project_id="project-1",
            name="No Events",
            created_by="owner-1",
        )

        assert result.name == "No Events"
