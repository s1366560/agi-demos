"""Business logic for pluggable retrieval backend management."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from src.configuration.config import get_settings
from src.domain.model.retrieval_store import RetrievalStore
from src.domain.ports.repositories.retrieval_store_repository import (
    RetrievalStoreRepository,
)
from src.domain.shared_kernel import DomainException
from src.infrastructure.retrieval.registry import (
    ENGINE_MEMSTACK_PGVECTOR,
    ENGINE_WEKNORA_REMOTE,
    VALID_RETRIEVAL_ENGINE_TYPES,
    RetrievalBackendFactory,
    RetrievalBackendRegistry,
)

logger = logging.getLogger(__name__)

_PRIVATE_HOST_ALLOWLIST_ENV = "RETRIEVAL_STORE_PRIVATE_HOST_ALLOWLIST"
_LOCAL_ENVIRONMENTS = {"development", "dev", "local", "test"}


class RetrievalStoreNotFound(DomainException):
    """Raised when a retrieval store id is not found under the tenant."""


class RetrievalStoreNameConflict(DomainException):
    """Raised when a retrieval store name is already used in the tenant."""


class RetrievalStoreInUse(DomainException):
    """Raised when deleting a store that projects still bind to."""


class RetrievalStoreValidationError(DomainException):
    """Raised for invalid engine type, config, or raw connection target."""


@dataclass(frozen=True)
class StoreDisplay:
    """API-safe retrieval store projection."""

    id: str
    tenant_id: str
    name: str
    engine_type: str
    status: str
    health_status: str | None
    detected_version: str | None
    connection_config: dict[str, Any]
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


RETRIEVAL_STORE_TYPES: list[dict[str, Any]] = [
    {
        "type": ENGINE_MEMSTACK_PGVECTOR,
        "display_name": "MemStack PostgreSQL (pgvector + FTS)",
        "connection_fields": [
            {
                "name": "use_default_connection",
                "type": "boolean",
                "required": False,
                "default": True,
            }
        ],
        "index_fields": [],
        "source": "env",
    },
    {
        "type": ENGINE_WEKNORA_REMOTE,
        "display_name": "WeKnora Remote",
        "connection_fields": [
            {"name": "base_url", "type": "string", "required": True},
            {"name": "api_key", "type": "string", "required": True, "sensitive": True},
            {"name": "knowledge_base_id", "type": "string", "required": False},
            {"name": "knowledge_base_ids", "type": "array", "required": False},
        ],
        "index_fields": [
            {"name": "search_path", "type": "string", "required": False, "default": "/knowledge-search"},
            {"name": "index_path", "type": "string", "required": False},
        ],
    },
    {"type": "qdrant", "display_name": "Qdrant", "connection_fields": [], "index_fields": []},
    {"type": "milvus", "display_name": "Milvus", "connection_fields": [], "index_fields": []},
    {"type": "weaviate", "display_name": "Weaviate", "connection_fields": [], "index_fields": []},
    {
        "type": "elasticsearch",
        "display_name": "Elasticsearch",
        "connection_fields": [],
        "index_fields": [],
    },
    {"type": "opensearch", "display_name": "OpenSearch", "connection_fields": [], "index_fields": []},
]


def _to_display(store: RetrievalStore) -> StoreDisplay:
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


class RetrievalStoreService:
    """Service for managing pluggable retrieval backends."""

    def __init__(
        self,
        repo: RetrievalStoreRepository,
        registry: RetrievalBackendRegistry,
        factory: RetrievalBackendFactory,
    ) -> None:
        self._repo = repo
        self._registry = registry
        self._factory = factory

    def list_store_types(self) -> list[dict[str, Any]]:
        return [dict(item) for item in RETRIEVAL_STORE_TYPES]

    async def create_store(
        self,
        *,
        tenant_id: str,
        name: str,
        engine_type: str,
        connection_config: dict[str, Any] | None = None,
        index_config: dict[str, Any] | None = None,
        created_by: str = "",
    ) -> RetrievalStore:
        engine_type = (engine_type or ENGINE_MEMSTACK_PGVECTOR).lower()
        if engine_type not in VALID_RETRIEVAL_ENGINE_TYPES:
            raise RetrievalStoreValidationError(
                f"Unsupported engine type: {engine_type!r} "
                f"(valid: {sorted(VALID_RETRIEVAL_ENGINE_TYPES)})"
            )
        existing = await self._repo.find_by_name(tenant_id, name)
        if existing is not None:
            raise RetrievalStoreNameConflict(
                f"A retrieval store named {name!r} already exists in this tenant"
            )

        config = connection_config or {}
        _validate_required_fields(engine_type, config)
        store = RetrievalStore(
            id=str(uuid4()),
            tenant_id=tenant_id,
            name=name,
            engine_type=engine_type,
            connection_config=config,
            index_config=index_config or {},
            status="disconnected",
            created_by=created_by,
        )
        return await self._repo.save(store)

    async def get_store(self, tenant_id: str, store_id: str) -> RetrievalStore:
        return await self._require_store(tenant_id, store_id)

    async def list_stores(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[RetrievalStore]:
        return await self._repo.find_by_tenant(tenant_id, limit=limit, offset=offset)

    async def resolve_store_view(self, tenant_id: str, store_id: str) -> StoreDisplay:
        store = await self._require_store(tenant_id, store_id)
        return _to_display(store)

    async def batch_resolve_store_views(
        self, tenant_id: str, store_ids: list[str]
    ) -> dict[str, StoreDisplay]:
        out: dict[str, StoreDisplay] = {}
        for store_id in dict.fromkeys(store_ids):
            store = await self._repo.find_by_id(tenant_id, store_id)
            if store is not None:
                out[store_id] = _to_display(store)
        return out

    async def update_connection_config(
        self,
        *,
        tenant_id: str,
        store_id: str,
        connection_config: dict[str, Any],
    ) -> RetrievalStore:
        store = await self._require_store(tenant_id, store_id)
        _validate_required_fields(store.engine_type, connection_config)
        store.connection_config = connection_config
        saved = await self._repo.save(store)
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
    ) -> RetrievalStore:
        store = await self._require_store(tenant_id, store_id)
        if name and name != store.name:
            existing = await self._repo.find_by_name(tenant_id, name)
            if existing is not None and existing.id != store_id:
                raise RetrievalStoreNameConflict(
                    f"A retrieval store named {name!r} already exists in this tenant"
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

    async def delete_store(self, tenant_id: str, store_id: str) -> None:
        await self._require_store(tenant_id, store_id)
        bound = await self._repo.count_projects_bound(store_id)
        if bound > 0:
            raise RetrievalStoreInUse(
                f"Retrieval store {store_id!r} still has {bound} project(s) bound"
            )
        await self._repo.soft_delete(tenant_id, store_id)
        self._registry.unregister_store(store_id)

    async def test_connection(
        self, *, engine_type: str, connection_config: dict[str, Any]
    ) -> str:
        engine_type = (engine_type or ENGINE_MEMSTACK_PGVECTOR).lower()
        if engine_type not in VALID_RETRIEVAL_ENGINE_TYPES:
            raise RetrievalStoreValidationError(f"Unsupported engine type: {engine_type!r}")
        _validate_required_fields(engine_type, connection_config)
        if engine_type != ENGINE_MEMSTACK_PGVECTOR:
            _ssrf_guard(connection_config)

        store = RetrievalStore(
            id="__test__",
            tenant_id="__test__",
            name="connection-test",
            engine_type=engine_type,
            connection_config=connection_config,
        )
        backend = self._factory.build(store)
        ok = await backend.health_probe()
        version = await backend.detect_version() if ok else "unreachable"
        await backend.close()
        if not ok:
            raise RetrievalStoreValidationError("Connection test failed: backend unreachable")
        return version

    def env_default_store_view(self, tenant_id: str) -> StoreDisplay:
        return StoreDisplay(
            id="__env_memstack_pgvector__",
            tenant_id=tenant_id,
            name="memstack_pgvector (env)",
            engine_type=ENGINE_MEMSTACK_PGVECTOR,
            status="connected",
            health_status=None,
            detected_version=None,
            connection_config={"use_default_connection": True},
            index_config={},
            created_at=None,
            updated_at=None,
            source="env",
            readonly=True,
        )

    async def _require_store(self, tenant_id: str, store_id: str) -> RetrievalStore:
        store = await self._repo.find_by_id(tenant_id, store_id)
        if store is None:
            raise RetrievalStoreNotFound(f"Retrieval store {store_id!r} not found")
        return store


_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    ENGINE_MEMSTACK_PGVECTOR: (),
    ENGINE_WEKNORA_REMOTE: ("base_url", "api_key"),
    "qdrant": ("host",),
    "milvus": ("host",),
    "weaviate": ("url",),
    "elasticsearch": ("addr",),
    "opensearch": ("addr",),
}


def _validate_required_fields(engine_type: str, config: dict[str, Any]) -> None:
    required = _REQUIRED_FIELDS.get(engine_type, ())
    missing = [field for field in required if not config.get(field)]
    if missing:
        raise RetrievalStoreValidationError(
            f"Missing required connection fields for {engine_type!r}: {missing}"
        )
    if engine_type == ENGINE_WEKNORA_REMOTE and not (
        config.get("knowledge_base_id") or config.get("knowledge_base_ids")
    ):
        raise RetrievalStoreValidationError(
            "WeKnora remote retrieval requires knowledge_base_id or knowledge_base_ids"
        )


def _normalize_host(value: str) -> str:
    return value.strip().lower().rstrip(".")


def _private_host_allowlist() -> set[str]:
    raw = os.getenv(_PRIVATE_HOST_ALLOWLIST_ENV)
    if raw is None:
        raw = get_settings().retrieval_store_private_host_allowlist
    return {_normalize_host(item) for item in raw.split(",") if item.strip()}


def _current_environment() -> str:
    return _normalize_host(os.getenv("ENVIRONMENT") or get_settings().environment)


def _is_private_target_allowed(
    host: str, addr: str, ip: ipaddress.IPv4Address | ipaddress.IPv6Address
) -> bool:
    allowlist = _private_host_allowlist()
    if _normalize_host(host) in allowlist or _normalize_host(addr) in allowlist:
        return True
    return ip.is_loopback and _current_environment() in _LOCAL_ENVIRONMENTS


def _ssrf_guard(config: dict[str, Any]) -> None:
    raw = (
        config.get("base_url")
        or config.get("url")
        or config.get("uri")
        or config.get("addr")
        or f"http://{config.get('host', '')}"
    )
    parsed = urlparse(str(raw))
    host = parsed.hostname
    if not host:
        raise RetrievalStoreValidationError("Connection config has no resolvable host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise RetrievalStoreValidationError(f"Cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        addr = str(info[4][0])
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_private_target_allowed(host, addr, ip):
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise RetrievalStoreValidationError(
                f"Refused connection to non-public host {host!r} ({addr})"
            )
