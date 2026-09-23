"""Expired OAuth credentials must refresh before actual actor tool discovery."""

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from src.application.services import marketplace_agent_mcp
from src.infrastructure.adapters.secondary.persistence.models import MCPServer
from src.infrastructure.agent.state.agent_worker_state import _discover_single_server_tools
from src.infrastructure.plugins import marketplace_snapshot_cache
from src.infrastructure.plugins.marketplace_credentials import open_transport
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.application.services.test_marketplace_oauth import (
    oauth as oauth_fixture,  # noqa: F401
)
from src.tests.unit.application.services.test_marketplace_oauth_runtime import runtime  # noqa: F401

pytestmark = pytest.mark.unit


async def test_actor_discovers_real_http_tools_after_token_expiration(
    runtime,  # noqa: F811
    oauth_fixture,  # noqa: F811
    monkeypatch,
):
    service, manager, sandbox, original = runtime
    _, fixture, _, _ = oauth_fixture
    fixture.tokens[original]["expires"] = time.time() - 1
    sandbox.get_sandbox_id = AsyncMock(return_value="sandbox")
    inside_lease = False

    @asynccontextmanager
    async def lease(*args, **kwargs):
        nonlocal inside_lease
        inside_lease = True
        try:
            yield
        finally:
            inside_lease = False

    monkeypatch.setattr(marketplace_snapshot_cache, "lease_marketplace_snapshots", lease)

    async def actual_http_discover(**kwargs):
        assert inside_lease
        assert kwargs["tool_name"] == "mcp_server_discover_tools"
        server = await service.db.get(MCPServer, "server")
        bearer = open_transport(server.transport_config["headers"]["Authorization"])
        async with httpx.AsyncClient() as client:
            response = await client.post(
                fixture.resource,
                headers={"Authorization": bearer},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        response.raise_for_status()
        return {
            "content": [{"type": "text", "text": json.dumps(response.json()["result"]["tools"])}]
        }

    sandbox.execute_tool = AsyncMock(side_effect=actual_http_discover)
    resolver = SimpleNamespace(resolve=lambda operation: SimpleNamespace(sandbox_manager=manager))
    services = {"service:application.mcp-services": resolver}

    def require(name):
        if name not in services:
            raise RuntimeV2Error("missing_service", "test operation service unavailable")
        return services[name]

    operation = SimpleNamespace(
        context=SimpleNamespace(scope=SimpleNamespace(tenant_id="tenant", project_id="project")),
        require=require,
        provide=lambda name, value: services.__setitem__(name, value),
    )
    monkeypatch.setattr(marketplace_agent_mcp, "current_operation_context_v2", lambda: operation)
    raw = AsyncMock()
    tools = await _discover_single_server_tools(raw, "sandbox", "managed-demo")
    assert [tool["name"] for tool in tools] == ["echo"]
    manager.runtime_service.update_server.assert_awaited_once()
    raw.call_tool.assert_not_called()
    assert inside_lease is False
