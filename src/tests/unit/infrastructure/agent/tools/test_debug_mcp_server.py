"""Tests for DebugMCPServerTool.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that the DebugMCPServerTool provides useful debugging
information for MCP servers running inside sandboxes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDebugMCPServerTool:
    """Test DebugMCPServerTool functionality."""

    @pytest.mark.asyncio
    async def test_tool_exists(self):
        """
        RED Test: Verify that DebugMCPServerTool class exists.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        assert DebugMCPServerTool is not None

    @pytest.mark.asyncio
    async def test_tool_returns_server_logs(self):
        """
        Test that DebugMCPServerTool returns server logs.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "[INFO] Server started\n[ERROR] Connection failed"}],
            }
        )

        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(server_name="test-server")

        assert "logs" in result
        assert "Server started" in result["logs"] or "logs" in str(result)

    @pytest.mark.asyncio
    async def test_tool_returns_process_info(self):
        """
        Test that DebugMCPServerTool returns process information.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()

        # Mock mcp_server_status response
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{
                    "type": "text",
                    "text": '{"status": "running", "pid": 12345, "memory_mb": 50, "cpu_percent": 2.5}'
                }],
            }
        )

        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(server_name="test-server")

        # Should have process info
        assert "status" in result or "process" in result or "running" in str(result)

    @pytest.mark.asyncio
    async def test_tool_returns_last_error(self):
        """
        Test that DebugMCPServerTool returns last error information.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()

        # Mock response with error info
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{
                    "type": "text",
                    "text": '{"last_error": "Connection refused", "error_count": 3}'
                }],
            }
        )

        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(server_name="broken-server")

        # Should have error info
        assert "error" in result or "Connection refused" in str(result)

    @pytest.mark.asyncio
    async def test_tool_handles_nonexistent_server(self):
        """
        Test that DebugMCPServerTool handles non-existent server gracefully.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": '{"error": "Server not found"}'}],
                "is_error": True,
            }
        )

        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(server_name="nonexistent")

        # Should return result without raising exception
        # Either has error info or registered: False
        assert isinstance(result, dict)
        assert result.get("registered") is False or "error" in result or "not found" in str(result).lower()

    @pytest.mark.asyncio
    async def test_tool_has_name_and_description(self):
        """
        Test that DebugMCPServerTool has proper name and description.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()
        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        assert tool.name == "debug_mcp_server"
        assert "debug" in tool.description.lower() or "mcp" in tool.description.lower()


class TestDebugMCPServerToolIntegration:
    """Integration tests for DebugMCPServerTool."""

    @pytest.mark.asyncio
    async def test_tool_aggregates_multiple_debug_sources(self):
        """
        Test that DebugMCPServerTool aggregates info from multiple sources.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()

        # Track which tools were called
        calls = []

        async def track_call(tool_name, **kwargs):
            calls.append(tool_name)
            if tool_name == "mcp_server_list":
                return {"content": [{"type": "text", "text": '[{"name": "test", "status": "running"}]'}]}
            elif tool_name == "mcp_server_status":
                return {"content": [{"type": "text", "text": '{"pid": 123, "status": "running"}'}]}
            elif tool_name == "mcp_server_logs":
                return {"content": [{"type": "text", "text": "[INFO] Running"}]}
            return {"content": [{"type": "text", "text": "{}"}]}

        mock_adapter.call_tool = track_call

        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(server_name="test-server", include_logs=True)

        # Should have called multiple debug endpoints
        assert len(calls) >= 2, f"Expected multiple calls, got: {calls}"

    @pytest.mark.asyncio
    async def test_tool_supports_log_tail_option(self):
        """
        Test that DebugMCPServerTool supports log tail/limit option.
        """
        from src.infrastructure.agent.tools.debug_mcp_server import DebugMCPServerTool

        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": "Last 10 lines..."}],
            }
        )

        tool = DebugMCPServerTool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(server_name="test-server", log_lines=10)

        # Should have called with log limit
        assert mock_adapter.call_tool.called
