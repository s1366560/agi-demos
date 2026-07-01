"""ArcadeDB POC tests (Phase 4).

These verify the ArcadeDB backend against a LIVE ArcadeDB cluster (default
``bolt://localhost:7688`` via ``ARCADEDB_URI``). They are skipped automatically
when no ArcadeDB is reachable, so the suite stays green in CI without one.

POC checklist (mirrors the plan's Phase 4):
1. Bolt connectivity via the ``neo4j`` async driver.
2. OpenCypher CRUD: MERGE/SET/MATCH for an Episodic node.
3. ``ArcadeDBGraphStore.vector_search`` shape parity (VECTOR_INDEX + <-> distance).
4. ``ArcadeDBGraphStore.fulltext_search`` shape parity (Lucene SEARCH).
5. ``initialize_schema`` idempotency (vertex/edge types + vector index).

NOTE: the exact ArcadeDB vector/fulltext syntax in ``ArcadeDBGraphStore`` may
need refinement against a real cluster; these tests document the expected
result shapes and will flag any divergence.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
import pytest_asyncio

# NOTE on loop scope: the suite default is ``asyncio_default_fixture_loop_scope
# = session``, but this module creates its OWN neo4j driver inside the fixture.
# A driver initialized on the session loop cannot be awaited from a function-
# loop test ("Future attached to a different loop"). Pinning the whole module
# (fixture + tests) to the function loop keeps driver creation and use on the
# same loop.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="function"),
]


def _arcadedb_uri() -> str:
    return os.environ.get("ARCADEDB_URI", "bolt://localhost:7688")


def _arcadedb_password() -> str:
    return os.environ.get("ARCADEDB_PASSWORD", "arcadepw")


def _arcadedb_database() -> str:
    return os.environ.get("ARCADEDB_DATABASE", "memstack")


def _can_reach_arcadedb() -> bool:
    """Cheap TCP probe (no driver) so we don't leak a driver across loops.

    Instantiating the neo4j driver in the skip-check binds connection-pool
    futures to whichever loop ran the check, which then collides with the
    test-function loop ("Future attached to a different loop"). A bare socket
    connect avoids that entirely.
    """
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(_arcadedb_uri())
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def _ensure_database_exists() -> None:
    """Create the ArcadeDB database via the HTTP API if it doesn't exist.

    ArcadeDB does NOT auto-create databases on Bolt connect; the database must
    exist before the driver opens a session against it. Creation is idempotent.
    The HTTP host/port is derived from the Bolt URI (same host, port 2480).
    """
    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(_arcadedb_uri())
    host = parsed.hostname or "localhost"
    base = f"http://{host}:2480"
    db = _arcadedb_database()
    auth = ("root", _arcadedb_password())

    # 1) Check existence (GET /api/v1/exists/{db}).
    exists_url = f"{base}/api/v1/exists/{db}"
    req = urllib.request.Request(exists_url)  # noqa: S310  # GET by default
    import base64

    token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            body = resp.read().decode()
            if '"result":true' in body:
                return  # already exists
    except OSError:
        return  # HTTP unreachable -> the Bolt probe would have skipped already
    except Exception:
        pass  # fall through and attempt creation

    # 2) Create via POST /api/v1/server with a server-level SQL command.
    create_url = f"{base}/api/v1/server"
    payload = json.dumps({"command": f"create database {db}"}).encode()
    req2 = urllib.request.Request(create_url, data=payload, method="POST")  # noqa: S310
    req2.add_header("Authorization", f"Basic {token}")
    req2.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req2, timeout=10) as resp:  # noqa: S310
            resp.read()
    except Exception:
        pass  # best-effort; the Bolt session will surface a clear error if missing


@pytest_asyncio.fixture(loop_scope="function")
async def arcadedb_store():
    """Build an ArcadeDBGraphStore against the live cluster (or skip).

    The POC exercises Bolt connectivity, OpenCypher CRUD, schema init and the
    *result shape* of the search primitives (test 3 probes with a zero vector).
    It therefore does NOT need a live LLM/embedding provider: we inject a
    stub embedder and ``None`` llm_client to keep the fixture independent of the
    DB-backed provider-resolution stack.
    """
    if not _can_reach_arcadedb():
        pytest.skip("ArcadeDB not reachable at " + _arcadedb_uri())

    _ensure_database_exists()

    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    from src.infrastructure.graph.neo4j_client import Neo4jClient
    from src.infrastructure.graph.stores.arcadedb_graph_store import ArcadeDBGraphStore

    client = Neo4jClient(
        uri=_arcadedb_uri(),
        user="root",
        password=_arcadedb_password(),
        database=_arcadedb_database(),
    )
    await client.initialize()
    # Stub embedder: the POC never generates real embeddings.
    embedding_service = EmbeddingService(embedder=_StubEmbedder())
    store = ArcadeDBGraphStore(
        neo4j_client=client,
        llm_client=None,
        embedding_service=embedding_service,
    )
    await store.initialize_schema()
    yield store
    await store.close()


class _StubEmbedder:
    """Minimal embedder satisfying ``EmbeddingService``'s duck-typed interface."""

    embedding_dim = 1536

    async def embed_text(self, _text: str) -> list[float]:
        return [0.0] * self.embedding_dim


async def test_bolt_connectivity(arcadedb_store) -> None:
    """(1) Bolt connectivity via neo4j async driver."""
    assert await arcadedb_store.health_probe() is True


async def test_opencypher_crud(arcadedb_store) -> None:
    """(2) OpenCypher MERGE/SET/MATCH round-trip on an Episodic node."""
    name = f"arcade-crud-{uuid4()}"
    await arcadedb_store.client.execute_query(
        "MERGE (e:Episodic {uuid: $uuid}) SET e.name = $name",
        uuid=name,
        name=name,
    )
    result = await arcadedb_store.client.execute_query(
        "MATCH (e:Episodic {uuid: $uuid}) RETURN e.name AS name",
        uuid=name,
    )
    assert result.records and result.records[0]["name"] == name
    # cleanup
    await arcadedb_store.client.execute_query(
        "MATCH (e:Episodic {uuid: $uuid}) DELETE e", uuid=name
    )


async def test_vector_search_result_shape(arcadedb_store) -> None:
    """(3) vector_search returns GraphSearchHit-shaped results."""
    from src.domain.model.graph.dtos import GraphSearchHit

    # Probe with a unit vector (NOT a zero vector — ArcadeDB rejects zero
    # vectors for COSINE similarity: "Query vector cannot be a zero vector").
    # Contract under test is the RESULT SHAPE, not relevance.
    probe = [1.0] + [0.0] * 1535
    hits = await arcadedb_store.vector_search(query_vector=probe, limit=5, project_id=None)
    assert isinstance(hits, list)
    for hit in hits:
        assert isinstance(hit, GraphSearchHit)
        assert isinstance(hit.node, dict)
        assert isinstance(hit.score, (int, float))


async def test_fulltext_search_result_shape(arcadedb_store) -> None:
    """(4) fulltext_search returns GraphSearchHit-shaped results."""
    hits = await arcadedb_store.fulltext_search(query="arcade", limit=5, project_id=None)
    assert isinstance(hits, list)


async def test_schema_initialization_idempotent(arcadedb_store) -> None:
    """(5) initialize_schema is idempotent (safe to call twice)."""
    await arcadedb_store.initialize_schema()  # second call must not raise
