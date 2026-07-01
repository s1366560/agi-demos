"""Pluggable retrieval backend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.retrieval_store import RetrievalChunk, RetrievalSearchResult


class RetrievalStorePort(ABC):
    """Semantic port for vector/keyword retrieval backends."""

    @abstractmethod
    async def initialize_schema(self) -> None:
        """Create backend-specific schema/indexes."""

    @abstractmethod
    async def index_chunks(self, chunks: list[RetrievalChunk]) -> int:
        """Index or replace chunks. Returns number indexed."""

    @abstractmethod
    async def delete_source(self, source_type: str, source_id: str, project_id: str) -> int:
        """Delete indexed chunks for a source. Returns number deleted."""

    @abstractmethod
    async def hybrid_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        """Search with backend-native hybrid retrieval."""

    @abstractmethod
    async def vector_search(
        self,
        query_vector: list[float],
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        """Search by vector similarity."""

    @abstractmethod
    async def fulltext_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        """Search by keyword/full-text matching."""

    @abstractmethod
    async def health_probe(self) -> bool:
        """Return whether the backend is reachable."""

    @abstractmethod
    async def detect_version(self) -> str:
        """Return detected backend version, or 'ok' when unknown."""

    @abstractmethod
    async def close(self) -> None:
        """Close underlying client/session resources."""
