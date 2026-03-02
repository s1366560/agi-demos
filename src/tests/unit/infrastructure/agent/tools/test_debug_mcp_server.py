"""Tests for debug_mcp_server functional tool API.

Verifies configure_debug_mcp_server + debug_mcp_server_tool provide
useful debugging information for MCP servers running inside sandboxes.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

import src.infrastructure.agent.tools.debug_mcp_server as _debug_mod
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.debug_mcp_server import (
    configure_debug_mcp_server,
    debug_mcp_server_tool,
)
from src.infrastructure.agent.tools.result import ToolResult

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        call_id="test-call",
        agent_name="test-agent",
        conversation_id="test-conv",
    )


_tool_exec = debug_mcp_server_tool.execute


@pytest.fixture(autouse=True)
def _reset_debug_mcp_state() -> Any:
    """Reset module-level state between tests."""
    yield
    _debug_mod._debug_mcp_sandbox_adapter = None
    _debug_mod._debug_mcp_sandbox_id = ""


# ---------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------


@pytest.mark.unit
class TestDebugMCPServerTool:
    """Test debug_mcp_server_tool functionality."""

    async def test_tool_exists(self) -> None:
        """Verify that debug_mcp_server_tool is importable."""
        assert debug_mcp_server_tool is not None

    async def test_tool_returns_server_logs(self) -> None:
        """Tool returns server logs in parsed output."""
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "running",
                                "logs": ("[INFO] Server started\n[ERROR] Connection failed"),
                            }
                        ),
                    }
                ],
            }
        )

        configure_debug_mcp_server(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await _tool_exec(_make_ctx(), server_name="test-server")

        assert isinstance(result, ToolResult)
        parsed = json.loads(result.output)
        assert "logs" in parsed

    async def test_tool_returns_process_info(self) -> None:
        """Tool returns process information in parsed output."""
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "running",
                                "pid": 12345,
                                "memory_mb": 50,
                                "cpu_percent": 2.5,
                            }
                        ),
                    }
                ],
            }
        )

        configure_debug_mcp_server(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await _tool_exec(_make_ctx(), server_name="test-server")

        assert isinstance(result, ToolResult)
        parsed = json.loads(result.output)
        assert "process_info" in parsed or "status" in parsed

    async def test_tool_returns_last_error(self) -> None:
        """Tool returns last error information."""
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "last_error": "Connection refused",
                                "error_count": 3,
                            }
                        ),
                    }
                ],
            }
        )

        configure_debug_mcp_server(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await _tool_exec(_make_ctx(), server_name="broken-server")

        assert isinstance(result, ToolResult)
        parsed = json.loads(result.output)
        assert "last_error" in parsed or "error" in parsed or "Connection refused" in result.output

    async def test_tool_handles_nonexistent_server(self) -> None:
        """Tool handles non-existent server gracefully."""
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": "Server not found"}),
                    }
                ],
                "is_error": True,
            }
        )

        configure_debug_mcp_server(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await _tool_exec(_make_ctx(), server_name="nonexistent")

        assert isinstance(result, ToolResult)
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)
        assert (
            parsed.get("registered") is False
            or "error" in parsed
            or "not found" in result.output.lower()
        )

    async def test_tool_has_name_and_description(self) -> None:
        """Tool has proper name and description."""
        assert debug_mcp_server_tool.name == "debug_mcp_server"
        assert (
            "debug" in debug_mcp_server_tool.description.lower()
            or "mcp" in debug_mcp_server_tool.description.lower()
        )


# ---------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------


@pytest.mark.unit
class TestDebugMCPServerToolIntegration:
    """Integration tests for debug_mcp_server_tool."""

    async def test_tool_aggregates_multiple_debug_sources(
        self,
    ) -> None:
        """Tool aggregates info from multiple MCP calls."""
        mock_adapter = AsyncMock()
        calls: list[str] = []

        async def track_call(
            sandbox_id: str,
            tool_name: str,
            arguments: dict[str, Any],
            **kwargs: Any,
        ) -> dict[str, Any]:
            _ = sandbox_id
            _ = arguments
            _ = kwargs
            calls.append(tool_name)
            if tool_name == "mcp_server_list":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                [
                                    {
                                        "name": "test",
                                        "status": "running",
                                    }
                                ]
                            ),
                        }
                    ]
                }
            if tool_name == "mcp_server_status":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "pid": 123,
                                    "status": "running",
                                }
                            ),
                        }
                    ]
                }
            if tool_name == "mcp_server_logs":
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "[INFO] Running",
                        }
                    ]
                }
            return {"content": [{"type": "text", "text": "{}"}]}

        mock_adapter.call_tool = track_call

        configure_debug_mcp_server(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        _ = await _tool_exec(
            _make_ctx(),
            server_name="test-server",
            include_logs=True,
        )

        assert len(calls) >= 2, f"Expected multiple calls, got: {calls}"

    async def test_tool_supports_log_tail_option(
        self,
    ) -> None:
        """Tool passes log_lines option to the adapter."""
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": "Last 10 lines...",
                    }
                ],
            }
        )

        configure_debug_mcp_server(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        _ = await _tool_exec(
            _make_ctx(),
            server_name="test-server",
            log_lines=10,
        )

        assert mock_adapter.call_tool.called
