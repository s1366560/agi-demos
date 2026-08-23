"""Production generation integration coverage for lightweight AI tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2 import ai_tool_services

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _ai_tools_v2_runtime(
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncMock]:
    """Exercise AI-tool requests through the production generation dispatcher."""
    llm_client = SimpleNamespace(generate=AsyncMock(return_value={"content": "V2 result"}))
    factory = AsyncMock(return_value=llm_client)
    monkeypatch.setattr(ai_tool_services, "create_llm_client", factory)
    try:
        await initialize_plugin_runtime_v2(test_app)
        assert "ai-tools" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
        yield factory
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_ai_tools_calls_generation_owned_tenant_client(
    authenticated_async_client: AsyncClient,
    _ai_tools_v2_runtime: AsyncMock,
) -> None:
    optimize_response = await authenticated_async_client.post(
        "/api/v1/ai/optimize",
        json={"content": "Original", "instruction": "Improve"},
    )
    title_response = await authenticated_async_client.post(
        "/api/v1/ai/generate-title",
        json={"content": "Original"},
    )

    assert optimize_response.status_code == status.HTTP_200_OK
    assert optimize_response.json() == {"content": "V2 result"}
    assert title_response.status_code == status.HTTP_200_OK
    assert title_response.json() == {"title": "V2 result"}
    assert _ai_tools_v2_runtime.await_count == 2


async def test_ai_tools_unavailable_client_fails_closed_without_builtin_fallback(
    authenticated_async_client: AsyncClient,
    _ai_tools_v2_runtime: AsyncMock,
) -> None:
    _ai_tools_v2_runtime.return_value = None

    response = await authenticated_async_client.post(
        "/api/v1/ai/optimize",
        json={"content": "Original"},
    )

    assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
    assert response.json()["detail"] == "LLM client not available. Please check configuration."
