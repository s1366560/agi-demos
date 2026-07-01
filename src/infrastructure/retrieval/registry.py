"""Retrieval backend registry + factory."""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from src.domain.model.retrieval_store import RetrievalStore

logger = logging.getLogger(__name__)

ENGINE_MEMSTACK_PGVECTOR = "memstack_pgvector"
ENGINE_WEKNORA_REMOTE = "weknora_remote"
ENGINE_QDRANT = "qdrant"
ENGINE_MILVUS = "milvus"
ENGINE_WEAVIATE = "weaviate"
ENGINE_ELASTICSEARCH = "elasticsearch"
ENGINE_OPENSEARCH = "opensearch"

VALID_RETRIEVAL_ENGINE_TYPES = frozenset(
    {
        ENGINE_MEMSTACK_PGVECTOR,
        ENGINE_WEKNORA_REMOTE,
        ENGINE_QDRANT,
        ENGINE_MILVUS,
        ENGINE_WEAVIATE,
        ENGINE_ELASTICSEARCH,
        ENGINE_OPENSEARCH,
    }
)

ENV_RETRIEVAL_STORE_ID_PREFIX = "__env_"


class RetrievalStorePortLike(Protocol):
    """Structural type stored by the registry."""

    async def health_probe(self) -> bool: ...

    async def detect_version(self) -> str: ...

    async def close(self) -> None: ...


class RetrievalBackendRegistry:
    """Per-process registry of live retrieval backends."""

    def __init__(self) -> None:
        self._by_engine_type: dict[str, RetrievalStorePortLike] = {}
        self._by_store_id: dict[str, RetrievalStorePortLike] = {}
        self._lock = threading.RLock()

    def register_engine(self, engine_type: str, store: RetrievalStorePortLike) -> None:
        with self._lock:
            existing = self._by_engine_type.get(engine_type)
            if existing is not None and existing is not store:
                logger.warning(
                    "Overwriting env-default retrieval backend for engine %s", engine_type
                )
            self._by_engine_type[engine_type] = store

    def register_store(self, store_id: str, store: RetrievalStorePortLike) -> None:
        with self._lock:
            self._by_store_id[store_id] = store

    def get_by_engine(self, engine_type: str) -> RetrievalStorePortLike | None:
        with self._lock:
            return self._by_engine_type.get(engine_type)

    def get_by_store_id(self, store_id: str) -> RetrievalStorePortLike | None:
        with self._lock:
            return self._by_store_id.get(store_id)

    def unregister_store(self, store_id: str) -> RetrievalStorePortLike | None:
        with self._lock:
            return self._by_store_id.pop(store_id, None)

    def all_store_ids(self) -> list[str]:
        with self._lock:
            return list(self._by_store_id.keys())


class RetrievalBackendBuilder(Protocol):
    """Callable that builds a retrieval backend from a RetrievalStore."""

    def __call__(self, store: RetrievalStore) -> RetrievalStorePortLike: ...


class RetrievalBackendFactory:
    """Build concrete retrieval backends from persisted store metadata."""

    def __init__(self) -> None:
        self._builders: dict[str, RetrievalBackendBuilder] = {}

    def register_builder(self, engine_type: str, builder: RetrievalBackendBuilder) -> None:
        self._builders[engine_type] = builder

    def build(self, store: RetrievalStore) -> RetrievalStorePortLike:
        builder = self._builders.get(store.engine_type)
        if builder is None:
            raise ValueError(
                f"Unsupported retrieval engine type: {store.engine_type!r} "
                f"(known: {sorted(self._builders)})"
            )
        return builder(store)


def env_retrieval_store_id(engine_type: str = ENGINE_MEMSTACK_PGVECTOR) -> str:
    """Synthetic id for an env-default retrieval backend."""
    return f"{ENV_RETRIEVAL_STORE_ID_PREFIX}{engine_type}__"


_registry: RetrievalBackendRegistry | None = None


def get_retrieval_backend_registry() -> RetrievalBackendRegistry:
    global _registry
    if _registry is None:
        _registry = RetrievalBackendRegistry()
    return _registry


def register_env_default_retrieval_store(
    store: RetrievalStorePortLike,
    engine_type: str = ENGINE_MEMSTACK_PGVECTOR,
) -> str:
    registry = get_retrieval_backend_registry()
    store_id = env_retrieval_store_id(engine_type)
    registry.register_engine(engine_type, store)
    registry.register_store(store_id, store)
    return store_id


def get_env_default_retrieval_store(
    engine_type: str = ENGINE_MEMSTACK_PGVECTOR,
) -> RetrievalStorePortLike | None:
    return get_retrieval_backend_registry().get_by_engine(engine_type)


def resolve_bound_retrieval_store_id(project_retrieval_store_id: str | None) -> str:
    if project_retrieval_store_id:
        return project_retrieval_store_id
    return env_retrieval_store_id()
