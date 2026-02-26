"""Tests for ToolContext and ToolAbortedError."""

import asyncio

import pytest

from src.infrastructure.agent.tools.context import ToolAbortedError, ToolContext
from src.infrastructure.agent.tools.result import ToolEvent


@pytest.mark.unit
class TestToolAbortedError:
    """Tests for ToolAbortedError exception."""

    def test_is_exception(self) -> None:
        err = ToolAbortedError("cancelled")
        assert isinstance(err, Exception)
        assert str(err) == "cancelled"

    def test_raise_and_catch(self) -> None:
        with pytest.raises(ToolAbortedError, match="aborted"):
            raise ToolAbortedError("aborted")


@pytest.mark.unit
class TestToolContext:
    """Tests for ToolContext dataclass."""

    def _make_ctx(self, **overrides: object) -> ToolContext:
        defaults = {
            "session_id": "sess-1",
            "message_id": "msg-1",
            "call_id": "call-1",
            "agent_name": "test-agent",
            "conversation_id": "conv-1",
        }
        defaults.update(overrides)
        return ToolContext(**defaults)  # type: ignore[arg-type]

    def test_create_with_defaults(self) -> None:
        ctx = self._make_ctx()
        assert ctx.session_id == "sess-1"
        assert ctx.message_id == "msg-1"
        assert ctx.call_id == "call-1"
        assert ctx.agent_name == "test-agent"
        assert ctx.conversation_id == "conv-1"
        assert isinstance(ctx.abort_signal, asyncio.Event)
        assert ctx.abort_signal.is_set() is False
        assert ctx.messages == []
        assert ctx._pending_events == []

    async def test_metadata_emits_tool_event(self) -> None:
        # Arrange
        ctx = self._make_ctx()

        # Act
        await ctx.metadata({"key": "value"})

        # Assert
        assert len(ctx._pending_events) == 1
        event = ctx._pending_events[0]
        assert isinstance(event, ToolEvent)
        assert event.type == "metadata"
        assert event.data == {"key": "value"}
        assert event.tool_name == ""  # Filled by pipeline

    async def test_emit_appends_event(self) -> None:
        # Arrange
        ctx = self._make_ctx()
        event = {"type": "custom", "data": "test"}

        # Act
        await ctx.emit(event)

        # Assert
        assert ctx._pending_events == [event]

    async def test_emit_multiple_events(self) -> None:
        ctx = self._make_ctx()
        await ctx.emit("event1")
        await ctx.emit("event2")
        assert len(ctx._pending_events) == 2

    async def test_ask_default_returns_true(self) -> None:
        # Default implementation always grants
        ctx = self._make_ctx()
        result = await ctx.ask("bash", "Run dangerous command")
        assert result is True

    async def test_race_normal_completion(self) -> None:
        # Arrange
        ctx = self._make_ctx()

        async def quick_task() -> str:
            return "done"

        # Act
        result = await ctx.race(quick_task())

        # Assert
        assert result == "done"

    async def test_race_abort_signal(self) -> None:
        ctx = self._make_ctx()

        async def slow_task() -> str:
            await asyncio.sleep(10)
            return "never"

        # Fire abort signal after a tiny delay
        async def fire_abort() -> None:
            await asyncio.sleep(0.01)
            ctx.abort_signal.set()

        _task = asyncio.create_task(fire_abort())  # noqa: RUF006

        with pytest.raises(ToolAbortedError):
            await ctx.race(slow_task())

    async def test_race_timeout(self) -> None:
        ctx = self._make_ctx()

        async def slow_task() -> str:
            await asyncio.sleep(10)
            return "never"

        with pytest.raises(TimeoutError):
            await ctx.race(slow_task(), timeout=0.01)

    def test_consume_pending_events_returns_and_clears(self) -> None:
        ctx = self._make_ctx()
        ctx._pending_events.extend(["a", "b", "c"])

        # Act
        events = ctx.consume_pending_events()

        # Assert
        assert events == ["a", "b", "c"]
        assert ctx._pending_events == []

    def test_consume_pending_events_empty(self) -> None:
        ctx = self._make_ctx()
        events = ctx.consume_pending_events()
        assert events == []

    async def test_consume_after_metadata_and_emit(self) -> None:
        ctx = self._make_ctx()
        await ctx.metadata({"a": 1})
        await ctx.emit("custom")

        events = ctx.consume_pending_events()
        assert len(events) == 2
        assert ctx._pending_events == []
