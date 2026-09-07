"""Production generation integration coverage for the engines catalog route."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _engines_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    try:
        await initialize_plugin_runtime_v2(test_app)
        assert "engines" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_engines_route_uses_the_generation_catalog(async_client: AsyncClient) -> None:
    response = await async_client.get("/api/v1/engines")

    assert response.status_code == status.HTTP_200_OK, response.text
    assert [engine["runtime_id"] for engine in response.json()] == [
        "python-3.12",
        "node-22",
        "sandbox-base",
    ]
