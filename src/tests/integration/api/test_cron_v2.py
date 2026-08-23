"""Production generation integration coverage for Cron routes."""

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
async def _cron_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    await initialize_plugin_runtime_v2(test_app)
    assert "cron" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_cron_queries_use_generation_services_and_project_membership(
    authenticated_async_client: AsyncClient,
    test_project_db,
) -> None:
    base = f"/api/v1/projects/{test_project_db.id}/cron-jobs"

    capabilities = await authenticated_async_client.get(f"{base}/capabilities")
    jobs = await authenticated_async_client.get(base)

    assert capabilities.status_code == status.HTTP_200_OK
    assert capabilities.json()["read"] is True
    assert jobs.status_code == status.HTTP_200_OK
    assert jobs.json() == {"items": [], "total": 0}
