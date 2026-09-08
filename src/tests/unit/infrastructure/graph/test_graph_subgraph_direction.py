"""Subgraph queries use stored edge direction, including incoming selections."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.graph.stores.arcadedb_graph_store import ArcadeDBGraphStore


@pytest.mark.unit
@pytest.mark.parametrize("adapter_type", [NativeGraphAdapter, ArcadeDBGraphStore])
async def test_neighbor_queries_preserve_stored_direction_and_both_endpoint_scope(
    adapter_type,
) -> None:
    client = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace(records=[])))
    adapter = object.__new__(adapter_type)
    adapter._neo4j_client = client
    await adapter.get_subgraph(
        node_uuids=["target-uuid", "source-uuid"],
        include_neighbors=True,
        limit=30,
        project_id="project-1",
        tenant_id="tenant-1",
        project_ids=["project-1"],
        is_superuser=False,
    )
    query = client.execute_query.await_args.args[0]
    params = client.execute_query.await_args.kwargs
    # Selecting a target uses the stored start/end, never the traversal's n/m ordering.
    assert "CASE WHEN r IS NULL THEN n ELSE startNode(r) END AS source" in query
    assert "CASE WHEN r IS NULL THEN null ELSE endNode(r) END AS target" in query
    assert "elementId(source) AS source_id" in query
    assert "elementId(target) AS target_id" in query
    assert "RETURN DISTINCT" in query
    assert "n.uuid IN $node_uuids" in query
    assert "n.project_id = $project_id" in query
    assert "m.project_id = $project_id" in query
    assert params["node_uuids"] == ["target-uuid", "source-uuid"]
    assert params["project_id"] == "project-1"
    assert params["limit"] == 30


@pytest.mark.unit
async def test_source_lookup_without_neighbors_does_not_traverse_or_resolve_by_name() -> None:
    client = SimpleNamespace(execute_query=AsyncMock(return_value=SimpleNamespace(records=[])))
    adapter = object.__new__(NativeGraphAdapter)
    adapter._neo4j_client = client
    assert (
        await adapter.get_subgraph(
            node_uuids=["episode-uuid"],
            include_neighbors=False,
            limit=10,
            project_id="project-1",
            tenant_id="tenant-1",
            project_ids=["project-1"],
            is_superuser=False,
        )
        == []
    )
    query = client.execute_query.await_args.args[0]
    assert "n.uuid IN $node_uuids" in query
    assert "OPTIONAL MATCH" not in query
    assert "null AS edge_id" in query
    assert "n.name" not in query
