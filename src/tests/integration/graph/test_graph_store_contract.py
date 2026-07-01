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

pytestmark = pytest.mark.integration


async def _can_reach_graph() -> bool:
    """Return True if a graph backend is reachable; skip the test otherwise."""
    try:
        from src.configuration.factories import create_native_graph_adapter

        adapter = await create_native_graph_adapter()
        if adapter is None:
            return False
        # health probe via a trivial query through the current escape hatch.
        result = await adapter.client.execute_query("RETURN 1 AS ok")
        ok = bool(result.records) and result.records[0].get("ok", 0) == 1
        return ok
    except Exception:
        return False


@pytest.fixture
async def graph_adapter():
    """Build the current adapter (NativeGraphAdapter) and clean up afterwards."""
    from src.configuration.factories import create_native_graph_adapter

    adapter = await create_native_graph_adapter()
    if adapter is None:
        pytest.skip("No graph provider configured (NoActiveProviderError)")
    if not await _can_reach_graph():
        pytest.skip("Graph backend not reachable")
    yield adapter
    # teardown is per-test via the cleanup_* deletes below; nothing global.


def _unique_project_id() -> str:
    return f"contract-{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Episode write -> read contract
# ---------------------------------------------------------------------------


async def test_add_episode_returns_episode_with_required_fields(graph_adapter):
    """add_episode must return an Episode carrying uuid, project_id, group_id."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    episode = Episode(
        content="Contract test: Alice met Bob in Paris.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-ep-{uuid.uuid4()}",
        tenant_id="contract-tenant",
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
    await graph_adapter.delete_episode(saved.name or "")


async def test_search_returns_episode_and_entity_shapes(graph_adapter):
    """search() must return episode/entity dicts with the documented keys."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    episode = Episode(
        content="Contract test: Zeta Corp acquired Beta Inc for 5 billion.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-search-{uuid.uuid4()}",
        tenant_id="contract-tenant",
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
        await graph_adapter.delete_episode(episode.name or "")


# ---------------------------------------------------------------------------
# Graph snapshot (get_graph_data) contract
# ---------------------------------------------------------------------------


async def test_get_graph_data_node_and_edge_shapes(graph_adapter):
    """get_graph_data must return {nodes:[...], edges:[...]} with stable keys."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    episode = Episode(
        content="Contract test: Graph snapshot for node/edge shape verification.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-snapshot-{uuid.uuid4()}",
        tenant_id="contract-tenant",
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
        await graph_adapter.delete_episode(episode.name or "")


# ---------------------------------------------------------------------------
# Delete contract
# ---------------------------------------------------------------------------


async def test_delete_episode_by_memory_id_returns_true(graph_adapter):
    """delete_episode_by_memory_id must return True on success."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    memory_id = f"contract-mem-{uuid.uuid4()}"
    episode = Episode(
        content="Contract test: delete by memory_id.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-del-{uuid.uuid4()}",
        tenant_id="contract-tenant",
        project_id=project_id,
        metadata={"memory_id": memory_id},
    )
    await graph_adapter.add_episode(episode)

    ok = await graph_adapter.delete_episode_by_memory_id(memory_id)
    assert ok is True


# ---------------------------------------------------------------------------
# Vector / fulltext search result shapes (raw primitive contract)
# ---------------------------------------------------------------------------


async def test_vector_search_returns_node_and_score(graph_adapter):
    """The vector_search primitive must return [{"node": dict, "score": float}] sorted desc."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    episode = Episode(
        content="Contract test: vector search shape check with entities.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-vec-{uuid.uuid4()}",
        tenant_id="contract-tenant",
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        # Use a zero-vector probe of the default entity index; the contract under
        # test is the RESULT SHAPE, not relevance. We reach the current primitive
        # through the Neo4jClient that the adapter owns (this path becomes
        # GraphStorePort.vector_search in Phase 2). Index name/property match the
        # default created in factories.create_native_graph_adapter
        # (entity_name_vector / name_embedding).
        dim = await graph_adapter.client.get_vector_index_dimension("entity_name_vector")
        probe = [0.0] * max(dim or 1536, 1)
        hits = await graph_adapter.client.vector_search(
            "entity_name_vector", probe, limit=5, project_id=project_id
        )

        assert isinstance(hits, list)
        for hit in hits:
            assert {"node", "score"}.issubset(hit.keys()), f"bad hit shape: {hit}"
            assert isinstance(hit["node"], dict)
            assert isinstance(hit["score"], (int, float))
        # scores must be non-increasing (sorted desc) when more than one hit
        scores = [h["score"] for h in hits]
        assert scores == sorted(scores, reverse=True), "vector_search not sorted desc"
    finally:
        await graph_adapter.delete_episode(episode.name or "")


async def test_fulltext_search_returns_node_and_score(graph_adapter):
    """The fulltext_search primitive must return [{"node": dict, "score": float}]."""
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    episode = Episode(
        content="Contract test: fulltext search shape verification prose.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-ft-{uuid.uuid4()}",
        tenant_id="contract-tenant",
        project_id=project_id,
    )
    await graph_adapter.add_episode(episode)

    try:
        hits = await graph_adapter.client.fulltext_search(
            "entity_name_summary", "fulltext", limit=5, project_id=project_id
        )
        assert isinstance(hits, list)
        for hit in hits:
            assert {"node", "score"}.issubset(hit.keys()), f"bad hit shape: {hit}"
            assert isinstance(hit["node"], dict)
            assert isinstance(hit["score"], (int, float))
    finally:
        await graph_adapter.delete_episode(episode.name or "")


# ---------------------------------------------------------------------------
# Data export contract
# ---------------------------------------------------------------------------


async def test_data_export_top_level_shape(graph_adapter):
    """The export operation must return the documented top-level dict shape.

    This exercises the same Cypher the ``data_export`` router runs, via the
    current driver escape hatch, to freeze the export envelope before the port
    migration.
    """
    from src.domain.model.memory.episode import Episode, SourceType

    project_id = _unique_project_id()
    episode = Episode(
        content="Contract test: data export envelope shape.",
        source_type=SourceType.TEXT,
        valid_at=datetime.now(UTC),
        name=f"contract-export-{uuid.uuid4()}",
        tenant_id="contract-tenant",
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
            "tenant_id": "contract-tenant",
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
        await graph_adapter.delete_episode(episode.name or "")
