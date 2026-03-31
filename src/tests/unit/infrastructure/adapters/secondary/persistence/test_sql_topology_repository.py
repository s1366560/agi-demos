"""Tests for SqlTopologyRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.topology_edge import TopologyEdge
from src.domain.model.workspace.topology_node import TopologyNode, TopologyNodeType
from src.infrastructure.adapters.secondary.persistence.sql_topology_repository import (
    SqlTopologyRepository,
)


@pytest.fixture
async def v2_topology_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlTopologyRepository:
    """Create a SqlTopologyRepository for testing."""
    return SqlTopologyRepository(v2_db_session)


def make_node(
    node_id: str,
    workspace_id: str = "workspace-1",
    node_type: TopologyNodeType = TopologyNodeType.USER,
    ref_id: str | None = None,
) -> TopologyNode:
    return TopologyNode(
        id=node_id,
        workspace_id=workspace_id,
        node_type=node_type,
        ref_id=ref_id,
        title=f"Node {node_id}",
        position_x=10.0,
        position_y=20.0,
        data={"color": "blue"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def make_edge(
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    workspace_id: str = "workspace-1",
) -> TopologyEdge:
    return TopologyEdge(
        id=edge_id,
        workspace_id=workspace_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        label="connects",
        data={"weight": 1},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestSqlTopologyRepository:
    """Tests for topology repository node and edge operations."""

    @pytest.mark.asyncio
    async def test_save_and_find_node(self, v2_topology_repo: SqlTopologyRepository) -> None:
        node = make_node("node-1")
        await v2_topology_repo.save_node(node)

        found = await v2_topology_repo.find_node_by_id("node-1")
        assert found is not None
        assert found.id == "node-1"
        assert found.workspace_id == "workspace-1"
        assert found.node_type == TopologyNodeType.USER

    @pytest.mark.asyncio
    async def test_list_nodes_by_workspace(self, v2_topology_repo: SqlTopologyRepository) -> None:
        await v2_topology_repo.save_node(make_node("node-a", workspace_id="workspace-a"))
        await v2_topology_repo.save_node(make_node("node-b", workspace_id="workspace-a"))
        await v2_topology_repo.save_node(make_node("node-c", workspace_id="workspace-b"))

        nodes = await v2_topology_repo.list_nodes_by_workspace("workspace-a")
        assert len(nodes) == 2
        assert {node.id for node in nodes} == {"node-a", "node-b"}

    @pytest.mark.asyncio
    async def test_list_all_nodes_and_nodes_by_hex(
        self, v2_topology_repo: SqlTopologyRepository
    ) -> None:
        node_a = make_node("node-a", workspace_id="workspace-a")
        node_a.hex_q = 2
        node_a.hex_r = -1
        node_b = make_node("node-b", workspace_id="workspace-a")
        node_b.hex_q = 3
        node_b.hex_r = -1
        await v2_topology_repo.save_node(node_a)
        await v2_topology_repo.save_node(node_b)

        all_nodes = await v2_topology_repo.list_all_nodes_by_workspace("workspace-a")
        occupied = await v2_topology_repo.list_nodes_by_hex("workspace-a", 2, -1)

        assert {node.id for node in all_nodes} == {"node-a", "node-b"}
        assert [node.id for node in occupied] == ["node-a"]

    @pytest.mark.asyncio
    async def test_save_and_find_edge(self, v2_topology_repo: SqlTopologyRepository) -> None:
        await v2_topology_repo.save_node(make_node("node-src"))
        await v2_topology_repo.save_node(make_node("node-dst", node_type=TopologyNodeType.AGENT))

        edge = make_edge("edge-1", source_node_id="node-src", target_node_id="node-dst")
        await v2_topology_repo.save_edge(edge)

        found = await v2_topology_repo.find_edge_by_id("edge-1")
        assert found is not None
        assert found.id == "edge-1"
        assert found.source_node_id == "node-src"
        assert found.target_node_id == "node-dst"

    @pytest.mark.asyncio
    async def test_list_edges_by_workspace(self, v2_topology_repo: SqlTopologyRepository) -> None:
        await v2_topology_repo.save_node(make_node("node-1", workspace_id="workspace-list"))
        await v2_topology_repo.save_node(make_node("node-2", workspace_id="workspace-list"))
        await v2_topology_repo.save_node(make_node("node-3", workspace_id="workspace-other"))

        await v2_topology_repo.save_edge(
            make_edge(
                "edge-a",
                source_node_id="node-1",
                target_node_id="node-2",
                workspace_id="workspace-list",
            )
        )
        await v2_topology_repo.save_edge(
            make_edge(
                "edge-b",
                source_node_id="node-3",
                target_node_id="node-3",
                workspace_id="workspace-other",
            )
        )

        edges = await v2_topology_repo.list_edges_by_workspace("workspace-list")
        assert len(edges) == 1
        assert edges[0].id == "edge-a"

    @pytest.mark.asyncio
    async def test_list_all_edges_and_edges_for_node(
        self, v2_topology_repo: SqlTopologyRepository
    ) -> None:
        await v2_topology_repo.save_node(make_node("node-1", workspace_id="workspace-list"))
        await v2_topology_repo.save_node(make_node("node-2", workspace_id="workspace-list"))
        await v2_topology_repo.save_node(make_node("node-3", workspace_id="workspace-list"))

        await v2_topology_repo.save_edge(
            make_edge(
                "edge-a",
                source_node_id="node-1",
                target_node_id="node-2",
                workspace_id="workspace-list",
            )
        )
        await v2_topology_repo.save_edge(
            make_edge(
                "edge-b",
                source_node_id="node-3",
                target_node_id="node-1",
                workspace_id="workspace-list",
            )
        )

        all_edges = await v2_topology_repo.list_all_edges_by_workspace("workspace-list")
        node_edges = await v2_topology_repo.list_edges_for_node("workspace-list", "node-1")

        assert {edge.id for edge in all_edges} == {"edge-a", "edge-b"}
        assert {edge.id for edge in node_edges} == {"edge-a", "edge-b"}

    @pytest.mark.asyncio
    async def test_delete_node_and_edge(self, v2_topology_repo: SqlTopologyRepository) -> None:
        await v2_topology_repo.save_node(make_node("node-x"))
        await v2_topology_repo.save_node(make_node("node-y"))
        await v2_topology_repo.save_edge(
            make_edge("edge-x", source_node_id="node-x", target_node_id="node-y")
        )

        assert await v2_topology_repo.delete_edge("edge-x") is True
        assert await v2_topology_repo.find_edge_by_id("edge-x") is None

        assert await v2_topology_repo.delete_node("node-x") is True
        assert await v2_topology_repo.find_node_by_id("node-x") is None
