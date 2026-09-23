"""Project MCP calls stay inside the sandbox owning the installed package."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.ports.services.sandbox_mcp_server_port import SandboxMCPToolCallResult
from src.infrastructure.plugins.v2.mcp_services import MCPClientDirectToolCallerV2

pytestmark = pytest.mark.unit


async def test_project_stdio_call_uses_registered_sandbox_process():
    manager = SimpleNamespace(
        call_tool=AsyncMock(
            return_value=SandboxMCPToolCallResult(
                content=[{"type": "text", "text": "OK"}], is_error=False
            )
        )
    )
    caller = MCPClientDirectToolCallerV2(sandbox_manager=manager)
    result = await caller.call(
        server=SimpleNamespace(project_id="project", name="installed-demo"),
        tool_name="echo",
        arguments={"text": "OK"},
    )
    assert result == {"content": [{"type": "text", "text": "OK"}], "isError": False}
    manager.call_tool.assert_awaited_once_with(
        project_id="project",
        server_name="installed-demo",
        tool_name="echo",
        arguments={"text": "OK"},
    )


async def test_unscoped_server_does_not_spawn_on_cloud_host():
    manager = SimpleNamespace(call_tool=AsyncMock())
    caller = MCPClientDirectToolCallerV2(sandbox_manager=manager)
    with pytest.raises(ValueError, match="project sandbox"):
        await caller.call(server=SimpleNamespace(project_id=None), tool_name="echo", arguments={})
    manager.call_tool.assert_not_awaited()
