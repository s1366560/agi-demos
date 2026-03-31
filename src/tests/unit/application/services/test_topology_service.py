"""Unit tests for TopologyService."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType
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
    hex_q: int | None = None,
    hex_r: int | None = None,
) -> TopologyNode:
    return TopologyNode(
        id=node_id,
        workspace_id=workspace_id,
        node_type=node_type,
        title=f"Node {node_id}",
        position_x=10.0,
        position_y=20.0,
        hex_q=hex_q,
        hex_r=hex_r,
        data={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_edge(edge_id: str = "edge-1", node_id: str = "node-1") -> TopologyEdge:
    return TopologyEdge(
        id=edge_id,
        workspace_id="ws-1",
        source_node_id=node_id,
        target_node_id="node-2",
        source_hex_q=1,
        source_hex_r=-1,
        target_hex_q=2,
        target_hex_r=-1,
        data={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_agent(binding_id: str = "wa-1", hex_q: int = 2, hex_r: int = -1) -> WorkspaceAgent:
    return WorkspaceAgent(
        id=binding_id,
        workspace_id="ws-1",
        agent_id="agent-1",
        display_name="Agent One",
        config={},
        is_active=True,
        hex_q=hex_q,
        hex_r=hex_r,
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
    repo.acquire_hex_lock = AsyncMock(return_value=None)
    repo.save_node = AsyncMock()
    repo.find_node_by_id = AsyncMock(return_value=None)
    repo.list_nodes_by_workspace = AsyncMock(return_value=[])
    repo.list_all_nodes_by_workspace = AsyncMock(return_value=[])
    repo.list_nodes_by_hex = AsyncMock(return_value=[])
    repo.delete_node = AsyncMock(return_value=False)
    repo.save_edge = AsyncMock()
    repo.find_edge_by_id = AsyncMock(return_value=None)
    repo.list_edges_by_workspace = AsyncMock(return_value=[])
    repo.list_all_edges_by_workspace = AsyncMock(return_value=[])
    repo.list_edges_for_node = AsyncMock(return_value=[])
    repo.sync_edge_coordinates_for_node = AsyncMock(return_value=None)
    repo.delete_edge = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    repo = MagicMock()
    repo.find_by_workspace_and_hex = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def topology_service(
    mock_workspace_repo: MagicMock,
    mock_member_repo: MagicMock,
    mock_topology_repo: MagicMock,
    mock_agent_repo: MagicMock,
):
    from src.application.services.topology_service import TopologyService

    return TopologyService(
        workspace_repo=mock_workspace_repo,
        workspace_member_repo=mock_member_repo,
        topology_repo=mock_topology_repo,
        workspace_agent_repo=mock_agent_repo,
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
    async def test_create_node_rejects_reserved_center_hex(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )

        with pytest.raises(ValueError, match="reserved"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                node_type=TopologyNodeType.NOTE,
                hex_q=0,
                hex_r=0,
            )

    @pytest.mark.unit
    async def test_create_node_rejects_hex_occupied_by_agent(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_agent_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_agent_repo.find_by_workspace_and_hex.return_value = [_make_agent()]

        with pytest.raises(ValueError, match="occupied"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                node_type=TopologyNodeType.NOTE,
                hex_q=2,
                hex_r=-1,
            )

    @pytest.mark.unit
    async def test_create_node_rejects_oversized_data_payload(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )

        with pytest.raises(ValueError, match="Topology data"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                node_type=TopologyNodeType.NOTE,
                data={"blob": "x" * 3000},
            )

    @pytest.mark.unit
    async def test_create_node_rejects_out_of_bounds_hex(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )

        with pytest.raises(ValueError, match="hex_q"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                node_type=TopologyNodeType.NOTE,
                hex_q=25,
                hex_r=0,
            )

    @pytest.mark.unit
    async def test_create_node_rejects_non_finite_position(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )

        with pytest.raises(ValueError, match="finite"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                node_type=TopologyNodeType.NOTE,
                position_x=float("inf"),
            )

    @pytest.mark.unit
    async def test_create_node_rejects_non_finite_data_numbers(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
    ) -> None:
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )

        with pytest.raises(ValueError, match="finite"):
            await topology_service.create_node(
                workspace_id="ws-1",
                actor_user_id="editor-1",
                node_type=TopologyNodeType.NOTE,
                data={"weight": float("nan")},
            )

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
    async def test_update_node_syncs_connected_edge_coordinates_when_hex_changes(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_topology_repo: MagicMock,
    ) -> None:
        node = _make_node("node-1", hex_q=1, hex_r=-1)
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_topology_repo.find_node_by_id.return_value = node
        mock_topology_repo.save_node.side_effect = lambda saved_node: saved_node

        updated = await topology_service.update_node(
            workspace_id="ws-1",
            node_id="node-1",
            actor_user_id="editor-1",
            hex_q=4,
            hex_r=-2,
        )

        assert updated.hex_q == 4
        assert updated.hex_r == -2
        assert mock_topology_repo.sync_edge_coordinates_for_node.await_count == 1
        assert mock_topology_repo.sync_edge_coordinates_for_node.await_args.kwargs == {
            "workspace_id": "ws-1",
            "node_id": "node-1",
            "hex_q": 4,
            "hex_r": -2,
        }

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

    @pytest.mark.unit
    async def test_create_edge_uses_authoritative_endpoint_hexes(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_topology_repo: MagicMock,
    ) -> None:
        source = _make_node("n-1", hex_q=3, hex_r=-1)
        target = _make_node("n-2", hex_q=4, hex_r=0)
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_topology_repo.find_node_by_id.side_effect = [source, target]
        mock_topology_repo.save_edge.side_effect = lambda edge: edge

        created = await topology_service.create_edge(
            workspace_id="ws-1",
            actor_user_id="editor-1",
            source_node_id="n-1",
            target_node_id="n-2",
            source_hex_q=999,
            source_hex_r=999,
            target_hex_q=999,
            target_hex_r=999,
        )

        assert created.source_hex_q == 3
        assert created.source_hex_r == -1
        assert created.target_hex_q == 4
        assert created.target_hex_r == 0

    @pytest.mark.unit
    async def test_update_edge_uses_authoritative_endpoint_hexes(
        self,
        topology_service,
        mock_workspace_repo: MagicMock,
        mock_member_repo: MagicMock,
        mock_topology_repo: MagicMock,
    ) -> None:
        source = _make_node("n-1", hex_q=3, hex_r=-1)
        target = _make_node("n-2", hex_q=4, hex_r=0)
        edge = _make_edge(edge_id="edge-1", node_id="n-1")
        edge.target_node_id = "n-2"
        mock_workspace_repo.find_by_id.return_value = _make_workspace()
        mock_member_repo.find_by_workspace_and_user.return_value = _make_member(
            user_id="editor-1", role=WorkspaceRole.EDITOR
        )
        mock_topology_repo.find_edge_by_id.return_value = edge
        mock_topology_repo.find_node_by_id.side_effect = [source, target]
        mock_topology_repo.save_edge.side_effect = lambda saved_edge: saved_edge

        updated = await topology_service.update_edge(
            workspace_id="ws-1",
            edge_id="edge-1",
            actor_user_id="editor-1",
            source_hex_q=999,
            source_hex_r=999,
            target_hex_q=999,
            target_hex_r=999,
        )

        assert updated.source_hex_q == 3
        assert updated.source_hex_r == -1
        assert updated.target_hex_q == 4
        assert updated.target_hex_r == 0

    @pytest.mark.unit
    async def test_list_all_nodes_uses_unpaginated_repository_method(
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
        mock_topology_repo.list_all_nodes_by_workspace.return_value = [_make_node("n-1")]

        nodes = await topology_service.list_all_nodes("ws-1", "editor-1")

        assert [node.id for node in nodes] == ["n-1"]
        mock_topology_repo.list_all_nodes_by_workspace.assert_awaited_once_with("ws-1")
