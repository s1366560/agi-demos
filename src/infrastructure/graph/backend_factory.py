"""Graph backend builders + default factory wiring.

Builds concrete ``GraphStorePort`` instances from ``GraphStore`` domain entities.
Two builders are registered:
- ``ENGINE_NEO4J``: NativeGraphAdapter (reference implementation).
- ``ENGINE_ARCADEDB``: ArcadeDBGraphStore (Phase 4 POC; Bolt-compatible).
"""

from __future__ import annotations

import logging
from typing import Any, cast

from src.domain.model.graph_store.graph_store import GraphStore
from src.infrastructure.graph.registry import (
    ENGINE_ARCADEDB,
    ENGINE_NEO4J,
    GraphBackendBuilder,
    GraphBackendFactory,
)

logger = logging.getLogger(__name__)


async def _build_native_adapter(neo4j_client: Any, tenant_id: str | None) -> Any:  # noqa: ANN401
    """Build a full NativeGraphAdapter (LLM + embedder + indices) over a client."""
    from src.configuration.factories import create_native_graph_adapter

    await neo4j_client.initialize()
    return await create_native_graph_adapter(tenant_id=tenant_id, neo4j_client=neo4j_client)


def build_neo4j_backend(store: GraphStore) -> Any:  # noqa: ANN401
    """Build a Neo4j graph backend (NativeGraphAdapter) from a GraphStore."""
    import asyncio

    from src.configuration.config import get_settings
    from src.infrastructure.graph.neo4j_client import Neo4jClient

    config = store.connection_config or {}
    settings = get_settings()
    client = Neo4jClient(
        uri=config.get("uri") or settings.effective_graph_store_uri,
        user=config.get("user") or settings.effective_graph_store_user,
        password=config.get("password") or settings.effective_graph_store_password,
    )

    try:
        asyncio.get_running_loop()
        return _build_native_adapter(client, tenant_id=None)
    except RuntimeError:
        return asyncio.run(_build_native_adapter(client, tenant_id=None))


def build_arcadedb_backend(store: GraphStore) -> Any:  # noqa: ANN401
    """Build an ArcadeDB graph backend from a GraphStore.

    ArcadeDB speaks OpenCypher over Bolt (port 7687, mapped to 7688 on the dev
    host to avoid clashing with Neo4j) for CRUD, plus SQL over HTTP (port 2480)
    for DDL and the vector/fulltext functions. The HTTP endpoint + database are
    derived inside ``ArcadeDBGraphStore`` from the Bolt client's URI/creds, but
    can be overridden via the store's ``connection_config``.
    """
    import asyncio

    from src.configuration.factories import create_llm_client
    from src.infrastructure.graph.embedding.embedding_service import (
        EmbedderProtocol,
        EmbeddingService,
    )
    from src.infrastructure.graph.neo4j_client import Neo4jClient
    from src.infrastructure.graph.stores.arcadedb_graph_store import ArcadeDBGraphStore
    from src.infrastructure.llm.provider_factory import get_ai_service_factory

    config = store.connection_config or {}
    # ArcadeDB requires the database name to select a graph at session time.
    database = config.get("database") or "memstack"
    client = Neo4jClient(
        uri=config.get("uri") or "bolt://localhost:7688",
        user=config.get("user") or "root",
        password=config.get("password") or "arcadepw",
        database=database,
    )
    http_base_url = config.get("http_base_url")
    http_auth = None
    if config.get("http_user") and config.get("http_password") is not None:
        http_auth = (config["http_user"], config["http_password"])

    async def _build() -> Any:  # noqa: ANN401
        await client.initialize()
        # Resolve an LLM + embedder for entity extraction (same as Neo4j path).
        llm_client = await create_llm_client(None)
        factory = get_ai_service_factory()
        provider_config = await factory.resolve_embedding_provider()
        embedder = factory.create_embedder(provider_config)
        embedding_service = EmbeddingService(embedder=cast(EmbedderProtocol, embedder))
        store_impl = ArcadeDBGraphStore(
            neo4j_client=client,
            llm_client=llm_client,
            embedding_service=embedding_service,
            http_base_url=http_base_url,
            http_database=database,
            http_auth=http_auth,
        )
        await store_impl.initialize_schema()
        return store_impl

    try:
        asyncio.get_running_loop()
        return _build()
    except RuntimeError:
        return asyncio.run(_build())


def build_default_factory() -> GraphBackendFactory:
    """Construct the default factory with all registered backend builders."""
    factory = GraphBackendFactory()
    factory.register_builder(ENGINE_NEO4J, build_neo4j_backend)
    factory.register_builder(ENGINE_ARCADEDB, build_arcadedb_backend)
    # Apache AGE (Postgres) is a future builder.
    return factory


def make_builder(engine_type: str) -> GraphBackendBuilder | None:
    """Return the builder for an engine type, or None if unsupported."""
    if engine_type == ENGINE_NEO4J:
        return build_neo4j_backend
    if engine_type == ENGINE_ARCADEDB:
        return build_arcadedb_backend
    return None
