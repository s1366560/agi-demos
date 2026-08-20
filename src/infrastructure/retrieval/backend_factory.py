"""Default retrieval backend factory wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.domain.model.retrieval_store import RetrievalStore
from src.infrastructure.retrieval.registry import (
    ENGINE_MEMSTACK_PGVECTOR,
    ENGINE_WEKNORA_REMOTE,
    RetrievalBackendFactory,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService


def build_default_retrieval_factory(
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    embedding_service: EmbeddingService | None = None,
) -> RetrievalBackendFactory:
    """Construct a factory with all v1 retrieval backend builders.

    Builtin builders (memstack_pgvector, weknora_remote) are registered
    first; plugin-provided ``retrieval_backend`` capability rows then
    contribute additional builders keyed by capability id (= engine type).
    With no rows active the factory is byte-identical to the builtin
    composition.
    """
    from src.domain.model.plugins import CapabilityKind
    from src.infrastructure.plugins.backend_runtime import iter_backend_builders
    from src.infrastructure.plugins.runtime_host import (
        get_platform_plugin_runtime_host,
    )

    factory = RetrievalBackendFactory()

    def build_memstack_pgvector(store: RetrievalStore) -> Any:  # noqa: ANN401
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.retrieval.stores import MemstackPgvectorRetrievalStore

        _ = store
        return MemstackPgvectorRetrievalStore(
            session_factory=session_factory or async_session_factory,
            embedding_service=embedding_service,
        )

    def build_weknora_remote(store: RetrievalStore) -> Any:  # noqa: ANN401
        from src.infrastructure.retrieval.stores import WeknoraRemoteRetrievalStore

        return WeknoraRemoteRetrievalStore(store.connection_config)

    factory.register_builder(ENGINE_MEMSTACK_PGVECTOR, build_memstack_pgvector)
    factory.register_builder(ENGINE_WEKNORA_REMOTE, build_weknora_remote)
    for row in iter_backend_builders(
        get_platform_plugin_runtime_host().capabilities,
        CapabilityKind.RETRIEVAL_BACKEND,
    ):
        factory.register_builder(row.capability_id, row.implementation)  # type: ignore[arg-type]
    return factory
