"""Optional remote retrieval adapter for an existing WeKnora deployment."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.domain.model.retrieval_store import RetrievalChunk, RetrievalSearchResult
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort

logger = logging.getLogger(__name__)


class WeknoraRemoteError(RuntimeError):
    """Raised when WeKnora returns an unsuccessful or unexpected payload."""


class WeknoraRemoteRetrievalStore(RetrievalStorePort):
    """Remote adapter using WeKnora's HTTP API.

    Required connection config:
    - ``base_url``: WeKnora API root, e.g. http://localhost:8080/api/v1
    - ``api_key``: tenant API key
    - ``knowledge_base_id`` or ``knowledge_base_ids``: target KB scope

    Optional connection config:
    - ``search_path``: defaults to /knowledge-search
    - ``index_path``: custom endpoint for external indexing, if deployed
    - ``health_path``: defaults to /system/info
    """

    def __init__(self, connection_config: dict[str, Any]) -> None:
        self._config = dict(connection_config)
        self._base_url = str(self._config.get("base_url", "")).rstrip("/")
        self._api_key = str(self._config.get("api_key", ""))
        self._search_path = str(self._config.get("search_path") or "/knowledge-search")
        self._index_path = self._config.get("index_path")
        self._health_path = str(self._config.get("health_path") or "/system/info")

    async def initialize_schema(self) -> None:
        return None

    async def index_chunks(self, chunks: list[RetrievalChunk]) -> int:
        if not chunks:
            return 0
        if not self._index_path:
            raise RuntimeError("WeKnora remote indexing requires connection_config.index_path")
        payload = {
            "chunks": [
                {
                    "id": chunk.id,
                    "source_type": chunk.source_type,
                    "source_id": chunk.source_id,
                    "project_id": chunk.project_id,
                    "content": chunk.content,
                    "chunk_index": chunk.chunk_index,
                    "category": chunk.category,
                    "metadata": chunk.metadata,
                }
                for chunk in chunks
            ]
        }
        async with self._client() as client:
            resp = await client.post(str(self._index_path), json=payload)
            resp.raise_for_status()
        return len(chunks)

    async def delete_source(self, source_type: str, source_id: str, project_id: str) -> int:
        delete_path = self._config.get("delete_path")
        if not delete_path:
            return 0
        async with self._client() as client:
            resp = await client.post(
                str(delete_path),
                json={
                    "source_type": source_type,
                    "source_id": source_id,
                    "project_id": project_id,
                },
            )
            resp.raise_for_status()
        return 1

    async def hybrid_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        payload: dict[str, Any] = {"query": query, "limit": limit}
        kb_ids = self._config.get("knowledge_base_ids")
        kb_id = self._config.get("knowledge_base_id") or project_id
        if isinstance(kb_ids, list) and kb_ids:
            payload["knowledge_base_ids"] = kb_ids
        else:
            payload["knowledge_base_id"] = kb_id
        if category:
            payload["category"] = category
        async with self._client() as client:
            resp = await client.post(self._search_path, json=payload)
            resp.raise_for_status()
            data = resp.json()
        rows = _extract_weknora_rows(data)
        return [self._row_to_result(row) for row in rows if isinstance(row, dict)][:limit]

    async def vector_search(
        self,
        query_vector: list[float],
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        _ = query_vector, project_id, limit, category
        raise NotImplementedError("WeKnora remote adapter exposes hybrid_search only")

    async def fulltext_search(
        self,
        query: str,
        project_id: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[RetrievalSearchResult]:
        return await self.hybrid_search(query, project_id, limit=limit, category=category)

    async def health_probe(self) -> bool:
        try:
            async with self._client() as client:
                resp = await client.get(self._health_path)
            return resp.status_code < 400
        except Exception:
            logger.debug("WeKnora remote health probe failed", exc_info=True)
            return False

    async def detect_version(self) -> str:
        try:
            async with self._client() as client:
                resp = await client.get(self._health_path)
                payload = resp.json() if resp.content else {}
            data = payload.get("data") if isinstance(payload, dict) else None
            version = None
            if isinstance(payload, dict):
                version = payload.get("version")
            if version is None and isinstance(data, dict):
                version = data.get("version")
            return str(version or "ok")
        except Exception:
            return "unknown"

    async def close(self) -> None:
        return None

    def _client(self) -> httpx.AsyncClient:
        if not self._base_url:
            raise RuntimeError("WeKnora remote base_url is required")
        headers = {"X-API-Key": self._api_key}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=30.0)

    @staticmethod
    def _row_to_result(row: dict[str, Any]) -> RetrievalSearchResult:
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata = _sanitize_metadata(metadata)
        source_id = row.get("knowledge_id") or row.get("document_id") or row.get("source_id")
        for key in (
            "knowledge_id",
            "knowledge_title",
            "knowledge_filename",
            "knowledge_source",
            "knowledge_base_id",
            "document_id",
            "source",
        ):
            if key in row and row.get(key) is not None:
                metadata[key] = row.get(key)
        score = row.get("score")
        if score is None:
            score = row.get("similarity")
        if score is None:
            score = row.get("distance")
        return RetrievalSearchResult(
            id=str(row.get("id") or row.get("chunk_id") or row.get("document_id") or ""),
            content=str(row.get("content") or row.get("text") or row.get("chunk_text") or ""),
            score=float(score or 0.0),
            metadata=metadata,
            source_type="weknora",
            source_id=source_id,
            category=str(row.get("chunk_type") or row.get("category") or "other"),
        )


def _extract_weknora_rows(payload: object) -> list[dict[str, Any]]:
    """Extract ``knowledge-search`` result rows from WeKnora payloads."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        raise WeknoraRemoteError("WeKnora knowledge-search returned a non-object payload")

    if payload.get("success") is False:
        error = payload.get("error") or payload.get("message") or payload.get("msg")
        raise WeknoraRemoteError(str(error or "WeKnora knowledge-search returned success=false"))

    rows = payload.get("data")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    if isinstance(rows, dict):
        nested = rows.get("results") or rows.get("items") or rows.get("chunks")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
    if rows is None and payload.get("success") is True:
        return []
    raise WeknoraRemoteError("WeKnora knowledge-search returned an unexpected payload shape")


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sensitive = {"api_key", "password", "token", "authorization", "secret"}
    return {key: value for key, value in metadata.items() if key.lower() not in sensitive}
