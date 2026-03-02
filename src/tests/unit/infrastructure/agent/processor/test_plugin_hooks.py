"""Unit tests for SessionProcessor plugin hook wiring.

Verifies that _notify_plugin_hook fires at each lifecycle point
with the correct hook name and payload keys.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)


def _make_registry(hook_side_effect=None):
    """Create a mock plugin registry with an async notify_hook."""
    registry = MagicMock()
    registry.notify_hook = AsyncMock(return_value=[], side_effect=hook_side_effect)
    return registry


def _make_tool(name="test_tool", output="ok"):
    """Create a ToolDefinition with a simple async execute."""

    async def execute(**kwargs):
        return output

    return ToolDefinition(
        name=name,
        description="A test tool",
        parameters={"type": "object", "properties": {}, "required": []},
        execute=execute,
    )


def _make_processor(*, registry=None, tools=None):
    """Build a minimal SessionProcessor with optional plugin registry."""
    config = ProcessorConfig(model="test-model", plugin_registry=registry)
    return SessionProcessor(config=config, tools=tools or [])


# ---------------------------------------------------------------------------
# _notify_plugin_hook helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotifyPluginHookHelper:
    """Tests for the _notify_plugin_hook helper method."""

    async def test_no_registry_no_error(self):
        """When plugin_registry is None, _notify_plugin_hook is a no-op."""
        proc = _make_processor(registry=None)
        # Should not raise
        await proc._notify_plugin_hook("on_session_start", {"x": 1})

    async def test_hook_called_with_correct_args(self):
        """notify_hook receives hook_name and payload."""
        registry = _make_registry()
        proc = _make_processor(registry=registry)
        payload = {"session_id": "s1"}
        await proc._notify_plugin_hook("on_session_start", payload)

        registry.notify_hook.assert_awaited_once_with("on_session_start", payload=payload)

    async def test_hook_error_does_not_propagate(self):
        """Errors inside notify_hook are caught and logged, not raised."""
        registry = _make_registry(hook_side_effect=RuntimeError("boom"))
        proc = _make_processor(registry=registry)
        # Must not raise
        await proc._notify_plugin_hook("on_error", {"err": "x"})
        registry.notify_hook.assert_awaited_once()


# ---------------------------------------------------------------------------
# process() lifecycle hooks
# ---------------------------------------------------------------------------


def _llm_text_response(text="Done"):
    """Return a fake _process_step that yields a text-end event.

    The event is recognised by _classify_step_event but does NOT trigger STOP,
    so _evaluate_goal_progress runs. We also patch _evaluate_goal_progress to
    immediately return STOP so the loop terminates cleanly.
    """
    from src.domain.events.agent_events import AgentTextEndEvent

    async def fake_process_step(session_id, messages):
        yield AgentTextEndEvent(content=text)

    return fake_process_step


def _stop_after_first_step():
    """Patch target for _evaluate_goal_progress — returns STOP immediately."""
    from src.infrastructure.agent.processor.processor import ProcessorResult

    async def patched(result, had_tool_calls, session_id, messages):
        return ProcessorResult.STOP, []

    return patched


@pytest.mark.unit
class TestProcessLifecycleHooks:
    """Tests for on_session_start, on_session_end, and on_error hooks."""

    async def test_on_session_start_fires(self):
        """on_session_start should fire after AgentStartEvent."""
        registry = _make_registry()
        proc = _make_processor(registry=registry)

        # Stub _process_step so the loop exits quickly
        proc._process_step = _llm_text_response("Done")
        proc._evaluate_goal_progress = _stop_after_first_step()

        events = []
        async for ev in proc.process("sess-1", [{"role": "user", "content": "hi"}]):
            events.append(ev)

        calls = registry.notify_hook.call_args_list
        hook_names = [c.args[0] for c in calls]
        assert "on_session_start" in hook_names

        # Verify payload
        start_call = next(c for c in calls if c.args[0] == "on_session_start")
        payload = start_call.kwargs.get("payload") or start_call.args[1]
        assert payload["session_id"] == "sess-1"
        assert "message_count" in payload

    async def test_on_session_end_fires(self):
        """on_session_end should fire after completion events."""
        registry = _make_registry()
        proc = _make_processor(registry=registry)
        proc._process_step = _llm_text_response("Done")
        proc._evaluate_goal_progress = _stop_after_first_step()

        events = []
        async for ev in proc.process("sess-2", [{"role": "user", "content": "hi"}]):
            events.append(ev)

        calls = registry.notify_hook.call_args_list
        hook_names = [c.args[0] for c in calls]
        assert "on_session_end" in hook_names

        end_call = next(c for c in calls if c.args[0] == "on_session_end")
        payload = end_call.kwargs.get("payload") or end_call.args[1]
        assert payload["session_id"] == "sess-2"
        assert "step_count" in payload
        assert "result" in payload

    async def test_on_error_fires(self):
        """on_error should fire when process() catches an exception."""
        registry = _make_registry()
        proc = _make_processor(registry=registry)

        # Make _process_step raise
        async def exploding_step(session_id, messages):
            raise RuntimeError("test explosion")
            yield

        proc._process_step = exploding_step

        events = []
        async for ev in proc.process("sess-3", [{"role": "user", "content": "hi"}]):
            events.append(ev)

        calls = registry.notify_hook.call_args_list
        hook_names = [c.args[0] for c in calls]
        assert "on_error" in hook_names

        err_call = next(c for c in calls if c.args[0] == "on_error")
        payload = err_call.kwargs.get("payload") or err_call.args[1]
        assert payload["session_id"] == "sess-3"
        assert "error" in payload
        assert payload["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# _execute_tool hooks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteToolHooks:
    """Tests for before_tool_execution and after_tool_execution hooks."""

    async def test_before_and_after_tool_hooks_fire(self):
        """Both before_ and after_tool_execution should fire for a normal tool call."""
        from src.infrastructure.agent.core.message import ToolPart, ToolState

        registry = _make_registry()
        tool = _make_tool(name="my_tool", output="result")
        proc = _make_processor(registry=registry, tools=[tool])

        # _resolve_tool_lookup expects a pending tool call entry
        tp = ToolPart(call_id="call-1", tool="my_tool", status=ToolState.PENDING)
        proc._pending_tool_calls["call-1"] = tp

        events = []
        async for ev in proc._execute_tool(
            session_id="sess-4",
            call_id="call-1",
            tool_name="my_tool",
            arguments={"arg1": "val1"},
        ):
            events.append(ev)

        calls = registry.notify_hook.call_args_list
        hook_names = [c.args[0] for c in calls]
        assert "before_tool_execution" in hook_names
        assert "after_tool_execution" in hook_names

        # before must come before after
        before_idx = hook_names.index("before_tool_execution")
        after_idx = hook_names.index("after_tool_execution")
        assert before_idx < after_idx

        # Verify before payload
        before_call = next(c for c in calls if c.args[0] == "before_tool_execution")
        bp = before_call.kwargs.get("payload") or before_call.args[1]
        assert bp["tool_name"] == "my_tool"
        assert bp["call_id"] == "call-1"
        assert bp["session_id"] == "sess-4"

        # Verify after payload
        after_call = next(c for c in calls if c.args[0] == "after_tool_execution")
        ap = after_call.kwargs.get("payload") or after_call.args[1]
        assert ap["tool_name"] == "my_tool"
        assert ap["session_id"] == "sess-4"
