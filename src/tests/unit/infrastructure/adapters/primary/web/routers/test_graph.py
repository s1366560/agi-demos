from types import SimpleNamespace
from typing import Any

from src.infrastructure.adapters.primary.web.routers.graph import (
    SubgraphRequest,
    get_entity_types,
    get_graph,
    get_subgraph,
    list_communities,
    list_entities,
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


class SequentialNeo4jClient:
    def __init__(self, results: list[list[dict[str, Any]]]) -> None:
        self.results = results
        self.calls: list[dict[str, Any]] = []

    async def execute_query(self, query: str, **params: Any) -> SimpleNamespace:
        self.calls.append({"query": query, "params": params})
        records = self.results.pop(0)
        return SimpleNamespace(records=records)


async def test_get_graph_serializes_neo4j_datetime_properties() -> None:
    source_props = {
        "uuid": "source-1",
        "name": "Source",
        "entity_type": "Person",
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
    assert node["label"] == "Person"
    assert node["created_at"] == "2026-05-16T04:58:00+00:00"
    assert node["metadata"]["seen_at"] == "2026-05-16T04:58:00+00:00"
    assert "name_embedding" not in node
    assert "name_embedding" in source_props
    assert response["elements"]["edges"][0]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert "fact_embedding" not in response["elements"]["edges"][0]["data"]


async def test_get_graph_filters_by_tenant_for_superuser_scope() -> None:
    client = FakeNeo4jClient([])

    response = await get_graph(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response == {"elements": {"nodes": [], "edges": []}}
    query = client.calls[0]["query"]
    assert "n.tenant_id = $tenant_id" in query
    assert "m.tenant_id = $tenant_id" in query
    assert client.calls[0]["params"]["tenant_id"] == "tenant-1"


async def test_get_graph_filters_rows_by_since_timestamp() -> None:
    client = FakeNeo4jClient([])

    response = await get_graph(
        project_id="project-1",
        since="2026-05-16T04:58:00+00:00",
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response == {"elements": {"nodes": [], "edges": []}}
    query = client.calls[0]["query"]
    assert "$since IS NULL" in query
    assert "toString(n.updated_at)" in query
    assert "toString(m.updated_at)" in query
    assert "toString(r.updated_at)" in query
    assert client.calls[0]["params"]["since"] == "2026-05-16T04:58:00+00:00"


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


async def test_list_entities_filters_by_entity_type_property_for_historical_nodes() -> None:
    client = SequentialNeo4jClient(
        [
            [{"total": 1}],
            [
                {
                    "props": {
                        "uuid": "person-1",
                        "name": "Ada",
                        "entity_type": "Person",
                    },
                    "labels": ["Entity", "Node"],
                }
            ],
        ]
    )

    response = await list_entities(
        project_id="project-1",
        entity_type="Person",
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response["total"] == 1
    assert response["entities"][0]["entity_type"] == "Person"
    assert "e.entity_type = $entity_type" in client.calls[0]["query"]
    assert client.calls[0]["params"]["entity_type"] == "Person"


async def test_list_entities_filters_by_tenant_for_superuser_scope() -> None:
    client = SequentialNeo4jClient([[{"total": 0}], []])

    response = await list_entities(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response["total"] == 0
    assert "e.tenant_id = $tenant_id" in client.calls[0]["query"]
    assert client.calls[0]["params"]["tenant_id"] == "tenant-1"


async def test_list_communities_filters_by_tenant_for_superuser_scope() -> None:
    client = SequentialNeo4jClient([[{"total": 0}], []])

    response = await list_communities(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response["total"] == 0
    assert "c.tenant_id = $tenant_id" in client.calls[0]["query"]
    assert client.calls[0]["params"]["tenant_id"] == "tenant-1"


async def test_get_entity_types_counts_entity_type_property_for_historical_nodes() -> None:
    client = FakeNeo4jClient([{"entity_type": "Person", "entity_count": 2}])

    response = await get_entity_types(
        project_id="project-1",
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response == {"entity_types": [{"entity_type": "Person", "count": 2}], "total": 1}
    assert "coalesce(" in client.calls[0]["query"]
    assert "head([label IN labels(e)" in client.calls[0]["query"]


async def test_get_entity_types_filters_by_tenant_for_superuser_scope() -> None:
    client = FakeNeo4jClient([])

    response = await get_entity_types(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        neo4j_client=client,
    )

    assert response == {"entity_types": [], "total": 0}
    assert "e.tenant_id = $tenant_id" in client.calls[0]["query"]
    assert client.calls[0]["params"]["tenant_id"] == "tenant-1"
