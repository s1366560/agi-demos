"""Tests for MCP management prompt and logging tools."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.mcp_manager.manager import JSONRPC_METHOD_NOT_FOUND, SetLogLevelResult
from src.tools.mcp_management import (
    execute_mcp_server_list_prompts,
    execute_mcp_server_set_log_level,
)


def test_execute_mcp_server_list_prompts_returns_prompt_list() -> None:
    manager = MagicMock()
    manager.list_prompts = AsyncMock(return_value=[{"name": "review"}])

    with patch("src.tools.mcp_management._get_manager", return_value=manager):
        result = asyncio.run(execute_mcp_server_list_prompts("demo"))

    assert result["isError"] is False
    assert '"name": "review"' in result["content"][0]["text"]
    manager.list_prompts.assert_awaited_once_with("demo")


def test_execute_mcp_server_set_log_level_forwards_valid_level() -> None:
    manager = MagicMock()
    manager.set_log_level = AsyncMock(return_value=True)

    with patch("src.tools.mcp_management._get_manager", return_value=manager):
        result = asyncio.run(execute_mcp_server_set_log_level("demo", "DEBUG"))

    assert result["isError"] is False
    assert '"success": true' in result["content"][0]["text"]
    manager.set_log_level.assert_awaited_once_with("demo", "debug")


def test_execute_mcp_server_set_log_level_rejects_invalid_level() -> None:
    manager = MagicMock()

    with patch("src.tools.mcp_management._get_manager", return_value=manager):
        result = asyncio.run(execute_mcp_server_set_log_level("demo", "verbose"))

    assert result["isError"] is True
    manager.set_log_level.assert_not_called()


def _payload(result: dict) -> dict:
    import json

    return json.loads(result["content"][0]["text"])


def test_execute_mcp_server_set_log_level_reports_method_not_supported() -> None:
    manager = MagicMock()
    manager.set_log_level = AsyncMock(
        return_value=SetLogLevelResult(
            ok=False,
            code="method_not_supported",
            message="MCP server 'probe_server' does not support logging/setLevel (JSON-RPC MethodNotFound). This is a capability limitation of the server, not a runtime crash.",
            server_name="probe_server",
            level="debug",
            rpc_code=JSONRPC_METHOD_NOT_FOUND,
        )
    )

    with patch("src.tools.mcp_management._get_manager", return_value=manager):
        result = asyncio.run(execute_mcp_server_set_log_level("probe_server", "debug"))

    assert result["isError"] is True
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["code"] == "method_not_supported"
    assert payload["error"]["code"] == "method_not_supported"
    assert payload["error"]["rpc_code"] == JSONRPC_METHOD_NOT_FOUND
    assert "capability limitation" in payload["error"]["message"]


def test_execute_mcp_server_set_log_level_reports_server_not_running() -> None:
    manager = MagicMock()
    manager.set_log_level = AsyncMock(
        return_value=SetLogLevelResult(
            ok=False,
            code="server_not_running",
            message="MCP server 'probe_server' is not running (status=stopped).",
            server_name="probe_server",
            level="info",
        )
    )

    with patch("src.tools.mcp_management._get_manager", return_value=manager):
        result = asyncio.run(execute_mcp_server_set_log_level("probe_server", "info"))

    payload = _payload(result)
    assert result["isError"] is True
    assert payload["error"]["code"] == "server_not_running"


def test_execute_mcp_server_set_log_level_reports_protocol_error() -> None:
    manager = MagicMock()
    manager.set_log_level = AsyncMock(
        return_value=SetLogLevelResult(
            ok=False,
            code="protocol_error",
            message="MCP server 'probe_server' rejected logging/setLevel: Invalid params",
            server_name="probe_server",
            level="debug",
            rpc_code=-32602,
        )
    )

    with patch("src.tools.mcp_management._get_manager", return_value=manager):
        result = asyncio.run(execute_mcp_server_set_log_level("probe_server", "debug"))

    payload = _payload(result)
    assert result["isError"] is True
    assert payload["error"]["code"] == "protocol_error"
    assert payload["error"]["rpc_code"] == -32602
