"""Unit tests for ArcadeDBGraphStore overrides (no live cluster needed).

These exercise the SQL-over-HTTP transport (``_sql``) and the result-shape
transformations of ``initialize_schema`` / ``vector_search`` /
``fulltext_search``. The HTTP layer is mocked; no network access occurs.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.graph.dtos import GraphSearchHit
from src.infrastructure.graph.embedding.embedding_service import NullEmbeddingService
from src.infrastructure.graph.stores.arcadedb_graph_store import ArcadeDBGraphStore


def _make_store() -> ArcadeDBGraphStore:
    """Build a store whose HTTP SQL transport is a fresh AsyncMock.

    The neo4j client carries a real URI string (needed by ``__init__`` to derive
    the HTTP base URL) but is otherwise unused by the overridden primitives.
    """
    client = MagicMock()
    client.uri = "bolt://localhost:7688"
    client.database = "memstack"
    client.user = "root"
    client.password = "arcadepw"
    store = ArcadeDBGraphStore(
        neo4j_client=client,
        llm_client=MagicMock(),
        embedding_service=NullEmbeddingService(),
    )
    store._sql = AsyncMock(return_value=[])
    return store


@pytest.mark.unit
class TestArcadeDBGraphStoreOverrides:
    @pytest.mark.asyncio
    async def test_vector_search_returns_typed_hits(self) -> None:
        store = _make_store()
        # ArcadeDB vectorNeighbors returns rows with a nested ``record`` dict
        # and a ``distance`` float.
        store._sql = AsyncMock(
            return_value=[
                {"record": {"uuid": "e1", "name": "Alice"}, "distance": 0.2},
            ]
        )

        hits = await store.vector_search(query_vector=[0.1, 0.2], limit=5)

        assert len(hits) == 1
        assert isinstance(hits[0], GraphSearchHit)
        # score = 1 - distance (cosine): 1 - 0.2 = 0.8
        assert hits[0].score == pytest.approx(0.8)
        assert hits[0].node["uuid"] == "e1"

    @pytest.mark.asyncio
    async def test_vector_search_inlines_vector_as_sql_literal(self) -> None:
        """The query vector must be inlined (ArcadeDB HTTP drops bound params)."""
        store = _make_store()
        store._sql = AsyncMock(return_value=[])

        await store.vector_search(query_vector=[1.0, 0.5, 0.0], limit=3)

        sql_cmd = store._sql.await_args.args[0]
        # The literal array must appear inline in the command string.
        assert "[1.0,0.5,0.0]" in sql_cmd
        assert "vectorNeighbors('Entity[name_embedding]'" in sql_cmd
        # No bound parameters should be passed.
        assert store._sql.await_args.kwargs == {}

    @pytest.mark.asyncio
    async def test_vector_search_rejects_non_finite_vector(self) -> None:
        store = _make_store()
        with pytest.raises(ValueError):
            await store.vector_search(query_vector=[float("nan"), 0.0], limit=3)

    @pytest.mark.asyncio
    async def test_fulltext_search_returns_typed_hits(self) -> None:
        store = _make_store()
        # SEARCH_INDEX returns the matching records directly (no nested record).
        store._sql = AsyncMock(return_value=[{"uuid": "e2", "name": "Bob"}])

        hits = await store.fulltext_search(query="bob", limit=5)

        assert len(hits) == 1
        assert isinstance(hits[0], GraphSearchHit)
        assert hits[0].node["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_fulltext_search_quotes_query_literal(self) -> None:
        """The query text must be single-quote-escaped inline."""
        store = _make_store()
        store._sql = AsyncMock(return_value=[])

        # The actual SEARCH_INDEX call is the LAST _sql invocation (after the
        # lazy index-ensure calls).
        await store.fulltext_search(query="bob's", limit=5)

        last_call = store._sql.await_args_list[-1]
        sql_cmd = last_call.args[0]
        assert "SEARCH_INDEX('entity_name_summary'" in sql_cmd
        # Embedded single quote must be doubled.
        assert "'bob''s'" in sql_cmd

    @pytest.mark.asyncio
    async def test_initialize_schema_issues_ddl_via_sql(self) -> None:
        store = _make_store()
        store._sql = AsyncMock(return_value=[])

        await store.initialize_schema()

        cmds = [c.args[0] for c in store._sql.await_args_list]
        # Vertex/edge types.
        assert any("CREATE VERTEX TYPE Entity" in c for c in cmds)
        assert any("CREATE EDGE TYPE MENTIONS" in c for c in cmds)
        # Vector property + LSM_VECTOR index.
        assert any("CREATE PROPERTY Entity.name_embedding" in c for c in cmds)
        assert any("LSM_VECTOR" in c and "COSINE" in c for c in cmds)

    @pytest.mark.asyncio
    async def test_initialize_schema_swallows_already_exists_errors(self) -> None:
        store = _make_store()
        # Every DDL statement "fails" (already exists) — must not raise.
        store._sql = AsyncMock(side_effect=RuntimeError("already exists"))
        await store.initialize_schema()
