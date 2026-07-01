"""Unit tests for the WeKnora remote retrieval adapter."""

from __future__ import annotations

import httpx
import pytest

from src.infrastructure.retrieval.stores.weknora_remote_store import (
    WeknoraRemoteError,
    WeknoraRemoteRetrievalStore,
)


def _store_with_transport(handler) -> WeknoraRemoteRetrievalStore:
    store = WeknoraRemoteRetrievalStore(
        {
            "base_url": "http://weknora.test/api/v1",
            "api_key": "secret-key",
            "knowledge_base_id": "kb-1",
        }
    )
    transport = httpx.MockTransport(handler)
    store._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://weknora.test/api/v1",
        headers={"X-API-Key": "secret-key", "Authorization": "Bearer secret-key"},
        transport=transport,
    )
    return store


@pytest.mark.unit
class TestWeknoraRemoteRetrievalStore:
    @pytest.mark.asyncio
    async def test_hybrid_search_maps_success_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://weknora.test/api/v1/knowledge-search"
            assert request.headers["X-API-Key"] == "secret-key"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "id": "chunk-1",
                            "content": "hello",
                            "knowledge_id": "knowledge-1",
                            "knowledge_title": "Doc",
                            "knowledge_filename": "doc.txt",
                            "knowledge_source": "upload",
                            "chunk_type": "text",
                            "score": 0.75,
                            "metadata": {"lang": "en"},
                        }
                    ],
                },
            )

        store = _store_with_transport(handler)

        results = await store.hybrid_search("hello", project_id="project-1", limit=5)

        assert len(results) == 1
        assert results[0].id == "chunk-1"
        assert results[0].content == "hello"
        assert results[0].score == 0.75
        assert results[0].source_type == "weknora"
        assert results[0].source_id == "knowledge-1"
        assert results[0].metadata["knowledge_title"] == "Doc"

    @pytest.mark.asyncio
    async def test_hybrid_search_raises_on_success_false(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": False, "error": "kb not found"})

        store = _store_with_transport(handler)

        with pytest.raises(WeknoraRemoteError, match="kb not found"):
            await store.hybrid_search("hello", project_id="project-1")

    @pytest.mark.asyncio
    async def test_hybrid_search_accepts_nested_results_payload(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"results": [{"id": "chunk-2", "content": "nested", "score": 1}]},
                },
            )

        store = _store_with_transport(handler)

        results = await store.hybrid_search("nested", project_id="project-1")

        assert [item.id for item in results] == ["chunk-2"]

    @pytest.mark.asyncio
    async def test_hybrid_search_accepts_weknora_alias_fields_and_strips_metadata_secrets(
        self,
    ) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "chunk_id": "chunk-3",
                            "text": "aliased text",
                            "document_id": "doc-1",
                            "similarity": 0.9,
                            "category": "manual",
                            "metadata": {"api_key": "secret", "topic": "runtime"},
                        }
                    ],
                },
            )

        store = _store_with_transport(handler)

        results = await store.hybrid_search("aliased", project_id="project-1")

        assert results[0].id == "chunk-3"
        assert results[0].content == "aliased text"
        assert results[0].score == 0.9
        assert results[0].source_id == "doc-1"
        assert results[0].category == "manual"
        assert results[0].metadata["topic"] == "runtime"
        assert "api_key" not in results[0].metadata

    @pytest.mark.asyncio
    async def test_detect_version_reads_system_info_data_shape(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://weknora.test/api/v1/system/info"
            return httpx.Response(200, json={"code": 0, "data": {"version": "0.4.0"}})

        store = _store_with_transport(handler)

        assert await store.detect_version() == "0.4.0"

    @pytest.mark.asyncio
    async def test_health_probe_rejects_client_errors(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        store = _store_with_transport(handler)

        assert await store.health_probe() is False
