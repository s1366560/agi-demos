from types import SimpleNamespace
from typing import Any

from src.infrastructure.adapters.primary.web.routers.graph import (
    SubgraphRequest,
    get_graph,
    get_subgraph,
)


class FakeNeo4jDateTime:
    def isoformat(self) -> str:
        return "2026-05-16T04:58:00+00:00"


class FakeNeo4jClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[dict[str, Any]] = []

    async def execute_query(self, query: str, **params: Any) -> SimpleNamespace:
        self.calls.append({"query": query, "params": params})
        return SimpleNamespace(records=self.records)


async def test_get_graph_serializes_neo4j_datetime_properties() -> None:
    source_props = {
        "uuid": "source-1",
        "name": "Source",
        "created_at": FakeNeo4jDateTime(),
        "metadata": {"seen_at": FakeNeo4jDateTime()},
        "name_embedding": [0.1, 0.2],
    }
    edge_props = {
        "created_at": FakeNeo4jDateTime(),
        "fact_embedding": [0.3],
    }
    client = FakeNeo4jClient(
        [
            {
                "source_id": "source-id",
                "source_labels": ["Entity"],
                "source_props": source_props,
                "edge_id": "edge-id",
                "edge_type": "RELATES_TO",
                "edge_props": edge_props,
                "target_id": "target-id",
                "target_labels": ["Entity"],
                "target_props": {"uuid": "target-1", "name": "Target"},
            }
        ]
    )

    response = await get_graph(
        project_id="project-1",
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    node = response["elements"]["nodes"][0]["data"]
    assert node["created_at"] == "2026-05-16T04:58:00+00:00"
    assert node["metadata"]["seen_at"] == "2026-05-16T04:58:00+00:00"
    assert "name_embedding" not in node
    assert "name_embedding" in source_props
    assert response["elements"]["edges"][0]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert "fact_embedding" not in response["elements"]["edges"][0]["data"]


async def test_get_subgraph_serializes_node_and_edge_neo4j_datetime_properties() -> None:
    client = FakeNeo4jClient(
        [
            {
                "source_id": "source-id",
                "source_labels": ["Entity"],
                "source_props": {
                    "uuid": "source-1",
                    "name": "Source",
                    "created_at": FakeNeo4jDateTime(),
                    "name_embedding": [0.1],
                },
                "edge_id": "edge-id",
                "edge_type": "RELATES_TO",
                "edge_props": {
                    "created_at": FakeNeo4jDateTime(),
                    "fact_embedding": [0.2],
                },
                "target_id": "target-id",
                "target_labels": ["Entity"],
                "target_props": {
                    "uuid": "target-1",
                    "name": "Target",
                    "created_at": FakeNeo4jDateTime(),
                    "name_embedding": [0.3],
                },
            }
        ]
    )

    response = await get_subgraph(
        SubgraphRequest(node_uuids=["source-1"], project_id="project-1"),
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    nodes = response["elements"]["nodes"]
    edge = response["elements"]["edges"][0]["data"]
    assert nodes[0]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert nodes[1]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert edge["created_at"] == "2026-05-16T04:58:00+00:00"
    assert "name_embedding" not in nodes[0]["data"]
    assert "fact_embedding" not in edge
