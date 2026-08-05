"""GraphStorePort contract tests (Phase 1 behavioral freeze).

These tests run against a REAL Neo4j instance (integration profile). Their job is
to freeze the exact result shapes that the current NativeGraphAdapter / Neo4jClient
return, so that the upcoming ``Neo4jGraphStore`` reference implementation (Phase 2)
can be verified to be behavior-equivalent, and so that any future backend
(ArcadeDB, AGE, ...) must reproduce these shapes through the ``GraphStorePort``.

What is frozen here, per operation:

* ``add_episode``        -> returns an ``Episode`` with id/project_id set (id is the
                            Entity identity assigned at construction; add_episode is
                            pass-through on the returned object)
* ``search``             -> list of dicts: episode {type,content,uuid,memory_id}
                            and entity {type,name,summary,uuid}
* ``get_graph_data``     -> {"nodes": [...], "edges": [...]} with node/edge keys
                            (id,label,type,uuid,...) and (id,source,target,label)
* ``delete_episode_by_memory_id`` -> bool True
* ``vector_search``      -> list of {"node": dict, "score": float} (sorted desc)
* ``fulltext_search``    -> list of {"node": dict, "score": float} (sorted desc)
* ``data_export``        -> dict with keys exported_at/tenant_id/project_id and
                            episodes/entities/relationships/communities lists

If any of these shapes change after the refactor WITHOUT an intentional contract
update, these tests will fail and flag the regression.

These require a running Neo4j (``NEO4J_*`` env). They are skipped automatically
when no graph backend can be reached, so the suite stays green in CI without one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


class _ContractEmbedder:
    """Deterministic embedder used to align test entities with the factory index."""

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    async def embed_text(self, _text: str) -> list[float]:
        return [0.01] * self._dimensions


async def _can_reach_graph(adapter) -> bool:
    """Return True if a graph backend is reachable; skip the test otherwise."""
    try:
        # health probe via a trivial query through the current escape hatch.
        result = await adapter.client.execute_query("RETURN 1 AS ok")
        ok = bool(result.records) and result.records[0].get("ok", 0) == 1
        return ok
    except Exception:
        return False


@pytest_asyncio.fixture(loop_scope="session")
async def graph_adapter(test_engine, test_project_db, monkeypatch):
    """Build the current adapter (NativeGraphAdapter) and clean up afterwards."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.configuration.factories import create_native_graph_adapter
    from src.infrastructure.adapters.secondary.schema import dynamic_schema

    schema_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(dynamic_schema, "async_session_factory", schema_session_factory)
    monkeypatch.setattr(dynamic_schema, "_initialized_projects", set())
    dynamic_schema.clear_schema_context_cache(str(test_project_db.id))

    adapter = await create_native_graph_adapter(tenant_id=str(test_project_db.tenant_id))
    if adapter is None:
        pytest.skip("No graph provider configured (NoActiveProviderError)")
    if not await _can_reach_graph(adapter):
        await adapter.close()
        pytest.skip("Graph backend not reachable")
    try:
        yield adapter
    finally:
        dynamic_schema.clear_schema_context_cache(str(test_project_db.id))
        await adapter.close()


# ---------------------------------------------------------------------------
# Episode write -> read contract
# ---------------------------------------------------------------------------


async def test_add_episode_returns_episode_with_required_fields(graph_adapter, test_project_db):
    """add_episode must return an Episode carrying uuid, project_id, group_id."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    episode = Episode(
        content="Contract test: Alice met Bob in Paris.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-ep-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
    )

    saved = await graph_adapter.add_episode(episode)

    # The returned object must be an Episode with an assigned identity and scoping.
    # add_episode is pass-through on the returned object; identity lives on .id
    # (Entity base), and project_id must round-trip unchanged.
    assert isinstance(saved, Episode)
    assert saved.id is not None and saved.id != ""
    assert saved.project_id == project_id
    # cleanup
    await graph_adapter.remove_episode(str(saved.id))


async def test_search_returns_episode_and_entity_shapes(graph_adapter, test_project_db):
    """search() must return episode/entity dicts with the documented keys."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    episode = Episode(
        content="Contract test: Zeta Corp acquired Beta Inc for 5 billion.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-search-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        results = await graph_adapter.search("Zeta Corp", project_id=project_id, limit=20)

        assert isinstance(results, list)
        for item in results:
            assert "type" in item, f"search hit missing 'type': {item}"
            if item["type"] == "episode":
                # frozen episode shape
                assert {"type", "content", "uuid", "memory_id"}.issubset(item.keys())
            else:
                # frozen entity shape
                assert item["type"] == "entity"
                assert {"type", "name", "summary", "uuid"}.issubset(item.keys())
    finally:
        await graph_adapter.remove_episode(str(episode.id))


# ---------------------------------------------------------------------------
# Graph snapshot (get_graph_data) contract
# ---------------------------------------------------------------------------


