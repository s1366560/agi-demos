"""Unit tests for register_mcp_server_tool (@tool_define version)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.register_mcp_server import (
    register_mcp_server_tool,
)


def _make_ctx(**overrides: Any) -> ToolContext:
    """Create a minimal ToolContext for testing."""
    defaults: dict[str, Any] = {
        "session_id": "session-1",
        "message_id": "msg-1",
        "call_id": "call-1",
        "agent_name": "test-agent",
        "conversation_id": "conv-1",
    }
    defaults.update(overrides)
    return ToolContext(**defaults)


_MOD = "src.infrastructure.agent.tools.register_mcp_server"


@pytest.mark.unit
class TestRegisterMCPServerTool:
    """Tests for register_mcp_server_tool @tool_define implementation."""

    def test_name_and_description(self) -> None:
        assert register_mcp_server_tool.name == "register_mcp_server"
        assert "MCP server" in register_mcp_server_tool.description

    def test_parameters_schema(self) -> None:
        schema = register_mcp_server_tool.parameters
        assert "server_name" in schema["properties"]
        assert "server_type" in schema["properties"]
        assert "command" in schema["properties"]
        assert "args" in schema["properties"]
        assert "url" in schema["properties"]
        assert "server_name" in schema["required"]
        assert "server_type" in schema["required"]

    async def test_execute_no_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sandbox adapter/id is not set, return error."""
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", None)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", None)
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Sandbox not available" in result.output

    async def test_execute_missing_server_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "server_name is required" in result.output

    async def test_execute_invalid_server_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="invalid", command="node"
        )
        assert result.is_error
        assert "Invalid server_type" in result.output

    async def test_execute_stdio_missing_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="stdio"
        )
        assert result.is_error
        assert "'command' is required" in result.output

    async def test_execute_sse_missing_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="my-server", server_type="sse"
        )
        assert result.is_error
        assert "'url' is required" in result.output

    async def test_execute_install_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": '{"success": false, "error": "pkg not found"}'}
                ]
            }
        )
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="bad-server", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Failed to install" in result.output

    async def test_execute_start_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # install succeeds
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            # start fails
            return {
                "content": [{"type": "text", "text": '{"success": false, "error": "port busy"}'}]
            }

        mock_adapter.call_tool = mock_call_tool
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="fail-server", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Failed to start" in result.output

    async def test_execute_success_no_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # install + start succeed
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            # discover returns tools
            return {
                "content": [
                    {"type": "text", "text": '[{"name": "query_db", "description": "Run SQL"}]'}
                ]
            }

        mock_adapter.call_tool = mock_call_tool
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", None)
        # Stub out persist/lifecycle helpers to avoid DB calls
        monkeypatch.setattr(f"{_MOD}._register_mcp_persist_server", AsyncMock(return_value=None))
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_emit_events",
            AsyncMock(return_value={"probe": {"status": "ok"}}),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="my-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )
        assert not result.is_error
        assert "registered and started successfully" in result.output
        assert "query_db" in result.output
        assert "MCP App" not in result.output

    async def test_execute_success_with_apps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            tools = [
                {
                    "name": "render_dashboard",
                    "_meta": {
                        "ui": {
                            "resourceUri": "ui://dashboard/index.html",
                            "title": "Dashboard",
                        }
                    },
                },
                {"name": "query_data", "description": "Query backend"},
            ]
            return {"content": [{"type": "text", "text": json.dumps(tools)}]}

        mock_adapter.call_tool = mock_call_tool
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", AsyncMock())
        monkeypatch.setattr(f"{_MOD}._register_mcp_persist_server", AsyncMock(return_value=None))
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_persist_app", AsyncMock(return_value="test-app-id-123")
        )
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_emit_events",
            AsyncMock(return_value={"probe": {"status": "ok"}}),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="dashboard-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )
        assert not result.is_error
        assert "registered and started successfully" in result.output
        assert "2 tool(s)" in result.output
        assert "1 MCP App(s)" in result.output
        assert "render_dashboard" in result.output

    async def test_execute_exception_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(side_effect=Exception("Connection lost"))
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sb-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "project-1")

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx, server_name="broken", server_type="stdio", command="node"
        )
        assert result.is_error
        assert "Connection lost" in result.output

    def test_consume_pending_events_empty(self) -> None:
        """New API uses ToolContext for events; fresh ctx has no events."""
        ctx = _make_ctx()
        assert ctx.consume_pending_events() == []
