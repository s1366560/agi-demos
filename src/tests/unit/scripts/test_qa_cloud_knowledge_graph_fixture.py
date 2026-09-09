"""Graph QA sample boundaries and production read-route admission."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from scripts.qa_cloud_knowledge_graph_fixture import (
    CAPTURED_CONTENT,
    apply_qa_graph_fixture,
    build_qa_graph_fixture,
    require_qa_fixture_records,
)
from scripts.qa_cloud_knowledge_sync_api import QA_HTTP_ROUTES, select_qa_routes
from scripts.qa_cloud_knowledge_sync_database import PROFILE_ID, QA_DATABASE, QaCloudDatabase
from scripts.qa_cloud_knowledge_sync_graph import QA_NEO4J_URI
from src.domain.model.memory.memory import Memory
from src.domain.model.project.project import Project
from src.infrastructure.graph.neo4j_client import Neo4jClient
from src.infrastructure.plugins.v2.builtin_cloud_knowledge_sync_http_routes import (
    CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2,
)
from src.infrastructure.plugins.v2.builtin_graph_http_routes import graph_route_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2

pytestmark = pytest.mark.unit


@pytest.fixture
def state():
    return QaCloudDatabase(
        database=QA_DATABASE,
        schema="qa_cloud_sync_" + uuid4().hex,
        profile_id=PROFILE_ID,
        profile_digest="a" * 64,
        created_at="2026-09-08T00:00:00+00:00",
        neo4j_uri=QA_NEO4J_URI,
    )


@pytest.fixture
def graph_fixture(state):
    return build_qa_graph_fixture(
        state, tenant_id=str(uuid4()), project_id=str(uuid4()), memory_id=str(uuid4())
    )


def test_fixture_uses_stable_ids_and_actual_source_properties(state, graph_fixture):
    fixture = graph_fixture
    rebuilt = build_qa_graph_fixture(
        state,
        tenant_id=fixture.tenant_id,
        project_id=fixture.project_id,
        memory_id=fixture.memory_id,
    )
    assert fixture.summary() == rebuilt.summary()
    assert len(fixture.nodes) == 5 and len(fixture.edges) == 7
    linked, unlinked, first, second, community = fixture.nodes
    assert linked.content == CAPTURED_CONTENT and linked.memory_id == fixture.memory_id
    assert unlinked.memory_id is None
    assert first.name == second.name and first.uuid != second.uuid
    assert first.tenant_id == second.tenant_id == fixture.tenant_id
    assert fixture.missing_source_uuid not in {node.uuid for node in fixture.nodes}
    forward, reverse, self_edge, membership = fixture.edges[3:]
    assert forward.episodes == [linked.uuid, fixture.missing_source_uuid]
    assert (forward.source_uuid, forward.target_uuid) == (first.uuid, second.uuid)
    assert (reverse.source_uuid, reverse.target_uuid) == (second.uuid, first.uuid)
    assert reverse.episodes == [unlinked.uuid]
    assert self_edge.source_uuid == self_edge.target_uuid == first.uuid
    assert membership.target_uuid == community.uuid and membership.relationship_type == "BELONGS_TO"
    assert "episodes" not in membership.to_neo4j_properties()
    other = build_qa_graph_fixture(
        replace(state, schema="qa_cloud_sync_" + uuid4().hex),
        tenant_id=fixture.tenant_id,
        project_id=fixture.project_id,
        memory_id=fixture.memory_id,
    )
    assert fixture.fixture_id != other.fixture_id


@pytest.mark.parametrize(
    "changes",
    [
        {"database": "memstack"},
        {"schema": "public"},
        {"neo4j_uri": "bolt://127.0.0.1:7687"},
    ],
)
def test_fixture_rejects_non_qa_targets_before_connecting(state, changes):
    with pytest.raises(ValueError):
        build_qa_graph_fixture(
            replace(state, **changes),
            tenant_id=str(uuid4()),
            project_id=str(uuid4()),
            memory_id=str(uuid4()),
        )


def test_fixture_requires_current_project_memory_but_cleanup_allows_deleted_memory(graph_fixture):
    fixture = graph_fixture
    project = Project(
        id=fixture.project_id, tenant_id=fixture.tenant_id, name="QA", owner_id=str(uuid4())
    )
    memory = Memory(
        id=fixture.memory_id,
        project_id=fixture.project_id,
        title="Current",
        content="Changed content",
        author_id=str(uuid4()),
    )
    require_qa_fixture_records(fixture, project, memory, cleanup=False)
    require_qa_fixture_records(fixture, project, None, cleanup=True)
    for invalid_project, invalid_memory in (
        (None, memory),
        (replace(project, tenant_id=str(uuid4())), memory),
        (project, None),
        (project, replace(memory, project_id=str(uuid4()))),
    ):
        with pytest.raises(ValueError):
            require_qa_fixture_records(fixture, invalid_project, invalid_memory, cleanup=False)


async def test_seed_uses_public_production_batch_methods_with_owned_nodes(graph_fixture):
    client = AsyncMock(spec=Neo4jClient)
    client.uri = QA_NEO4J_URI
    client.database = "neo4j"
    client.find_node_by_uuid.return_value = None
    await apply_qa_graph_fixture(client, graph_fixture)
    assert client.find_node_by_uuid.await_count == 5
    client.save_nodes_batch.assert_awaited_once()
    client.save_edges_batch.assert_awaited_once()
    nodes = client.save_nodes_batch.call_args.args[0]
    assert len(nodes) == 5
    assert all(node["properties"]["qa_fixture_id"] == graph_fixture.fixture_id for node in nodes)
    assert all(node["properties"]["project_id"] == graph_fixture.project_id for node in nodes)
    edges = client.save_edges_batch.call_args.args[0]
    assert edges[3]["properties"]["episodes"] == [
        graph_fixture.nodes[0].uuid,
        graph_fixture.missing_source_uuid,
    ]
    client.delete_node.assert_not_awaited()


@pytest.mark.parametrize("cleanup", [False, True])
async def test_all_node_ownership_is_checked_before_any_write(graph_fixture, cleanup):
    client = AsyncMock(spec=Neo4jClient)
    client.uri = QA_NEO4J_URI
    client.database = "neo4j"
    client.find_node_by_uuid.side_effect = [
        None,
        None,
        None,
        None,
        {
            "tenant_id": graph_fixture.tenant_id,
            "project_id": graph_fixture.project_id,
            "qa_fixture_id": "other-fixture",
        },
    ]
    with pytest.raises(ValueError, match="not owned"):
        await apply_qa_graph_fixture(client, graph_fixture, cleanup=cleanup)
    client.save_nodes_batch.assert_not_awaited()
    client.save_edges_batch.assert_not_awaited()
    client.delete_node.assert_not_awaited()


async def test_cleanup_only_deletes_exact_owned_uuids(graph_fixture):
    client = AsyncMock(spec=Neo4jClient)
    client.uri = QA_NEO4J_URI
    client.database = "neo4j"
    client.find_node_by_uuid.return_value = {
        "tenant_id": graph_fixture.tenant_id,
        "project_id": graph_fixture.project_id,
        "qa_fixture_id": graph_fixture.fixture_id,
    }
    await apply_qa_graph_fixture(client, graph_fixture, cleanup=True)
    assert [call.args[0] for call in client.delete_node.await_args_list] == [
        node.uuid for node in graph_fixture.nodes
    ]
    client.save_nodes_batch.assert_not_awaited()
    client.save_edges_batch.assert_not_awaited()


def test_qa_route_selection_preserves_only_two_production_graph_read_handlers():
    graph_routes = graph_route_definitions_v2()
    placeholders = tuple(
        RouteDefinitionV2(
            owner_entry_id="qa-other",
            path=path,
            methods=(method,),
            endpoint=lambda: None,
            name=path,
        )
        for method, path in QA_HTTP_ROUTES
        if not path.startswith("/api/v1/graph/")
    )
    cloud = tuple(
        RouteDefinitionV2(
            owner_entry_id=CLOUD_KNOWLEDGE_SYNC_HTTP_ENTRY_V2,
            path=f"/cloud/{number}",
            methods=("GET",),
            endpoint=lambda: None,
            name=str(number),
        )
        for number in range(11)
    )
    selected = select_qa_routes((*placeholders, *cloud, *graph_routes), host=MagicMock())
    actual = tuple(route for route in selected if route.path.startswith("/api/v1/graph/"))
    expected = tuple(
        route
        for route in graph_routes
        if route.path in {"/api/v1/graph/memory/graph", "/api/v1/graph/memory/graph/subgraph"}
    )
    assert actual == expected and len(actual) == 2
    assert {(method, route.path) for route in actual for method in route.methods} == {
        ("GET", "/api/v1/graph/memory/graph"),
        ("POST", "/api/v1/graph/memory/graph/subgraph"),
    }


@pytest.mark.parametrize("failure", [None, "schema", "memory"])
async def test_command_checks_sql_scope_before_opening_exact_graph_target(
    state, graph_fixture, tmp_path, monkeypatch, failure
):
    from scripts import qa_cloud_knowledge_graph_fixture as module

    path = tmp_path / "metadata.json"
    state.save(path)
    engine = MagicMock()
    engine.dispose = AsyncMock()
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.scalar.return_value = "public" if failure == "schema" else state.schema
    monkeypatch.setattr(module, "qa_engine", lambda _state: engine)
    monkeypatch.setattr(module, "async_sessionmaker", lambda *_args, **_kwargs: lambda: session)
    project = Project(
        id=graph_fixture.project_id,
        tenant_id=graph_fixture.tenant_id,
        name="QA",
        owner_id=str(uuid4()),
    )
    memory = Memory(
        id=graph_fixture.memory_id,
        project_id=graph_fixture.project_id,
        title="Current",
        content="Changed",
        author_id=str(uuid4()),
    )
    project_repo = MagicMock()
    project_repo.find_by_id = AsyncMock(return_value=project)
    memory_repo = MagicMock()
    memory_repo.find_by_id = AsyncMock(return_value=None if failure == "memory" else memory)
    monkeypatch.setattr(module, "SqlProjectRepository", lambda _session: project_repo)
    monkeypatch.setattr(module, "SqlMemoryRepository", lambda _session: memory_repo)
    graph = AsyncMock(spec=Neo4jClient)
    graph.uri = QA_NEO4J_URI
    graph.database = "neo4j"
    graph.__aenter__.return_value = graph
    graph.find_node_by_uuid.return_value = None
    constructor = MagicMock(return_value=graph)
    monkeypatch.setattr(module, "Neo4jClient", constructor)
    arguments = {
        "tenant_id": graph_fixture.tenant_id,
        "project_id": graph_fixture.project_id,
        "memory_id": graph_fixture.memory_id,
    }
    if failure:
        with pytest.raises(ValueError):
            await module.run_qa_graph_fixture(path, **arguments)
        constructor.assert_not_called()
    else:
        result = await module.run_qa_graph_fixture(path, **arguments)
        assert result["operation"] == "seed" and result["fixture_id"] == graph_fixture.fixture_id
        constructor.assert_called_once_with(
            uri=QA_NEO4J_URI, user="", password="", database="neo4j"
        )
        graph.save_nodes_batch.assert_awaited_once()
        graph.save_edges_batch.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.flush.assert_not_awaited()


def test_cli_passes_explicit_scope_without_secrets(monkeypatch, capsys, tmp_path):
    from scripts import qa_cloud_knowledge_graph_fixture as module

    path = tmp_path / "metadata.json"
    runner = AsyncMock(return_value={"operation": "cleanup", "fixture_id": "sample"})
    monkeypatch.setattr(module, "run_qa_graph_fixture", runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "qa_graph",
            "cleanup",
            "--metadata",
            str(path),
            "--tenant-id",
            "tenant",
            "--project-id",
            "project",
            "--memory-id",
            "memory",
        ],
    )
    module.main()
    runner.assert_awaited_once_with(
        path, tenant_id="tenant", project_id="project", memory_id="memory", cleanup=True
    )
    assert '"fixture_id": "sample"' in capsys.readouterr().out


async def test_public_fixture_writer_rejects_a_shared_graph_client(graph_fixture):
    client = AsyncMock(spec=Neo4jClient)
    client.uri = "bolt://127.0.0.1:7687"
    client.database = "neo4j"
    with pytest.raises(ValueError, match="isolated"):
        await apply_qa_graph_fixture(client, graph_fixture)
    client.find_node_by_uuid.assert_not_awaited()
    client.save_nodes_batch.assert_not_awaited()
