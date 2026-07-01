"""Retrieval store domain entity and DTOs.

Retrieval stores model vector/keyword search backends for project knowledge
content. They intentionally mirror the graph-store and WeKnora vector-store
shape: tenant-scoped, engine typed, encrypted connection config in persistence,
and application-enforced project bindings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(kw_only=True)
class RetrievalStore:
    """A registered retrieval backend such as pgvector, Qdrant, or WeKnora."""

    id: str
    tenant_id: str
    name: str
    engine_type: str = "memstack_pgvector"
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
        """Return connection_config with sensitive values redacted."""
        sensitive = {"password", "api_key", "token", "secret", "authorization"}
        out: dict[str, Any] = {}
        for key, value in self.connection_config.items():
            if key.lower() in sensitive and value:
                out[key] = "***"
            else:
                out[key] = value
        return out


@dataclass(frozen=True, kw_only=True)
class RetrievalChunk:
    """Chunk payload for indexing into a retrieval backend."""

    id: str | None = None
    source_type: str
    source_id: str
    project_id: str
    content: str
    chunk_index: int = 0
    category: str = "other"
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    importance: float = 0.5


@dataclass(frozen=True, kw_only=True)
class RetrievalSearchResult:
    """Normalized retrieval search result returned by every backend."""

    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str | None = None
    source_id: str | None = None
    category: str = "other"
    created_at: datetime | None = None
