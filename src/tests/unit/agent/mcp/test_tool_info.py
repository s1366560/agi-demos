"""Tests for MCPToolInfo, MCPCallResult, and mcp_tool_to_info."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.mcp.tool_info import (
    MCPCallResult,
    MCPToolInfo,
    mcp_tool_to_info,
)


@pytest.mark.unit
class TestMCPCallResult:
    """Tests for MCPCallResult dataclass."""

    def test_defaults(self) -> None:
        result = MCPCallResult(content="hello")
        assert result.content == "hello"
        assert result.is_error is False
        assert result.metadata == {}

    def test_with_error(self) -> None:
        result = MCPCallResult(content="fail", is_error=True, metadata={"code": 500})
        assert result.is_error is True
        assert result.metadata["code"] == 500

    def test_metadata_default_not_shared(self) -> None:
        r1 = MCPCallResult(content="a")
        r2 = MCPCallResult(content="b")
        r1.metadata["x"] = 1
        assert "x" not in r2.metadata


@pytest.mark.unit
class TestMCPToolInfo:
    """Tests for MCPToolInfo dataclass and execute method."""

    def _make_executor(self, return_value: MCPCallResult | None = None) -> AsyncMock:
        executor = AsyncMock()
        executor.call_tool = AsyncMock(return_value=return_value or MCPCallResult(content="ok"))
        return executor

    def test_full_name_property(self) -> None:
        info = MCPToolInfo(
            server_id="myserver",
            tool_name="read_file",
            description="Read a file",
            parameters_schema={"type": "object"},
            executor=AsyncMock(),
        )
        assert info.full_name == "mcp__myserver__read_file"

    async def test_execute_calls_executor(self) -> None:
        executor = self._make_executor(MCPCallResult(content="file content"))
        info = MCPToolInfo(
            server_id="srv",
            tool_name="read",
            description="desc",
            parameters_schema={},
            executor=executor,
        )

        result = await info.execute(path="/tmp/file.txt")

        executor.call_tool.assert_called_once_with(
            server_id="srv",
            tool_name="read",
            arguments={"path": "/tmp/file.txt"},
        )
        assert isinstance(result, ToolResult)
        assert result.output == "file content"
        assert result.is_error is False

    async def test_execute_error_result(self) -> None:
        executor = self._make_executor(MCPCallResult(content="not found", is_error=True))
        info = MCPToolInfo(
            server_id="srv",
            tool_name="read",
            description="desc",
            parameters_schema={},
            executor=executor,
        )

        result = await info.execute()

        assert result.is_error is True
        assert result.output == "not found"

    async def test_execute_metadata_propagation(self) -> None:
        executor = self._make_executor(MCPCallResult(content="ok", metadata={"timing": 42}))
        info = MCPToolInfo(
            server_id="srv",
            tool_name="tool",
            description="desc",
            parameters_schema={},
            executor=executor,
        )

        result = await info.execute()

        assert result.metadata["mcp_server"] == "srv"
        assert result.metadata["mcp_tool"] == "tool"
        assert result.metadata["timing"] == 42

    async def test_execute_title_format(self) -> None:
        executor = self._make_executor()
        info = MCPToolInfo(
            server_id="server1",
            tool_name="bash",
            description="desc",
            parameters_schema={},
            executor=executor,
        )

        result = await info.execute()
        assert result.title == "server1.bash"


@pytest.mark.unit
class TestMcpToolToInfo:
    """Tests for mcp_tool_to_info conversion function."""

    def test_converts_to_tool_info(self) -> None:
        executor = AsyncMock()
        mcp_tool = MCPToolInfo(
            server_id="sandbox",
            tool_name="grep",
            description="Search files",
            parameters_schema={"type": "object", "properties": {"pattern": {"type": "string"}}},
            executor=executor,
        )

        info = mcp_tool_to_info(mcp_tool)

        assert isinstance(info, ToolInfo)
        assert info.name == "mcp__sandbox__grep"
        assert info.description == "Search files"
        assert info.permission == "mcp"
        assert info.category == "mcp"
        assert "mcp" in info.tags
        assert "sandbox" in info.tags

    async def test_converted_tool_execute_works(self) -> None:
        executor = AsyncMock()
        executor.call_tool = AsyncMock(return_value=MCPCallResult(content="found"))
        mcp_tool = MCPToolInfo(
            server_id="s",
            tool_name="t",
            description="d",
            parameters_schema={},
            executor=executor,
        )

        info = mcp_tool_to_info(mcp_tool)
        result = await info.execute(query="test")

        assert isinstance(result, ToolResult)
        assert result.output == "found"
