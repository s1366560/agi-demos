"""Tests for PipelineMCPExecutor and MCPErrorHandler."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolAbortedError, ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.mcp.pipeline_executor import MCPErrorHandler, PipelineMCPExecutor
from src.infrastructure.mcp.tool_info import MCPCallResult


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        message_id="m",
        call_id="c",
        agent_name="a",
        conversation_id="conv",
    )


@pytest.mark.unit
class TestMCPErrorHandler:
    """Tests for MCPErrorHandler.handle_error static method."""

    def test_connection_error(self) -> None:
        result = MCPErrorHandler.handle_error("srv", "tool", ConnectionError("refused"))
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "CONNECTION_ERROR" in result.output
        assert result.metadata["error_type"] == "connection_error"
        assert result.metadata["server"] == "srv"
        assert result.metadata["tool"] == "tool"

    def test_timeout_error(self) -> None:
        result = MCPErrorHandler.handle_error("srv", "tool", TimeoutError("timed out"))
        assert result.is_error is True
        assert "TIMEOUT" in result.output

    def test_abort_error(self) -> None:
        result = MCPErrorHandler.handle_error("srv", "tool", ToolAbortedError("abort"))
        assert result.is_error is True
        assert "ABORTED" in result.output

    def test_unknown_error(self) -> None:
        result = MCPErrorHandler.handle_error("srv", "tool", RuntimeError("oops"))
        assert result.is_error is True
        assert "UNKNOWN" in result.output
        assert result.metadata["original_error"] == "oops"

    def test_title_format(self) -> None:
        result = MCPErrorHandler.handle_error("myserver", "mytool", ValueError("x"))
        assert result.title == "Error: myserver.mytool"


@pytest.mark.unit
class TestPipelineMCPExecutor:
    """Tests for PipelineMCPExecutor."""

    async def test_call_without_ctx_uses_wait_for(self) -> None:
        inner = AsyncMock()
        inner.call_tool = AsyncMock(return_value=MCPCallResult(content="ok"))
        executor = PipelineMCPExecutor(inner, default_timeout=30.0)

        result = await executor.call_tool("srv", "tool", {"x": 1})

        inner.call_tool.assert_called_once_with("srv", "tool", {"x": 1})
        assert result.content == "ok"

    async def test_call_with_ctx_uses_abort_aware(self) -> None:
        inner = AsyncMock()
        inner.call_tool = AsyncMock(return_value=MCPCallResult(content="ctx_result"))
        executor = PipelineMCPExecutor(inner, default_timeout=30.0)
        ctx = _make_ctx()

        result = await executor.call_tool("srv", "tool", {}, ctx=ctx)

        assert result.content == "ctx_result"

    async def test_timeout_override(self) -> None:
        inner = AsyncMock()

        async def slow_call(*args: object, **kwargs: object) -> MCPCallResult:
            await asyncio.sleep(10)
            return MCPCallResult(content="never")

        inner.call_tool = slow_call
        executor = PipelineMCPExecutor(inner, default_timeout=30.0)

        with pytest.raises(asyncio.TimeoutError):
            await executor.call_tool("srv", "tool", {}, timeout=0.01)

    async def test_abort_signal_propagated(self) -> None:
        inner = AsyncMock()

        async def slow_call(*args: object, **kwargs: object) -> MCPCallResult:
            await asyncio.sleep(10)
            return MCPCallResult(content="never")

        inner.call_tool = slow_call
        executor = PipelineMCPExecutor(inner, default_timeout=30.0)
        ctx = _make_ctx()

        async def fire_abort() -> None:
            await asyncio.sleep(0.01)
            ctx.abort_signal.set()

        _task = asyncio.create_task(fire_abort())  # noqa: RUF006

        with pytest.raises(ToolAbortedError):
            await executor.call_tool("srv", "tool", {}, ctx=ctx, timeout=10.0)

    async def test_default_timeout(self) -> None:
        inner = AsyncMock()
        inner.call_tool = AsyncMock(return_value=MCPCallResult(content="ok"))
        executor = PipelineMCPExecutor(inner, default_timeout=60.0)

        # Should use default timeout when none specified
        result = await executor.call_tool("srv", "tool", {})
        assert result.content == "ok"
