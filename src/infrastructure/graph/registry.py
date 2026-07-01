"""Graph backend registry + factory.

Mirrors the WeKnora vector-store two-axis registry:
- ``by_engine_type``: the env-default backend (one per engine; created at startup
  from ``GRAPH_STORE_*`` / ``NEO4J_*`` config).
- ``by_store_id``: DB-managed backends (``graph_stores`` rows); upsert semantics
  allow many backends of the same engine type.

``GraphBackendFactory`` dispatches on ``engine_type`` to build a concrete
``GraphStorePort`` from a ``GraphStore`` domain entity. Today only ``neo4j`` is
implemented; ArcadeDB (Phase 4) plugs in as another case.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from src.domain.model.graph_store.graph_store import GraphStore

logger = logging.getLogger(__name__)

# Engine type constants. Add new engines here (and a factory case) to extend.
ENGINE_NEO4J = "neo4j"
ENGINE_ARCADEDB = "arcadedb"
ENGINE_AGE = "age"  # Apache AGE (Postgres) - future
VALID_GRAPH_ENGINE_TYPES = frozenset({ENGINE_NEO4J, ENGINE_ARCADEDB, ENGINE_AGE})

# Synthetic id prefix for env-default backends (never persisted as DB rows).
ENV_STORE_ID_PREFIX = "__env_"


class GraphStorePortLike(Protocol):
    """Structural type for the registry's stored values (a GraphStorePort)."""

    async def close(self) -> None: ...


class GraphBackendRegistry:
    """In-process registry of live graph backends, keyed by engine + store id.

    Thread-safe. Per-process: sibling replicas keep their own cache until restart
    (same limitation as WeKnora's StoreRegistry).
    """

    def __init__(self) -> None:
        self._by_engine_type: dict[str, GraphStorePortLike] = {}
        self._by_store_id: dict[str, GraphStorePortLike] = {}
        self._lock = threading.RLock()

    def register_engine(self, engine_type: str, store: GraphStorePortLike) -> None:
        """Register/replace the env-default backend for an engine type."""
        with self._lock:
            existing = self._by_engine_type.get(engine_type)
            if existing is not None and existing is not store:
                logger.warning(
                    "Overwriting env-default graph backend for engine %s", engine_type
                )
            self._by_engine_type[engine_type] = store

    def register_store(self, store_id: str, store: GraphStorePortLike) -> None:
        """Register/replace (upsert) a DB-managed backend by store id."""
        with self._lock:
            self._by_store_id[store_id] = store

    def get_by_engine(self, engine_type: str) -> GraphStorePortLike | None:
        with self._lock:
            return self._by_engine_type.get(engine_type)

    def get_by_store_id(self, store_id: str) -> GraphStorePortLike | None:
        with self._lock:
            return self._by_store_id.get(store_id)

    def unregister_store(self, store_id: str) -> GraphStorePortLike | None:
        with self._lock:
            return self._by_store_id.pop(store_id, None)

    def is_env_store_id(self, store_id: str) -> bool:
        return store_id.startswith(ENV_STORE_ID_PREFIX)

    def all_store_ids(self) -> list[str]:
        with self._lock:
            return list(self._by_store_id.keys())


class GraphBackendFactory:
    """Builds a concrete ``GraphStorePort`` for a ``GraphStore`` domain entity.

    Dispatches on ``engine_type``. Each builder reads the connection config and
    constructs the backend-specific client + adapter.
    """

    def __init__(self) -> None:
        self._builders: dict[str, GraphBackendBuilder] = {}

    def register_builder(self, engine_type: str, builder: GraphBackendBuilder) -> None:
        self._builders[engine_type] = builder

    def build(self, store: GraphStore) -> GraphStorePortLike:
        """Build a live backend for ``store``; raises on unknown engine type."""
        builder = self._builders.get(store.engine_type)
        if builder is None:
            raise ValueError(
                f"Unsupported graph engine type: {store.engine_type!r} "
                f"(known: {sorted(self._builders)})"
            )
        return builder(store)


class GraphBackendBuilder(Protocol):
    """Callable that builds a GraphStorePort from a GraphStore domain entity."""

    def __call__(self, store: GraphStore) -> GraphStorePortLike: ...


# --- Module-level singleton registry + default factory wiring ---


def env_store_id(engine_type: str) -> str:
    """Synthetic id for the env-default backend of an engine type."""
    return f"{ENV_STORE_ID_PREFIX}{engine_type}__"


# Module-global registry (per-process). Wired during app startup.
_registry: GraphBackendRegistry | None = None


def get_graph_backend_registry() -> GraphBackendRegistry:
    """Return the process-global registry (lazy-initialized)."""
    global _registry
    if _registry is None:
        _registry = GraphBackendRegistry()
    return _registry


# --- Env-default store wiring (called once at startup) ---


def register_env_default_store(store: GraphStorePortLike) -> str:
    """Register the env-default graph backend (built at startup from settings).

    Returns the synthetic env store id used for the binding. The same backend
    instance is also registered by store id so callers that resolve a project's
    graph_store_id to the env default still find it.
    """
    registry = get_graph_backend_registry()
    store_id = env_store_id("neo4j")
    registry.register_engine("neo4j", store)
    registry.register_store(store_id, store)
    return store_id


def get_env_default_store() -> GraphStorePortLike | None:
    """Return the env-default graph backend, or None if not wired."""
    return get_graph_backend_registry().get_by_engine("neo4j")


def resolve_bound_store_id(project_graph_store_id: str | None) -> str | None:
    """Return the effective store id for a project's binding.

    A null binding resolves to the env-default store id (so callers can always
    look up a concrete id). Used by routers that have the Project row in hand.
    """
    if project_graph_store_id:
        return project_graph_store_id
    return env_store_id("neo4j")
