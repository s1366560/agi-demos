"""Tests for abort_aware_gather and abort_aware_timeout."""

import asyncio

import pytest

from src.infrastructure.agent.tools.abort import abort_aware_gather, abort_aware_timeout
from src.infrastructure.agent.tools.context import ToolAbortedError, ToolContext


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        message_id="m",
        call_id="c",
        agent_name="a",
        conversation_id="conv",
    )


@pytest.mark.unit
class TestAbortAwareGather:
    """Tests for abort_aware_gather."""

    async def test_all_complete_normally(self) -> None:
        ctx = _make_ctx()

        async def task1() -> int:
            return 1

        async def task2() -> int:
            return 2

        results = await abort_aware_gather(ctx, task1(), task2())
        assert results == [1, 2]

    async def test_abort_during_execution(self) -> None:
        ctx = _make_ctx()

        async def slow() -> str:
            await asyncio.sleep(10)
            return "never"

        async def fire_abort() -> None:
            await asyncio.sleep(0.01)
            ctx.abort_signal.set()

        _task = asyncio.create_task(fire_abort())  # noqa: RUF006

        with pytest.raises(ToolAbortedError, match="Aborted"):
            await abort_aware_gather(ctx, slow())

    async def test_exception_in_coroutine_propagates(self) -> None:
        ctx = _make_ctx()

        async def failing() -> None:
            raise ValueError("boom")

        async def ok() -> int:
            return 1

        with pytest.raises(ValueError, match="boom"):
            await abort_aware_gather(ctx, failing(), ok())

    async def test_return_exceptions_mode(self) -> None:
        ctx = _make_ctx()

        async def failing() -> None:
            raise ValueError("err")

        async def ok() -> int:
            return 42

        # With return_exceptions, exceptions are returned as values
        # Note: the behavior depends on task completion order
        results = await abort_aware_gather(ctx, ok(), return_exceptions=True)
        assert results == [42]

    async def test_empty_coroutines_returns_immediately(self) -> None:
        """With no coros, gather returns empty list immediately."""
        ctx = _make_ctx()
        results = await abort_aware_gather(ctx)
        assert results == []

    async def test_single_coroutine(self) -> None:
        ctx = _make_ctx()

        async def single() -> str:
            return "one"

        results = await abort_aware_gather(ctx, single())
        assert results == ["one"]


@pytest.mark.unit
class TestAbortAwareTimeout:
    """Tests for abort_aware_timeout."""

    async def test_completes_before_timeout(self) -> None:
        ctx = _make_ctx()

        async def quick() -> str:
            return "done"

        result = await abort_aware_timeout(ctx, quick(), timeout_seconds=5.0)
        assert result == "done"

    async def test_timeout_exceeded(self) -> None:
        ctx = _make_ctx()

        async def slow() -> str:
            await asyncio.sleep(10)
            return "never"

        with pytest.raises(TimeoutError, match="timed out"):
            await abort_aware_timeout(ctx, slow(), timeout_seconds=0.01)

    async def test_abort_before_timeout(self) -> None:
        ctx = _make_ctx()

        async def slow() -> str:
            await asyncio.sleep(10)
            return "never"

        async def fire_abort() -> None:
            await asyncio.sleep(0.01)
            ctx.abort_signal.set()

        _task = asyncio.create_task(fire_abort())  # noqa: RUF006

        with pytest.raises(ToolAbortedError, match="Aborted"):
            await abort_aware_timeout(ctx, slow(), timeout_seconds=10.0)

    async def test_result_type_preserved(self) -> None:
        ctx = _make_ctx()

        async def typed_task() -> dict:
            return {"key": "value"}

        result = await abort_aware_timeout(ctx, typed_task(), timeout_seconds=5.0)
        assert result == {"key": "value"}
