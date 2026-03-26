"""Unit tests for TopologyService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType
from src.domain.model.workspace.workspace import Workspace
from src.domain.model.workspace.workspace_member import WorkspaceMember
from src.domain.model.workspace.workspace_role import WorkspaceRole


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
        id=f"wm-{user_id}",
        workspace_id=workspace_id,
        user_id=user_id,
        role=role,
        invited_by="owner-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_node(
    node_id: str,
    workspace_id: str = "ws-1",
    node_type: TopologyNodeType = TopologyNodeType.NOTE,
) -> TopologyNode:
    return TopologyNode(
        id=node_id,
        workspace_id=workspace_id,
        node_type=node_type,
        title=f"Node {node_id}",
        position_x=10.0,
        position_y=20.0,
        data={},
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
def mock_topology_repo() -> MagicMock:
    repo = MagicMock()
    repo.save_node = AsyncMock()
    repo.find_node_by_id = AsyncMock(return_value=None)
    repo.list_nodes_by_workspace = AsyncMock(return_value=[])
    repo.delete_node = AsyncMock(return_value=False)
    repo.save_edge = AsyncMock()
    repo.find_edge_by_id = AsyncMock(return_value=None)
    repo.list_edges_by_workspace = AsyncMock(return_value=[])
    repo.delete_edge = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def topology_service(
    mock_workspace_repo: MagicMock,
    mock_member_repo: MagicMock,
    mock_topology_repo: MagicMock,
):
    from src.application.services.topology_service import TopologyService

    return TopologyService(
        workspace_repo=mock_workspace_repo,
        workspace_member_repo=mock_member_repo,
        topology_repo=mock_topology_repo,
    )


class TestTopologyService:
    @pytest.mark.unit
    async def test_create_node_allows_editor(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_topology_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_topology_repo.save_node.side_effect = lambda node: node

        created = await topology_service.create_node(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            node_type=TopologyNodeType.NOTE,
            title="New node",
            position_x=1.5,
            position_y=2.5,
            data={"x": 1},
        )

        assert created.workspace_id == "ws-1"
        assert created.title == "New node"
        assert created.position_x == 1.5
        assert mock_topology_repo.save_node.await_count == 1

    @pytest.mark.unit
    async def test_create_node_forbidden_for_viewer(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="viewer-1", role=WorkspaceRole.VIEWER
        )

        with pytest.raises(PermissionError, match="permission"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="viewer-1",
                node_type=TopologyNodeType.NOTE,
            )

    @pytest.mark.unit
    async def test_create_edge_rejects_missing_endpoint_nodes(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_topology_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_topology_repo.find_node_by_id.side_effect = [None, _make_node("n-2")]

        with pytest.raises(ValueError, match="Source node"):
            await topology_service.create_edge(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                source_node_id="n-1",
                target_node_id="n-2",
                label="connects",
            )

    @pytest.mark.unit
    async def test_create_edge_rejects_cross_workspace_nodes(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_topology_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace("ws-1")
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_topology_repo.find_node_by_id.side_effect = [
            _make_node("n-1", workspace_id="ws-1"),
            _make_node("n-2", workspace_id="ws-2"),
        ]

        with pytest.raises(ValueError, match="same workspace"):
            await topology_service.create_edge(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                source_node_id="n-1",
                target_node_id="n-2",
            )
