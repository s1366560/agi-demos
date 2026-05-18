"""Tests for function-based MCP ToolInfo factories."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.agent.mcp.adapter import (
    create_all_mcp_tools,
    create_mcp_tool,
    create_mcp_tool_by_name,
    create_mcp_tools_from_server,
    mcp_tool_name,
)
from src.infrastructure.agent.tools.context import ToolContext


def _make_context() -> ToolContext:
    return ToolContext(
        session_id="session-1",
        message_id="message-1",
        call_id="call-1",
        agent_name="agent",
        conversation_id="conversation-1",
    )


def _tool_definition(name: str = "lookup") -> dict[str, Any]:
    return {
        "name": name,
        "description": "Lookup records",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }


@pytest.mark.unit
def test_mcp_tool_name_uses_standard_namespace() -> None:
    assert mcp_tool_name("server-a", "lookup") == "mcp__server-a__lookup"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_mcp_tool_builds_toolinfo_and_calls_registry() -> None:
    registry = Mock()
    registry.call_tool = AsyncMock(return_value={"items": ["one"]})
    info = create_mcp_tool("server-a", _tool_definition(), registry)

    assert info.name == "mcp__server-a__lookup"
    assert info.description == "[MCP] Lookup records"
    assert info.parameters["required"] == ["query"]
    assert info.category == "mcp"
    assert info.tags == frozenset({"mcp", "server-a"})

    result = await info.execute(_make_context(), query="abc")

    assert result.is_error is False
    assert json.loads(result.output) == {"items": ["one"]}
    registry.call_tool.assert_awaited_once_with(
        server_id="server-a",
        tool_name="lookup",
        arguments={"query": "abc"},
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_mcp_tool_returns_tool_result_error_on_registry_failure() -> None:
    registry = Mock()
    registry.call_tool = AsyncMock(side_effect=RuntimeError("offline"))
    info = create_mcp_tool("server-a", _tool_definition(), registry)

    result = await info.execute(_make_context(), query="abc")

    assert result.is_error is True
    assert result.output == "MCP tool execution failed: offline"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_mcp_tools_from_server_builds_all_server_tools() -> None:
    registry = Mock()
    registry.get_tools = AsyncMock(return_value=[_tool_definition("a"), _tool_definition("b")])

    infos = await create_mcp_tools_from_server("server-a", registry)

    assert [info.name for info in infos] == ["mcp__server-a__a", "mcp__server-a__b"]
    registry.get_tools.assert_awaited_once_with("server-a")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_all_mcp_tools_builds_registered_server_tools() -> None:
    registry = Mock()
    registry.get_registered_servers.return_value = ["server-a", "server-b"]
    registry.get_tools = AsyncMock(
        side_effect=[
            [_tool_definition("a")],
            [_tool_definition("b")],
        ]
    )

    infos = await create_all_mcp_tools(registry)

    assert [info.name for info in infos] == ["mcp__server-a__a", "mcp__server-b__b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_mcp_tool_by_name_returns_matching_toolinfo() -> None:
    registry = Mock()
    registry.get_tools = AsyncMock(return_value=[_tool_definition("a"), _tool_definition("b")])

    info = await create_mcp_tool_by_name("server-a", "b", registry)

    assert info is not None
    assert info.name == "mcp__server-a__b"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_mcp_tool_by_name_returns_none_when_missing() -> None:
    registry = Mock()
    registry.get_tools = AsyncMock(return_value=[_tool_definition("a")])

    info = await create_mcp_tool_by_name("server-a", "missing", registry)

    assert info is None
