"""Live WeKnora remote retrieval compatibility tests.

These tests run only when WEKNORA_BASE_URL, WEKNORA_API_KEY and WEKNORA_KB_ID
are present. They validate MemStack's optional remote adapter against a real
WeKnora deployment without making WeKnora a required runtime dependency.
"""

from __future__ import annotations

import os

import pytest

from src.infrastructure.retrieval.stores.weknora_remote_store import (
    WeknoraRemoteRetrievalStore,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _live_config() -> dict[str, str]:
    base_url = os.environ.get("WEKNORA_BASE_URL")
    api_key = os.environ.get("WEKNORA_API_KEY")
    kb_id = os.environ.get("WEKNORA_KB_ID")
    if not base_url or not api_key or not kb_id:
        pytest.skip("WEKNORA_BASE_URL, WEKNORA_API_KEY and WEKNORA_KB_ID are required")
    return {
        "base_url": base_url,
        "api_key": api_key,
        "knowledge_base_id": kb_id,
    }


async def test_weknora_remote_health_and_version() -> None:
    store = WeknoraRemoteRetrievalStore(_live_config())

    assert await store.health_probe() is True
    assert await store.detect_version()


async def test_weknora_remote_hybrid_search_returns_normalized_results() -> None:
    store = WeknoraRemoteRetrievalStore(_live_config())
    query = os.environ.get("WEKNORA_QUERY", "test")

    results = await store.hybrid_search(query, project_id="weknora-live", limit=5)

    assert isinstance(results, list)
    for item in results:
        assert item.id
        assert isinstance(item.content, str)
        assert item.source_type == "weknora"
        assert "api_key" not in item.metadata
        assert "authorization" not in item.metadata
