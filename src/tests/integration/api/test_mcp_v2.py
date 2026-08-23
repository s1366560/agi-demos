"""Production generation integration coverage for MCP routes."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from src.infrastructure.adapters.primary.web.dependencies import get_current_user_tenant
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

pytestmark = pytest.mark.integration


class _SandboxAdapter(MCPSandboxAdapter):
    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
async def _mcp_v2_runtime(test_app: FastAPI) -> AsyncIterator[None]:
    test_app.dependency_overrides[get_current_user_tenant] = lambda: "default_tenant"
    try:
        await initialize_plugin_runtime_v2(test_app, sandbox_runtime_factory=_SandboxAdapter)
        assert "mcp" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)
        test_app.dependency_overrides.pop(get_current_user_tenant, None)


async def test_mcp_list_uses_generation_services(
    authenticated_async_client: AsyncClient,
) -> None:
    response = await authenticated_async_client.get("/api/v1/mcp/list")

    assert response.status_code == status.HTTP_200_OK, response.text
    assert response.json() == []
