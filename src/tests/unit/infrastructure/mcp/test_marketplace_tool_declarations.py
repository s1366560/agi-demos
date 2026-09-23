"""Real actor adapters must participate in the signed generation's tool contribution."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.permission.rules import classify_sandbox_tool_permission
from src.infrastructure.agent.tools.custom_tool_status import custom_tools_status
from src.infrastructure.mcp.sandbox_tool_adapter import (
    SandboxMCPServerToolAdapter,
    create_sandbox_mcp_server_tool,
)
from src.infrastructure.plugins.v2.agent_sandbox_mcp_tools import (
    SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2,
    _agent_sandbox_mcp_tool_set_v2,
)
from src.infrastructure.plugins.v2.tool_set import PreparedToolProviderV2

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("factory", [SandboxMCPServerToolAdapter, create_sandbox_mcp_server_tool])
def test_discovered_adapter_enters_generation_with_explicit_mcp_permission(factory):
    adapter = factory(
        sandbox_adapter=AsyncMock(),
        sandbox_id="sandbox",
        server_name="owned-demo",
        tool_info={"name": "echo", "description": "Echo text", "inputSchema": {"type": "object"}},
    )
    result = _agent_sandbox_mcp_tool_set_v2(
        agent=object(),
        selection_context=None,
        prepared_tool_provider=PreparedToolProviderV2(tools={adapter.name: adapter}),
        required_tags=SANDBOX_MCP_TOOL_REQUIRED_TAGS_V2,
    )
    assert len(result.definitions) == 1
    assert result.definitions[0].name == "mcp__owned_demo__echo"
    assert result.definitions[0].permission == "mcp"
    assert result.tools[adapter.name] is adapter


def test_metadata_permissions_do_not_authorize_remote_invocation():
    assert custom_tools_status.permission == "read"
    assert classify_sandbox_tool_permission("mcp_server_list_prompts") == "read"
    assert classify_sandbox_tool_permission("mcp_server_discover_tools") == "read"
    assert classify_sandbox_tool_permission("mcp_server_call_tool") != "read"
    assert classify_sandbox_tool_permission("mcp_server_install") != "read"


@pytest.mark.parametrize("first_result", [[], RuntimeError("offline")])
async def test_failed_discovery_never_reassigns_another_servers_tool(monkeypatch, first_result):
    import json

    from src.infrastructure.agent.state import agent_worker_state as worker

    servers = [{"name": name, "status": "running"} for name in ("first", "second")]
    sandbox = AsyncMock()
    sandbox.call_tool.return_value = {
        "content": [{"type": "text", "text": json.dumps({"servers": servers})}]
    }
    monkeypatch.setattr(worker, "_auto_restore_mcp_servers", AsyncMock())
    monkeypatch.setattr(
        worker,
        "_discover_single_server_tools",
        AsyncMock(side_effect=[first_result, [{"name": "echo", "inputSchema": {}}]]),
    )
    tools = await worker._load_user_mcp_server_tools(sandbox, "sandbox", "project")
    assert set(tools) == {"mcp__second__echo"}
    assert tools["mcp__second__echo"]._server_name == "second"
