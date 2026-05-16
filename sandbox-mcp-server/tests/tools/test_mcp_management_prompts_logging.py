"""Tests for MCP management prompt and logging tools."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
