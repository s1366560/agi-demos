"""ArcadeDB HA failover rehearsal tests.

Run with the local HA compose file:

    docker compose -f docker-compose.arcadedb-ha.yml up -d
    ARCADEDB_HA_ENABLE_FAILOVER=1 \
      PYTHONPATH=. uv run pytest src/tests/integration/graph/test_arcadedb_ha.py -v

Without ARCADEDB_HA_ENABLE_FAILOVER=1, or when the three Bolt ports are not
reachable, this suite skips so normal CI is unaffected.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="function")]


def _ha_enabled() -> bool:
    return os.environ.get("ARCADEDB_HA_ENABLE_FAILOVER", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ha_uris() -> list[str]:
    raw = os.environ.get(
        "ARCADEDB_HA_URIS",
        "bolt://localhost:7689,bolt://localhost:7690,bolt://localhost:7691",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def _container_names() -> list[str]:
    raw = os.environ.get(
        "ARCADEDB_HA_CONTAINERS",
        "memstack-arcadedb-ha-1,memstack-arcadedb-ha-2,memstack-arcadedb-ha-3",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def _can_reach(uri: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 7687
    try:
        with socket.create_connection((host, port), timeout=2.0):
            return True
    except OSError:
        return False


def _docker_container_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


async def _make_store(uri: str):
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    from src.infrastructure.graph.neo4j_client import Neo4jClient
    from src.infrastructure.graph.stores.arcadedb_graph_store import ArcadeDBGraphStore

    client = Neo4jClient(
        uri=uri,
        user="root",
        password=os.environ.get("ARCADEDB_HA_PASSWORD", "arcadepw"),
        database=os.environ.get("ARCADEDB_HA_DATABASE", "memstack"),
    )
    await client.initialize()
    store = ArcadeDBGraphStore(
        neo4j_client=client,
        llm_client=None,
        embedding_service=EmbeddingService(embedder=_StubEmbedder()),
    )
    await store.initialize_schema()
    return store


async def _wait_for_healthy(uri: str, timeout_seconds: float = 30.0):
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            store = await _make_store(uri)
            if await store.health_probe():
                return store
            await store.close()
        except Exception as exc:
            last_error = exc
        await _async_sleep(1.0)
    raise AssertionError(f"ArcadeDB HA node {uri} did not become healthy: {last_error}")


async def _async_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


class _StubEmbedder:
    embedding_dim = 1536

    async def embed_text(self, _text: str) -> list[float]:
        return [0.0] * self.embedding_dim


async def test_arcadedb_ha_leader_candidate_failover_rehearsal() -> None:
    if not _ha_enabled():
        pytest.skip("Set ARCADEDB_HA_ENABLE_FAILOVER=1 to run ArcadeDB HA rehearsal")

    uris = _ha_uris()
    if len(uris) < 3 or not all(_can_reach(uri) for uri in uris):
        pytest.skip("Three ArcadeDB HA Bolt endpoints are required")

    containers = _container_names()
    if len(containers) < 3 or not _docker_container_exists(containers[0]):
        pytest.skip("Local HA compose containers are required for stop/restart rehearsal")

    before = await _make_store(uris[0])
    canary_project = f"arcadedb-ha-{uuid4()}"
    episode_id = f"episode-{uuid4()}"
    entity_id = f"entity-{uuid4()}"
    try:
        await before.client.execute_query(
            """
            MERGE (ep:Episodic {uuid: $episode_id})
            SET ep.project_id = $project_id, ep.name = $episode_id
            MERGE (en:Entity {uuid: $entity_id})
            SET en.project_id = $project_id, en.name = $entity_id, en.name_summary = $entity_id
            MERGE (ep)-[:MENTIONS]->(en)
            """,
            episode_id=episode_id,
            entity_id=entity_id,
            project_id=canary_project,
        )

        subprocess.run(["docker", "stop", containers[0]], check=True)
        survivor = await _wait_for_healthy(uris[1], timeout_seconds=30.0)
        try:
            await survivor.client.execute_query(
                """
                MERGE (en:Entity {uuid: $entity_id})
                SET en.project_id = $project_id, en.name = $entity_id, en.name_summary = $entity_id
                """,
                entity_id=f"entity-after-failover-{uuid4()}",
                project_id=canary_project,
            )
            result = await survivor.client.execute_query(
                """
                MATCH (en:Entity {project_id: $project_id})
                RETURN count(en) AS entity_count
                """,
                project_id=canary_project,
            )
            assert result.records[0]["entity_count"] >= 2
            assert isinstance(
                await survivor.vector_search(
                    query_vector=[1.0] + [0.0] * 1535,
                    project_id=canary_project,
                    limit=5,
                ),
                list,
            )
            assert isinstance(
                await survivor.fulltext_search(
                    query=entity_id,
                    project_id=canary_project,
                    limit=5,
                ),
                list,
            )
        finally:
            await survivor.close()
    finally:
        subprocess.run(["docker", "start", containers[0]], check=False)
        recovered = await _wait_for_healthy(uris[0], timeout_seconds=30.0)
        try:
            result = await recovered.client.execute_query(
                """
                MATCH (en:Entity {project_id: $project_id})
                RETURN count(en) AS entity_count
                """,
                project_id=canary_project,
            )
            assert result.records[0]["entity_count"] >= 2
            await recovered.client.execute_query(
                """
                MATCH (n {project_id: $project_id})
                DETACH DELETE n
                """,
                project_id=canary_project,
            )
        finally:
            await recovered.close()
            await before.close()
