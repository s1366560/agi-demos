"""GraphStoreService: business logic for pluggable graph-backend management.

Handles CRUD over ``graph_stores`` rows, connection testing (with SSRF guard),
delete protection (reject when projects are still bound), and secret masking in
display projections. Mirrors WeKnora's ``VectorStoreService`` surface.

The service works against the ``GraphStoreRepository`` port and the
``GraphBackendRegistry``/``GraphBackendFactory``; it does not own Neo4j clients
directly (the factory builds them on demand for connection tests).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from src.domain.model.graph_store.graph_store import GraphStore
from src.domain.ports.repositories.graph_store_repository import GraphStoreRepository
from src.domain.shared_kernel import DomainException
from src.infrastructure.graph.registry import (
    VALID_GRAPH_ENGINE_TYPES,
    GraphBackendFactory,
    GraphBackendRegistry,
)

logger = logging.getLogger(__name__)

# Redacted placeholder for masked secrets in API responses.
REDACTED_SECRET = "***"


class GraphStoreNotFound(DomainException):
    """Raised when a graph store id is not found under the tenant."""


class GraphStoreNameConflict(DomainException):
    """Raised when a store name is already in use within the tenant."""


class GraphStoreInUse(DomainException):
    """Raised on delete when projects are still bound to the store."""


class GraphStoreValidationError(DomainException):
    """Raised on invalid engine type, missing required fields, or SSRF risk."""


@dataclass(frozen=True)
class StoreDisplay:
    """A graph-store projection for API responses (secrets masked)."""

    id: str
    tenant_id: str
    name: str
    engine_type: str
    status: str
    health_status: str | None
    detected_version: str | None
    connection_config: dict[str, Any]  # masked
    index_config: dict[str, Any]
    created_at: Any
    updated_at: Any
    source: str = "user"
    readonly: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "engine_type": self.engine_type,
            "status": self.status,
            "health_status": self.health_status,
            "detected_version": self.detected_version,
            "connection_config": self.connection_config,
            "index_config": self.index_config,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "readonly": self.readonly,
        }


GRAPH_STORE_TYPES: list[dict[str, Any]] = [
    {
        "type": "neo4j",
        "display_name": "Neo4j",
        "connection_fields": [
            {"name": "uri", "type": "string", "required": True},
            {"name": "user", "type": "string", "required": False},
            {"name": "password", "type": "string", "required": False, "sensitive": True},
        ],
        "index_fields": [],
    },
    {
        "type": "arcadedb",
        "display_name": "ArcadeDB",
        "connection_fields": [
            {"name": "uri", "type": "string", "required": True},
            {"name": "database", "type": "string", "required": False, "default": "memstack"},
            {"name": "user", "type": "string", "required": False},
            {"name": "password", "type": "string", "required": False, "sensitive": True},
            {"name": "http_base_url", "type": "string", "required": False},
        ],
        "index_fields": [],
    },
    {
        "type": "age",
        "display_name": "Apache AGE (PostgreSQL)",
        "connection_fields": [
            {"name": "dsn", "type": "string", "required": True, "sensitive": True}
        ],
        "index_fields": [],
        "status": "planned",
    },
]


def _to_display(store: GraphStore) -> StoreDisplay:
    return StoreDisplay(
        id=store.id,
        tenant_id=store.tenant_id,
        name=store.name,
        engine_type=store.engine_type,
        status=store.status,
        health_status=store.health_status,
        detected_version=store.detected_version,
        connection_config=store.masked_connection_config(),
        index_config=store.index_config,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


class GraphStoreService:
    """Service for managing pluggable graph backends."""

    def __init__(
        self,
        repo: GraphStoreRepository,
        registry: GraphBackendRegistry,
        factory: GraphBackendFactory,
    ) -> None:
        self._repo = repo
        self._registry = registry
        self._factory = factory

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_store_types(self) -> list[dict[str, Any]]:
        """Return engine metadata for dynamic UI forms."""
        return [dict(item) for item in GRAPH_STORE_TYPES]

    async def create_store(
        self,
        *,
        tenant_id: str,
        name: str,
        engine_type: str,
        connection_config: dict[str, Any] | None = None,
        index_config: dict[str, Any] | None = None,
        created_by: str = "",
    ) -> GraphStore:
        """Create a new graph store (validates engine type + name uniqueness)."""
        engine_type = (engine_type or "neo4j").lower()
        if engine_type not in VALID_GRAPH_ENGINE_TYPES:
            raise GraphStoreValidationError(
                f"Unsupported engine type: {engine_type!r} "
                f"(valid: {sorted(VALID_GRAPH_ENGINE_TYPES)})"
            )
        existing = await self._repo.find_by_name(tenant_id, name)
        if existing is not None:
            raise GraphStoreNameConflict(
                f"A graph store named {name!r} already exists in this tenant"
            )

        store = GraphStore(
            id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            engine_type=engine_type,
            connection_config=connection_config or {},
            index_config=index_config or {},
            status="disconnected",
            created_by=created_by,
        )
        return await self._repo.save(store)

    async def update_connection_config(
        self,
        *,
        tenant_id: str,
        store_id: str,
        connection_config: dict[str, Any],
    ) -> GraphStore:
        """Update only the connection config of a store (re-test recommended)."""
        store = await self._require_store(tenant_id, store_id)
        store.connection_config = connection_config
        saved = await self._repo.save(store)
        # Invalidate any cached live backend for this store id.
        self._registry.unregister_store(store_id)
        return saved

    async def update_store(
        self,
        *,
        tenant_id: str,
        store_id: str,
        name: str | None = None,
        connection_config: dict[str, Any] | None = None,
        index_config: dict[str, Any] | None = None,
    ) -> GraphStore:
        """Update mutable store fields and invalidate any cached backend."""
        store = await self._require_store(tenant_id, store_id)
        if name and name != store.name:
            existing = await self._repo.find_by_name(tenant_id, name)
            if existing is not None and existing.id != store_id:
                raise GraphStoreNameConflict(
                    f"A graph store named {name!r} already exists in this tenant"
                )
            store.name = name
        if connection_config is not None:
            _validate_required_fields(store.engine_type, connection_config)
            store.connection_config = connection_config
        if index_config is not None:
            store.index_config = index_config
        saved = await self._repo.save(store)
        self._registry.unregister_store(store_id)
        return saved

    async def get_store(self, tenant_id: str, store_id: str) -> GraphStore:
        """Fetch a store by id (raises GraphStoreNotFound if absent)."""
        return await self._require_store(tenant_id, store_id)

    async def list_stores(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[GraphStore]:
        return await self._repo.find_by_tenant(tenant_id, limit=limit, offset=offset)

    async def resolve_store_view(self, tenant_id: str, store_id: str) -> StoreDisplay:
        """Return a single store with secrets masked (never returns credentials)."""
        store = await self._require_store(tenant_id, store_id)
        return _to_display(store)

    async def batch_resolve_store_views(
        self, tenant_id: str, store_ids: list[str]
    ) -> dict[str, StoreDisplay]:
        """Resolve multiple stores at once (avoids N+1)."""
        out: dict[str, StoreDisplay] = {}
        for sid in dict.fromkeys(store_ids):  # de-dup, preserve order
            store = await self._repo.find_by_id(tenant_id, sid)
            if store is not None:
                out[sid] = _to_display(store)
        return out

    def env_default_store_view(self, tenant_id: str) -> StoreDisplay:
        """Return API-safe display for the env-configured graph backend."""
        return StoreDisplay(
            id="__env_neo4j__",
            tenant_id=tenant_id,
            name="neo4j (env)",
            engine_type="neo4j",
            status="connected",
            health_status=None,
            detected_version=None,
            connection_config={"uri": "env"},
            index_config={},
            created_at=None,
            updated_at=None,
            source="env",
            readonly=True,
        )

    async def delete_store(self, tenant_id: str, store_id: str) -> None:
        """Soft-delete a store, rejecting when projects are still bound."""
        await self._require_store(tenant_id, store_id)
        bound = await self._repo.count_projects_bound(store_id)
        if bound > 0:
            raise GraphStoreInUse(
                f"Graph store {store_id!r} still has {bound} project(s) bound to it; "
                "unbind or delete them before removing the store"
            )
        await self._repo.soft_delete(tenant_id, store_id)
        self._registry.unregister_store(store_id)
        logger.info("Deleted graph store %s for tenant %s", store_id, tenant_id)

    # ------------------------------------------------------------------
    # Connection testing
    # ------------------------------------------------------------------

    async def test_connection(
        self, *, engine_type: str, connection_config: dict[str, Any]
    ) -> str:
        """Validate + probe a connection config; return detected server version.

        Performs an SSRF guard on the resolved host before building a backend.
        Used by the "test raw connection" admin flow (untrusted input).
        """
        engine_type = (engine_type or "neo4j").lower()
        if engine_type not in VALID_GRAPH_ENGINE_TYPES:
            raise GraphStoreValidationError(f"Unsupported engine type: {engine_type!r}")
        _validate_required_fields(engine_type, connection_config)
        _ssrf_guard(connection_config)

        store = GraphStore(
            id="__test__",
            tenant_id="__test__",
            name="connection-test",
            engine_type=engine_type,
            connection_config=connection_config,
        )
        backend = self._factory.build(store)
        if isawaitable(backend):
            backend = await backend
        if hasattr(backend, "health_probe"):
            ok = await backend.health_probe()  # type: ignore[attr-defined]
        else:
            ok = bool(backend)
        # Best-effort version detection.
        version = getattr(backend, "detected_version", None) or "ok" if ok else "unreachable"
        if hasattr(backend, "close"):
            try:
                await backend.close()  # type: ignore[attr-defined]
            except Exception:
                logger.debug("Failed to close test backend", exc_info=True)
        if not ok:
            raise GraphStoreValidationError("Connection test failed: backend unreachable")
        return version

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _require_store(self, tenant_id: str, store_id: str) -> GraphStore:
        store = await self._repo.find_by_id(tenant_id, store_id)
        if store is None:
            raise GraphStoreNotFound(f"Graph store {store_id!r} not found")
        return store


# ----------------------------------------------------------------------
# SSRF / validation helpers (module-level for testability)
# ----------------------------------------------------------------------

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "neo4j": ("uri",),
    "arcadedb": ("uri",),
    "age": ("dsn",),
}


def _validate_required_fields(engine_type: str, config: dict[str, Any]) -> None:
    required = _REQUIRED_FIELDS.get(engine_type, ())
    missing = [f for f in required if not config.get(f)]
    if missing:
        raise GraphStoreValidationError(
            f"Missing required connection fields for {engine_type!r}: {missing}"
        )


def _ssrf_guard(config: dict[str, Any]) -> None:
    """Reject connection configs pointing at private/loopback/link-local hosts.

    Guards the raw (untrusted) connection-test flow against SSRF. Considers both
    a ``uri`` (bolt://host:port) and a bare ``host`` field. Resolution failures
    are rejected conservatively.
    """
    raw = config.get("uri") or f"bolt://{config.get('host', '')}:7687"
    parsed = urlparse(raw)
    host = parsed.hostname
    if not host:
        raise GraphStoreValidationError("Connection config has no resolvable host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise GraphStoreValidationError(f"Cannot resolve host {host!r}: {e}") from e
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise GraphStoreValidationError(
                f"Refused connection to non-public host {host!r} ({addr})"
            )
