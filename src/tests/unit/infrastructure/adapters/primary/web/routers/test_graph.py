from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

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


def _store() -> Mock:
    store = Mock()
    store.get_graph_visualization = AsyncMock(return_value=[])
    store.get_subgraph = AsyncMock(return_value=[])
    store.list_entities = AsyncMock(return_value={"entities": [], "total": 0})
    store.list_communities = AsyncMock(return_value={"communities": [], "total": 0})
    store.get_entity_types = AsyncMock(return_value=[])
    return store


def _application(graph_store: object, db: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        db=db if db is not None else SimpleNamespace(),
        services=SimpleNamespace(graph_store=graph_store),
    )


async def test_get_graph_assembles_elements_from_rows() -> None:
    source_props = {
        "uuid": "source-1",
        "name": "Source",
        "entity_type": "Person",
        "created_at": FakeNeo4jDateTime(),
        "metadata": {"seen_at": FakeNeo4jDateTime()},
        "name_embedding": [0.1, 0.2],
    }
    edge_props = {"created_at": FakeNeo4jDateTime(), "fact_embedding": [0.3]}
    rows = [
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
    store = _store()
    store.get_graph_visualization = AsyncMock(return_value=rows)

    response = await get_graph(
        project_id="project-1",
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    node = response["elements"]["nodes"][0]["data"]
    assert node["label"] == "Person"
    assert node["created_at"] == "2026-05-16T04:58:00+00:00"
    assert node["metadata"]["seen_at"] == "2026-05-16T04:58:00+00:00"
    assert "name_embedding" not in node
    assert "name_embedding" in source_props
    assert response["elements"]["edges"][0]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert "fact_embedding" not in response["elements"]["edges"][0]["data"]


async def test_get_graph_forwards_tenant_scope_for_superuser() -> None:
    store = _store()

    response = await get_graph(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response == {"elements": {"nodes": [], "edges": []}}
    kwargs = store.get_graph_visualization.await_args.kwargs
    assert kwargs["tenant_id"] == "tenant-1"
    assert kwargs["is_superuser"] is True


async def test_get_graph_forwards_since_filter() -> None:
    store = _store()

    response = await get_graph(
        project_id="project-1",
        since="2026-05-16T04:58:00+00:00",
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response == {"elements": {"nodes": [], "edges": []}}
    kwargs = store.get_graph_visualization.await_args.kwargs
    assert kwargs["since"] == "2026-05-16T04:58:00+00:00"
    assert kwargs["project_id"] == "project-1"


async def test_get_subgraph_assembles_elements_from_rows() -> None:
    rows = [
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
    store = _store()
    store.get_subgraph = AsyncMock(return_value=rows)

    response = await get_subgraph(
        SubgraphRequest(node_uuids=["source-1"], project_id="project-1"),
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    nodes = response["elements"]["nodes"]
    edge = response["elements"]["edges"][0]["data"]
    assert nodes[0]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert nodes[1]["data"]["created_at"] == "2026-05-16T04:58:00+00:00"
    assert edge["created_at"] == "2026-05-16T04:58:00+00:00"
    assert "name_embedding" not in nodes[0]["data"]
    assert "fact_embedding" not in edge


async def test_list_entities_forwards_entity_type_filter() -> None:
    store = _store()
    store.list_entities = AsyncMock(
        return_value={
            "entities": [{"uuid": "person-1", "name": "Ada", "entity_type": "Person"}],
            "total": 1,
        }
    )

    response = await list_entities(
        project_id="project-1",
        entity_type="Person",
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response["total"] == 1
    assert response["entities"][0]["entity_type"] == "Person"
    kwargs = store.list_entities.await_args.kwargs
    assert kwargs["entity_type"] == "Person"


async def test_list_entities_forwards_tenant_scope_for_superuser() -> None:
    store = _store()

    response = await list_entities(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response["total"] == 0
    kwargs = store.list_entities.await_args.kwargs
    assert kwargs["tenant_id"] == "tenant-1"


async def test_list_communities_forwards_tenant_scope_for_superuser() -> None:
    store = _store()

    response = await list_communities(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response["total"] == 0
    kwargs = store.list_communities.await_args.kwargs
    assert kwargs["tenant_id"] == "tenant-1"


async def test_get_entity_types_returns_store_counts() -> None:
    store = _store()
    store.get_entity_types = AsyncMock(return_value=[{"entity_type": "Person", "count": 2}])

    response = await get_entity_types(
        project_id="project-1",
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response == {"entity_types": [{"entity_type": "Person", "count": 2}], "total": 1}


async def test_get_entity_types_forwards_tenant_scope_for_superuser() -> None:
    store = _store()

    response = await get_entity_types(
        tenant_id="tenant-1",
        project_id=None,
        current_user=SimpleNamespace(is_superuser=True),
        graph_application=_application(store),
    )

    assert response == {"entity_types": [], "total": 0}
    kwargs = store.get_entity_types.await_args.kwargs
    assert kwargs["tenant_id"] == "tenant-1"


@pytest.mark.parametrize(
    ("labels", "expected_type"),
    [
        (["Node", "Artifact", "Entity"], "Entity"),
        (["Community", "Node"], "Community"),
        (["Node", "Episodic"], "Episodic"),
        (["Artifact"], None),
        ([], None),
        (["Entity", "Community"], None),
    ],
)
@pytest.mark.parametrize("operation", ["graph", "subgraph"])
async def test_graph_node_type_uses_structural_labels(
    labels: list[str], expected_type: str | None, operation: str
) -> None:
    props = {
        "name": "Community is only a display name",
        "entity_type": "Artifact",
        "type": "untrusted-business-property",
    }
    rows = [
        {
            "source_id": "source-id",
            "source_labels": labels,
            "source_props": props,
            "edge_id": "edge-id",
            "edge_type": "RELATED_TO",
            "edge_props": {},
            "target_id": "target-id",
            "target_labels": labels,
            "target_props": props,
        }
    ]
    store = _store()
    store.get_graph_visualization.return_value = rows
    store.get_subgraph.return_value = rows
    arguments = {
        "current_user": SimpleNamespace(is_superuser=True),
        "graph_application": _application(store),
    }
    response = (
        await get_graph(project_id="project-1", **arguments)
        if operation == "graph"
        else await get_subgraph(
            SubgraphRequest(node_uuids=["source-id"], project_id="project-1"), **arguments
        )
    )
    for node in response["elements"]["nodes"]:
        assert node["data"]["type"] == expected_type
        assert node["data"]["name"] == props["name"]
        assert node["data"]["entity_type"] == "Artifact"
        if expected_type == "Entity":
            assert node["data"]["label"] == "Artifact"
    assert response["elements"]["edges"][0]["data"]["label"] == "RELATED_TO"
    assert props["type"] == "untrusted-business-property"