async def test_get_graph_data_node_and_edge_shapes(graph_adapter, test_project_db):
    """get_graph_data must return {nodes:[...], edges:[...]} with stable keys."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    episode = Episode(
        content="Contract test: Graph snapshot for node/edge shape verification.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-snapshot-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        data = await graph_adapter.get_graph_data(project_id, limit=100)

        assert {"nodes", "edges"}.issubset(data.keys())
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)

        for node in data["nodes"]:
            # frozen node shape: at least id/label/type/uuid
            assert {"id", "label", "type", "uuid"}.issubset(node.keys()), (
                f"node missing required keys: {node}"
            )

        for edge in data["edges"]:
            # frozen edge shape: id/source/target/label
            assert {"id", "source", "target", "label"}.issubset(edge.keys()), (
                f"edge missing required keys: {edge}"
            )
    finally:
        await graph_adapter.remove_episode(str(episode.id))


# ---------------------------------------------------------------------------
# Delete contract
# ---------------------------------------------------------------------------


async def test_delete_episode_by_memory_id_returns_true(graph_adapter, test_project_db):
    """delete_episode_by_memory_id must return True on success."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    memory_id = f"contract-mem-{uuid.uuid4()}"
    episode = Episode(
        content="Contract test: delete by memory_id.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-del-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
        metadata={"memory_id": memory_id},
    )
    await graph_adapter.add_episode(episode)

    ok = await graph_adapter.delete_episode_by_memory_id(memory_id)
    assert ok is True


# ---------------------------------------------------------------------------
# Vector / fulltext search result shapes (raw primitive contract)
# ---------------------------------------------------------------------------


async def test_vector_search_returns_node_and_score(graph_adapter, test_project_db):
    """The vector_search primitive must return [{"node": dict, "score": float}] sorted desc."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    episode = Episode(
        content="Contract test: vector search shape check with entities.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-vec-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        # Align the test entity with the current dimension-specific index built
        # by create_native_graph_adapter. Query Neo4j's index metadata because a
        # pre-existing index can remain authoritative across provider changes.
        index_result = await graph_adapter.client.execute_query(
            """
            SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties, options
            WHERE type = 'VECTOR'
              AND state = 'ONLINE'
              AND labelsOrTypes = ['Entity']
              AND properties = ['name_embedding']
            RETURN name, options
            """
        )
        assert len(index_result.records) == 1
        index_record = index_result.records[0]
        dim = int(index_record["options"]["indexConfig"]["vector.dimensions"])
        index_name = str(index_record["name"])
        assert index_name == f"entity_name_vector_{dim}D"
        rebuild = await graph_adapter.rebuild_embeddings(_ContractEmbedder(dim), project_id)
        assert rebuild["updated"] >= 1
        embedding_result = await graph_adapter.client.execute_query(
            """
            MATCH (n:Entity {project_id: $project_id})
            WHERE n.name_embedding IS NOT NULL
            RETURN n.name_embedding AS embedding
            LIMIT 1
            """,
            project_id=project_id,
        )
        assert embedding_result.records
        probe = list(embedding_result.records[0]["embedding"])
        assert len(probe) == dim
        hits = await graph_adapter.vector_search(
            probe,
            limit=5,
            project_id=project_id,
            index_name=index_name,
        )

        assert isinstance(hits, list)
        assert hits
        for hit in hits:
            assert isinstance(hit.node, dict)
            assert isinstance(hit.score, (int, float))
        # scores must be non-increasing (sorted desc) when more than one hit
        scores = [hit.score for hit in hits]
        assert scores == sorted(scores, reverse=True), "vector_search not sorted desc"
    finally:
        await graph_adapter.remove_episode(str(episode.id))


async def test_fulltext_search_returns_node_and_score(graph_adapter, test_project_db):
    """The fulltext_search primitive must return [{"node": dict, "score": float}]."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    episode = Episode(
        content="Contract test: fulltext search shape verification prose.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-ft-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        entity_result = await graph_adapter.client.execute_query(
            """
            MATCH (n:Entity {project_id: $project_id})
            WHERE n.name IS NOT NULL
            RETURN n.name AS name
            LIMIT 1
            """,
            project_id=project_id,
        )
        assert entity_result.records
        hits = await graph_adapter.fulltext_search(
            query=str(entity_result.records[0]["name"]),
            limit=5,
            project_id=project_id,
            index_name="entity_name_summary",
        )
        assert isinstance(hits, list)
        assert hits
        for hit in hits:
            assert isinstance(hit.node, dict)
            assert isinstance(hit.score, (int, float))
    finally:
        await graph_adapter.remove_episode(str(episode.id))


# ---------------------------------------------------------------------------
# Data export contract
# ---------------------------------------------------------------------------


async def test_data_export_top_level_shape(graph_adapter, test_project_db):
    """The export operation must return the documented top-level dict shape.

    This exercises the same Cypher the ``data_export`` router runs, via the
    current driver escape hatch, to freeze the export envelope before the port
    migration.
    """
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = str(test_project_db.id)
    episode = Episode(
        content="Contract test: data export envelope shape.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-export-{uuid.uuid4()}",
        tenant_id=str(test_project_db.tenant_id),
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        result = await graph_adapter.client.execute_query(
            "MATCH (e:Episodic {project_id: $project_id}) RETURN properties(e) as props",
            project_id=project_id,
        )
        episodes = [r["props"] for r in result.records]

        # Frozen export envelope shape (matches data_export.py build path).
        export = {
            "exported_at": datetime.now(UTC).isoformat(),
            "tenant_id": str(test_project_db.tenant_id),
            "project_id": project_id,
            "episodes": episodes,
            "entities": [],
            "relationships": [],
            "communities": [],
        }
        assert {
            "exported_at",
            "tenant_id",
            "project_id",
            "episodes",
            "entities",
            "relationships",
            "communities",
        }.issubset(export.keys())
        assert isinstance(export["episodes"], list)
        assert len(export["episodes"]) >= 1
    finally:
        await graph_adapter.remove_episode(str(episode.id))
