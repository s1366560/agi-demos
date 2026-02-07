"""Unit tests for SandboxMCPServerManager."""

import json

import pytest
from unittest.mock import AsyncMock

from src.application.services.sandbox_mcp_server_manager import SandboxMCPServerManager
from src.domain.ports.services.sandbox_mcp_server_port import (
    SandboxMCPServerStatus,
    SandboxMCPToolCallResult,
)


@pytest.mark.unit
class TestSandboxMCPServerManager:
    """Tests for SandboxMCPServerManager."""

    def _make_manager(self):
        sandbox_resource = AsyncMock()
        return SandboxMCPServerManager(sandbox_resource=sandbox_resource), sandbox_resource

    def _tool_result(self, data, is_error=False):
        """Create a tool result dict matching sandbox MCP response format."""
        return {
            "content": [{"type": "text", "text": json.dumps(data)}],
            "is_error": is_error,
        }

    async def test_install_and_start_success(self):
        mgr, resource = self._make_manager()
        resource.ensure_sandbox_ready = AsyncMock(return_value="sandbox-1")
        resource.execute_tool.side_effect = [
            self._tool_result({"success": True}),
            self._tool_result({"success": True, "status": "running", "pid": 1234}),
        ]

        result = await mgr.install_and_start(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="test-server",
            server_type="stdio",
            transport_config={"command": "node", "args": ["server.js"]},
        )

        assert isinstance(result, SandboxMCPServerStatus)
        assert result.status == "running"
        assert result.pid == 1234
        assert resource.execute_tool.call_count == 2

    async def test_install_and_start_install_failure(self):
        mgr, resource = self._make_manager()
        resource.ensure_sandbox_ready = AsyncMock(return_value="sandbox-1")
        resource.execute_tool.return_value = self._tool_result(
            {"success": False, "error": "npm not found"}, is_error=False
        )

        result = await mgr.install_and_start(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="test-server",
            server_type="stdio",
            transport_config={"command": "node"},
        )

        assert result.status == "failed"
        assert "npm" in (result.error or "")

    async def test_stop_server_success(self):
        mgr, resource = self._make_manager()
        resource.execute_tool.return_value = self._tool_result({"success": True})

        result = await mgr.stop_server(
            project_id="proj-1",
            server_name="test-server",
        )

        assert result is True

    async def test_stop_server_failure(self):
        mgr, resource = self._make_manager()
        resource.execute_tool.side_effect = ConnectionError("sandbox down")

        result = await mgr.stop_server(
            project_id="proj-1",
            server_name="test-server",
        )

        assert result is False

    async def test_discover_tools_success(self):
        mgr, resource = self._make_manager()
        resource.ensure_sandbox_ready = AsyncMock(return_value="sandbox-1")
        tools_data = [
            {"name": "read", "description": "Read file", "input_schema": {}},
            {"name": "write", "description": "Write file", "input_schema": {}},
        ]
        resource.execute_tool.side_effect = [
            # install_and_start: install
            self._tool_result({"success": True}),
            # install_and_start: start
            self._tool_result({"success": True, "status": "running"}),
            # discover
            self._tool_result(tools_data),
        ]

        tools = await mgr.discover_tools(
            project_id="proj-1",
            tenant_id="tenant-1",
            server_name="test-server",
            server_type="stdio",
            transport_config={"command": "node"},
        )

        assert len(tools) == 2
        assert tools[0]["name"] == "read"

    async def test_call_tool_success(self):
        mgr, resource = self._make_manager()
        resource.execute_tool.return_value = {
            "content": [{"type": "text", "text": "result data"}],
            "is_error": False,
        }

        result = await mgr.call_tool(
            project_id="proj-1",
            server_name="test-server",
            tool_name="read",
            arguments={"path": "/tmp/test"},
        )

        assert isinstance(result, SandboxMCPToolCallResult)
        assert result.is_error is False
        assert len(result.content) == 1

    async def test_call_tool_error(self):
        mgr, resource = self._make_manager()
        resource.execute_tool.return_value = {
            "content": [{"type": "text", "text": "tool failed"}],
            "is_error": True,
        }

        result = await mgr.call_tool(
            project_id="proj-1",
            server_name="test-server",
            tool_name="read",
            arguments={},
        )

        assert result.is_error is True

    async def test_call_tool_exception(self):
        mgr, resource = self._make_manager()
        resource.execute_tool.side_effect = ConnectionError("sandbox down")

        result = await mgr.call_tool(
            project_id="proj-1",
            server_name="test-server",
            tool_name="read",
            arguments={},
        )

        assert result.is_error is True
        assert "sandbox down" in result.error_message

    async def test_list_servers(self):
        mgr, resource = self._make_manager()
        resource.execute_tool.return_value = self._tool_result([
            {"name": "server1", "server_type": "stdio", "status": "running", "pid": 100},
            {"name": "server2", "server_type": "sse", "status": "stopped"},
        ])

        servers = await mgr.list_servers(project_id="proj-1")

        assert len(servers) == 2
        assert servers[0].name == "server1"
        assert servers[0].status == "running"
        assert servers[1].name == "server2"
        assert servers[1].status == "stopped"

    async def test_parse_tool_result_json(self):
        mgr, _ = self._make_manager()
        result = mgr._parse_tool_result({
            "content": [{"type": "text", "text": '{"key": "value"}'}]
        })
        assert result == {"key": "value"}

    async def test_parse_tool_result_plain_text(self):
        mgr, _ = self._make_manager()
        result = mgr._parse_tool_result({
            "content": [{"type": "text", "text": "just plain text"}]
        })
        assert result == "just plain text"
