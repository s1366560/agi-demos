"""Graph store domain entity.

A ``GraphStore`` models a registered pluggable graph backend (engine type +
connection config + index config + lifecycle state) scoped to a tenant. Projects
bind to a graph store via ``graph_store_id`` (NULL = tenant/env default).

This is the domain representation; the persistence layer (``GraphStoreModel``)
stores the connection config encrypted at rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(kw_only=True)
class GraphStore:
    """A registered graph backend (e.g. a Neo4j or ArcadeDB cluster)."""

    id: str
    tenant_id: str
    name: str
    engine_type: str = "neo4j"
    # Plaintext connection config in the domain layer (encrypted only in the
    # persistence layer). May contain secrets (uri/user/password/api_key).
    connection_config: dict[str, Any] = field(default_factory=dict)
    index_config: dict[str, Any] = field(default_factory=dict)
    status: str = "disconnected"
    health_status: str | None = None
    last_health_check: datetime | None = None
    detected_version: str | None = None
    created_by: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def masked_connection_config(self) -> dict[str, Any]:
        """Return connection_config with sensitive fields replaced by ``***``."""
        sensitive = {"password", "api_key", "token", "secret"}
        out: dict[str, Any] = {}
        for key, value in self.connection_config.items():
            if key.lower() in sensitive and value:
                out[key] = "***"
            else:
                out[key] = value
        return out
