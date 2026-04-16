"""Unit tests for SessionProcessor tool refresh functionality.

Tests that the processor can refresh its tools dynamically when
register_mcp_server tool succeeds, enabling immediate access to
newly registered MCP tools without session restart.

TDD Task: Fix ReAct Agent not refreshing tools after register_mcp_server
"""

from typing import Any

import pytest

from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.result import ToolResult


class MockTool:
    """Simple mock tool for testing."""

    def __init__(self, name: str, description: str = "A mock tool") -> None:
        self.name = name
        self.description = description

    async def execute(self, **kwargs) -> str:
        return f"Executed {self.name}"

    def get_parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


def create_tool_def(name: str, description: str = "Test tool") -> ToolDefinition:
    """Helper to create a ToolDefinition."""
    return ToolDefinition(
        name=name,
        description=description,
        parameters={"type": "object", "properties": {}, "required": []},
        execute=lambda **kwargs: f"Executed {name}",
    )


@pytest.mark.unit
class TestProcessorConfigToolProvider:
    """Tests for ProcessorConfig tool_provider field."""

    def test_config_defaults_to_no_tool_provider(self):
        """Should default tool_provider to None."""
        config = ProcessorConfig(model="test-model")
        assert config.tool_provider is None

    def test_config_accepts_tool_provider(self):
        """Should accept tool_provider as a callable."""

        def provider() -> list:
            return [create_tool_def("test_tool")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        assert config.tool_provider is provider

    def test_config_accepts_async_tool_provider(self):
        """Should accept async tool_provider callable."""

        async def async_provider() -> list:
            return [create_tool_def("async_tool")]

        config = ProcessorConfig(model="test-model", tool_provider=async_provider)
        assert config.tool_provider is async_provider


@pytest.mark.unit
class TestSessionProcessorToolRefresh:
    """Tests for SessionProcessor._refresh_tools() method."""

    def test_processor_stores_tool_provider_from_config(self):
        """Should store tool_provider from config."""

        def provider() -> list:
            return [create_tool_def("tool1")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        assert processor._tool_provider is provider

    def test_processor_tool_provider_defaults_to_none(self):
        """Should have _tool_provider as None when not provided."""
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        assert processor._tool_provider is None

    def test_refresh_tools_without_provider_does_nothing(self):
        """Should do nothing when no tool_provider configured."""
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Should not raise, should just return None
        result = processor._refresh_tools()

        assert result is None
        # Tools should remain unchanged
        assert "initial" in processor.tools

    def test_refresh_tools_with_provider_updates_tools(self):
        """Should update tools when tool_provider is set."""
        call_count = 0

        def dynamic_provider() -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [create_tool_def("tool_v1")]
            else:
                return [create_tool_def("tool_v1"), create_tool_def("tool_v2")]

        config = ProcessorConfig(model="test-model", tool_provider=dynamic_provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Initial state
        assert "initial" in processor.tools
        assert "tool_v1" not in processor.tools

        # First refresh - gets tool_v1
        processor._refresh_tools()
        assert "tool_v1" in processor.tools
        assert "tool_v2" not in processor.tools

        # Second refresh - gets tool_v1 and tool_v2
        processor._refresh_tools()
        assert "tool_v1" in processor.tools
        assert "tool_v2" in processor.tools

    def test_refresh_tools_returns_new_tool_count(self):
        """Should return the number of tools after refresh."""

        def provider() -> list:
            return [create_tool_def("a"), create_tool_def("b"), create_tool_def("c")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[])

        result = processor._refresh_tools()

        assert result == 3

    def test_refresh_tools_keeps_goal_evaluator_tool_reference_in_sync(self):
        """GoalEvaluator should observe refreshed tools without re-binding."""

        def provider() -> list:
            return [create_tool_def("todoread")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])
        original_tools_ref = processor._goal_evaluator._tools

        processor._refresh_tools()

        assert processor.tools is original_tools_ref
        assert processor._goal_evaluator.has_task_reader() is True


@pytest.mark.unit
class TestProcessorToolRefreshAfterRegister:
    """Tests for tool refresh after register_mcp_server execution."""

    @pytest.mark.asyncio
    async def test_execute_tool_refreshes_after_register_mcp_server_success(self):
        """Should call _refresh_tools after successful register_mcp_server."""
        refresh_called = False

        def provider() -> list:
            return [create_tool_def("mcp__server__tool")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Mock _refresh_tools to track calls
        original_refresh = processor._refresh_tools

        def mock_refresh():
            nonlocal refresh_called
            refresh_called = True
            return original_refresh()

        processor._refresh_tools = mock_refresh

        # Create a mock register_mcp_server tool that succeeds
        async def mock_execute(**kwargs):
            return "MCP server registered successfully"

        register_tool = ToolDefinition(
            name="register_mcp_server",
            description="Register MCP server",
            parameters={},
            execute=mock_execute,
        )
        processor.tools["register_mcp_server"] = register_tool

        # Create a pending tool call
        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-123"] = ToolPart(
            call_id="call-123",
            tool="register_mcp_server",
            input={},
            status=ToolState.RUNNING,
        )

        # Execute the tool
        events = []
        async for event in processor._execute_tool(
            session_id="test-session",
            call_id="call-123",
            tool_name="register_mcp_server",
            arguments={"server_name": "test-server", "server_type": "stdio"},
        ):
            events.append(event)

        # Verify refresh was called
        assert refresh_called, "_refresh_tools should be called after register_mcp_server"

    @pytest.mark.asyncio
    async def test_execute_tool_does_not_refresh_on_register_failure(self):
        """Should NOT call _refresh_tools if register_mcp_server fails."""
        refresh_called = False

        def provider() -> list:
            return [create_tool_def("tool")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Track refresh calls
        original_refresh = processor._refresh_tools

        def mock_refresh():
            nonlocal refresh_called
            refresh_called = True
            return original_refresh()

        processor._refresh_tools = mock_refresh

        # Create a mock register_mcp_server tool that FAILS
        async def mock_execute(**kwargs):
            return "Error: Failed to register MCP server"

        register_tool = ToolDefinition(
            name="register_mcp_server",
            description="Register MCP server",
            parameters={},
            execute=mock_execute,
        )
        processor.tools["register_mcp_server"] = register_tool

        # Create a pending tool call
        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-456"] = ToolPart(
            call_id="call-456",
            tool="register_mcp_server",
            input={},
            status=ToolState.RUNNING,
        )

        # Execute the tool
        async for _ in processor._execute_tool(
            session_id="test-session",
            call_id="call-456",
            tool_name="register_mcp_server",
            arguments={"server_name": "bad-server", "server_type": "stdio"},
        ):
            pass

        # Verify refresh was NOT called (tool failed)
        assert not refresh_called, "_refresh_tools should NOT be called on failure"

    @pytest.mark.asyncio
    async def test_execute_tool_does_not_refresh_other_tools(self):
        """Should NOT call _refresh_tools for tools other than register_mcp_server."""
        refresh_called = False

        def provider() -> list:
            return [create_tool_def("tool")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Track refresh calls
        processor._refresh_tools = (
            lambda: setattr(
                type("obj", (object,), {"refresh_called": True})(), "refresh_called", True
            )
            or True
        )

        original_method = processor._refresh_tools

        def track_refresh():
            nonlocal refresh_called
            refresh_called = True
            return original_method()

        processor._refresh_tools = track_refresh

        # Create a regular tool
        async def mock_execute(**kwargs):
            return "Success"

        regular_tool = ToolDefinition(
            name="some_other_tool",
            description="Some other tool",
            parameters={},
            execute=mock_execute,
        )
        processor.tools["some_other_tool"] = regular_tool

        # Create a pending tool call
        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-789"] = ToolPart(
            call_id="call-789",
            tool="some_other_tool",
            input={},
            status=ToolState.RUNNING,
        )

        # Execute the tool
        async for _ in processor._execute_tool(
            session_id="test-session",
            call_id="call-789",
            tool_name="some_other_tool",
            arguments={},
        ):
            pass

        # Verify refresh was NOT called for non-register tool
        assert not refresh_called, "_refresh_tools should only be called for register_mcp_server"

    @pytest.mark.asyncio
    async def test_refresh_makes_new_tools_immediately_available(self):
        """New tools from refresh should be immediately available for next LLM call."""
        tool_registry = {"initial": create_tool_def("initial")}

        def dynamic_provider() -> list:
            return list(tool_registry.values())

        config = ProcessorConfig(model="test-model", tool_provider=dynamic_provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Initially only has initial tool
        assert "initial" in processor.tools
        assert "mcp__new__tool" not in processor.tools

        # Simulate register_mcp_server success adding a new tool to registry
        tool_registry["mcp__new__tool"] = create_tool_def("mcp__new__tool")

        # Refresh tools
        processor._refresh_tools()

        # New tool should now be available
        assert "mcp__new__tool" in processor.tools


@pytest.mark.unit
class TestProcessorToolRefreshEdgeCases:
    """Edge cases for tool refresh functionality."""

    def test_refresh_with_provider_returning_empty_list(self):
        """Should handle provider returning empty list."""

        def empty_provider() -> list:
            return []

        config = ProcessorConfig(model="test-model", tool_provider=empty_provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        result = processor._refresh_tools()

        assert result is None
        # Guard: existing tools are preserved when provider returns empty
        assert len(processor.tools) == 1
        assert "initial" in processor.tools

    def test_refresh_with_provider_raising_exception(self):
        """Should handle provider raising exception gracefully."""

        def bad_provider() -> list:
            raise RuntimeError("Provider failed")

        config = ProcessorConfig(model="test-model", tool_provider=bad_provider)
        processor = SessionProcessor(config=config, tools=[create_tool_def("initial")])

        # Should not raise, should log warning and return None
        result = processor._refresh_tools()

        assert result is None
        # Tools should remain unchanged
        assert "initial" in processor.tools

    @pytest.mark.asyncio
    async def test_refresh_with_async_provider(self):
        """Should handle async tool_provider gracefully.

        Since _refresh_tools is synchronous, calling it with an async
        provider will return a coroutine object rather than a list.
        The implementation handles this gracefully by catching the TypeError.
        """

        async def async_provider() -> list:
            # Simulate async tool loading
            return [create_tool_def("async_tool")]

        config = ProcessorConfig(model="test-model", tool_provider=async_provider)
        processor = SessionProcessor(config=config, tools=[])

        # _refresh_tools should handle async provider gracefully
        # (returns None when TypeError is raised from trying to iterate coroutine)
        _ = processor._refresh_tools()

        # For async providers, sync call should be handled gracefully
        # The tools dict should remain unchanged since we can't iterate a coroutine
        assert "async_tool" not in processor.tools

    def test_refresh_preserves_tool_order(self):
        """Should preserve tool order from provider."""

        def provider() -> list:
            return [
                create_tool_def("tool_a"),
                create_tool_def("tool_b"),
                create_tool_def("tool_c"),
            ]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[])

        processor._refresh_tools()

        # Order should be preserved (dicts maintain insertion order in Python 3.7+)
        names = list(processor.tools.keys())
        assert names == ["tool_a", "tool_b", "tool_c"]


@pytest.mark.unit
class TestProcessorPendingToolEvents:
    """Tests for pending event emission from self-modifying tools."""

    @pytest.mark.asyncio
    async def test_execute_tool_emits_pending_events_for_skill_sync(self):
        """Processor should emit toolset_changed dict events from skill_sync."""
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])

        class _SkillSyncTool:
            def __init__(self) -> None:
                self._events = [{"type": "toolset_changed", "data": {"source": "skill_sync"}}]

            async def execute(self, **kwargs):
                return "Skill synced"

            def consume_pending_events(self):
                events = list(self._events)
                self._events.clear()
                return events

        tool_instance = _SkillSyncTool()
        processor.tools["skill_sync"] = ToolDefinition(
            name="skill_sync",
            description="Skill sync tool",
            parameters={},
            execute=tool_instance.execute,
            _tool_instance=tool_instance,
        )

        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-skill-sync"] = ToolPart(
            call_id="call-skill-sync",
            tool="skill_sync",
            input={},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="test-session",
            call_id="call-skill-sync",
            tool_name="skill_sync",
            arguments={"skill_name": "demo-skill"},
        ):
            events.append(event)

        assert any(
            isinstance(event, dict) and event.get("type") == "toolset_changed" for event in events
        )

    @pytest.mark.asyncio
    async def test_plugin_manager_toolset_event_includes_refresh_metadata(self):
        """plugin_manager toolset_changed events should include refresh diagnostics."""

        def provider() -> list:
            return [create_tool_def("tool_a"), create_tool_def("tool_b")]

        config = ProcessorConfig(model="test-model", tool_provider=provider)
        processor = SessionProcessor(config=config, tools=[])

        class _PluginManagerTool:
            def __init__(self) -> None:
                self._events = [
                    {
                        "type": "toolset_changed",
                        "data": {
                            "source": "plugin_manager",
                            "action": "reload",
                        },
                    }
                ]

            async def execute(self, **kwargs):
                return "Plugin runtime reloaded"

            def consume_pending_events(self):
                events = list(self._events)
                self._events.clear()
                return events

        tool_instance = _PluginManagerTool()
        processor.tools["plugin_manager"] = ToolDefinition(
            name="plugin_manager",
            description="Plugin manager tool",
            parameters={},
            execute=tool_instance.execute,
            _tool_instance=tool_instance,
        )

        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-plugin-manager"] = ToolPart(
            call_id="call-plugin-manager",
            tool="plugin_manager",
            input={},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="test-session",
            call_id="call-plugin-manager",
            tool_name="plugin_manager",
            arguments={"action": "reload"},
        ):
            events.append(event)

        toolset_changed_event = next(
            event
            for event in events
            if isinstance(event, dict) and event.get("type") == "toolset_changed"
        )
        assert toolset_changed_event["data"]["refresh_source"] == "processor"
        assert toolset_changed_event["data"]["refresh_status"] == "success"
        assert toolset_changed_event["data"]["refreshed_tool_count"] == 3

    @pytest.mark.asyncio
    async def test_plugin_manager_toolset_event_marks_refresh_skipped_on_error(self):
        """plugin_manager toolset_changed events should mark refresh as skipped on failures."""
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])

        class _PluginManagerTool:
            def __init__(self) -> None:
                self._events = [
                    {
                        "type": "toolset_changed",
                        "data": {
                            "source": "plugin_manager",
                            "action": "reload",
                        },
                    }
                ]

            async def execute(self, **kwargs):
                return "Error: plugin reload failed"

            def consume_pending_events(self):
                events = list(self._events)
                self._events.clear()
                return events

        tool_instance = _PluginManagerTool()
        processor.tools["plugin_manager"] = ToolDefinition(
            name="plugin_manager",
            description="Plugin manager tool",
            parameters={},
            execute=tool_instance.execute,
            _tool_instance=tool_instance,
        )

        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-plugin-manager-error"] = ToolPart(
            call_id="call-plugin-manager-error",
            tool="plugin_manager",
            input={},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="test-session",
            call_id="call-plugin-manager-error",
            tool_name="plugin_manager",
            arguments={"action": "reload"},
        ):
            events.append(event)

        toolset_changed_event = next(
            event
            for event in events
            if isinstance(event, dict) and event.get("type") == "toolset_changed"
        )
        assert toolset_changed_event["data"]["refresh_status"] == "skipped"
        assert "refreshed_tool_count" not in toolset_changed_event["data"]


@pytest.mark.unit
class TestWorkspaceDelegationRecoveryHint:
    @pytest.mark.asyncio
    async def test_delegate_guardrail_error_queues_recovery_hint(self):
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])

        async def mock_execute(**kwargs):
            return ToolResult(
                output=(
                    "Error: workspace-authority delegation requires workspace_task_id. "
                    "Call todoread first, select the target child task's workspace_task_id, "
                    "then retry delegate_to_subagent."
                ),
                is_error=True,
            )

        delegate_tool = ToolDefinition(
            name="delegate_to_subagent",
            description="Delegate to subagent",
            parameters={},
            execute=mock_execute,
        )
        processor.tools["delegate_to_subagent"] = delegate_tool

        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-delegate-guardrail"] = ToolPart(
            call_id="call-delegate-guardrail",
            tool="delegate_to_subagent",
            input={},
            status=ToolState.RUNNING,
        )

        async for _ in processor._execute_tool(
            session_id="test-session",
            call_id="call-delegate-guardrail",
            tool_name="delegate_to_subagent",
            arguments={"subagent_name": "worker", "task": "do work"},
        ):
            pass

        assert (
            SessionProcessor._WORKSPACE_DELEGATION_RECOVERY_HINT
            in processor._response_instructions
        )

    @pytest.mark.asyncio
    async def test_todoread_success_clears_workspace_recovery_hint(self):
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])
        processor._response_instructions = [
            SessionProcessor._WORKSPACE_DELEGATION_RECOVERY_HINT,
            f"{SessionProcessor._WORKSPACE_TODOREAD_SNAPSHOT_PREFIX} stale snapshot",
            f"{SessionProcessor._WORKSPACE_DELEGATION_RETRY_ACTION_PREFIX} stale retry",
            "keep me",
        ]

        async def mock_execute(**kwargs):
            return ToolResult(
                output='{"todos": []}',
                is_error=False,
            )

        todoread_tool = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={},
            execute=mock_execute,
        )
        processor.tools["todoread"] = todoread_tool

        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-todoread-success"] = ToolPart(
            call_id="call-todoread-success",
            tool="todoread",
            input={},
            status=ToolState.RUNNING,
        )

        async for _ in processor._execute_tool(
            session_id="test-session",
            call_id="call-todoread-success",
            tool_name="todoread",
            arguments={},
        ):
            pass

        assert SessionProcessor._WORKSPACE_DELEGATION_RECOVERY_HINT not in processor._response_instructions
        assert not any(
            item.startswith(SessionProcessor._WORKSPACE_TODOREAD_SNAPSHOT_PREFIX)
            for item in processor._response_instructions
        )
        assert not any(
            item.startswith(SessionProcessor._WORKSPACE_DELEGATION_RETRY_ACTION_PREFIX)
            for item in processor._response_instructions
        )
        assert processor._response_instructions == ["keep me"]

    @pytest.mark.asyncio
    async def test_delegate_guardrail_error_injects_todoread_snapshot_hint(self):
        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])

        async def delegate_execute(**kwargs):
            return ToolResult(
                output=(
                    "Error: workspace-authority delegation requires workspace_task_id. "
                    "Call todoread first, select the target child task's workspace_task_id, "
                    "then retry delegate_to_subagent."
                ),
                is_error=True,
            )

        async def todoread_execute(**kwargs):
            return ToolResult(
                output=(
                    '{"todos":['
                    '{"id":"t1","workspace_task_id":"wt-1","content":"Task A","status":"pending"},'
                    '{"id":"t2","workspace_task_id":"wt-2","content":"Task B","status":"pending"}'
                    ']}'
                ),
                is_error=False,
            )

        processor.tools["delegate_to_subagent"] = ToolDefinition(
            name="delegate_to_subagent",
            description="Delegate to subagent",
            parameters={},
            execute=delegate_execute,
        )
        processor.tools["todoread"] = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={},
            execute=todoread_execute,
        )

        from src.infrastructure.agent.core.message import ToolPart, ToolState

        processor._pending_tool_calls["call-delegate-guardrail-snapshot"] = ToolPart(
            call_id="call-delegate-guardrail-snapshot",
            tool="delegate_to_subagent",
            input={},
            status=ToolState.RUNNING,
        )

        async for _ in processor._execute_tool(
            session_id="test-session",
            call_id="call-delegate-guardrail-snapshot",
            tool_name="delegate_to_subagent",
            arguments={"subagent_name": "worker", "task": "do work"},
        ):
            pass

        assert any(
            item.startswith(SessionProcessor._WORKSPACE_TODOREAD_SNAPSHOT_PREFIX)
            and "wt-1" in item
            and "Available tasks" in item
            for item in processor._response_instructions
        )
        assert not any(
            item.startswith(SessionProcessor._WORKSPACE_DELEGATION_RETRY_ACTION_PREFIX)
            for item in processor._response_instructions
        )

    @pytest.mark.asyncio
    async def test_delegate_guardrail_error_auto_retries_single_candidate(self):
        from src.domain.events.agent_events import AgentActEvent
        from src.infrastructure.agent.core.message import ToolPart, ToolState

        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])

        call_count = 0

        async def delegate_execute(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ToolResult(
                    output=(
                        "Error: workspace-authority delegation requires workspace_task_id. "
                        "Call todoread first, select the target child task's workspace_task_id, "
                        "then retry delegate_to_subagent."
                    ),
                    is_error=True,
                )
            assert kwargs["workspace_task_id"] == "wt-1"
            return ToolResult(output="delegated successfully", is_error=False)

        async def todoread_execute(**kwargs):
            return ToolResult(
                output='{"todos":[{"id":"t1","workspace_task_id":"wt-1","content":"Task A","status":"pending"}]}',
                is_error=False,
            )

        processor.tools["delegate_to_subagent"] = ToolDefinition(
            name="delegate_to_subagent",
            description="Delegate to subagent",
            parameters={},
            execute=delegate_execute,
        )
        processor.tools["todoread"] = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={},
            execute=todoread_execute,
        )

        processor._pending_tool_calls["call-delegate-auto-retry"] = ToolPart(
            call_id="call-delegate-auto-retry",
            tool="delegate_to_subagent",
            input={},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="test-session",
            call_id="call-delegate-auto-retry",
            tool_name="delegate_to_subagent",
            arguments={"subagent_name": "worker", "task": "do work"},
        ):
            events.append(event)

        retry_act = next(
            event
            for event in events
            if isinstance(event, AgentActEvent)
            and event.call_id == "call-delegate-auto-retry-workspace-retry"
        )
        assert retry_act.tool_input["workspace_task_id"] == "wt-1"
        assert call_count == 2

    def test_workspace_todoread_snapshot_prefers_single_active_candidate(self):
        output = (
            '{"todos":['
            '{"id":"t1","workspace_task_id":"wt-1","content":"Task A","status":"pending"},'
            '{"id":"t2","workspace_task_id":"wt-2","content":"Task B","status":"completed"}'
            "]}"
        )

        summary = SessionProcessor._summarize_workspace_todoread_output(output)

        assert summary is not None
        assert "Suggested workspace_task_id=wt-1" in summary
        assert "Available tasks: wt-1:Task A:pending" in summary

    def test_build_parallel_workspace_delegation_retry_hint(self):
        hint = SessionProcessor._build_workspace_delegation_retry_hint(
            tool_name="parallel_delegate_subagents",
            tool_input={
                "tasks": [
                    {"subagent_name": "worker-a", "task": "done", "workspace_task_id": "wt-0"},
                    {"subagent_name": "worker-b", "task": "next task"},
                ]
            },
            workspace_task_id="wt-9",
        )

        assert hint is not None
        assert "parallel_delegate_subagents" in hint
        assert "workspace_task_id='wt-9'" in hint

    def test_build_parallel_workspace_delegation_retry_arguments(self):
        args = SessionProcessor._build_workspace_delegation_retry_arguments(
            tool_name="parallel_delegate_subagents",
            tool_input={
                "tasks": [
                    {"subagent_name": "worker-a", "task": "done", "workspace_task_id": "wt-0"},
                    {"subagent_name": "worker-b", "task": "next task"},
                ]
            },
            workspace_task_id="wt-9",
        )

        assert args == {
            "tasks": [
                {"subagent_name": "worker-a", "task": "done", "workspace_task_id": "wt-0"},
                {"subagent_name": "worker-b", "task": "next task", "workspace_task_id": "wt-9"},
            ]
        }

    @pytest.mark.asyncio
    async def test_parallel_delegate_guardrail_error_auto_retries_single_missing_candidate(self):
        from src.domain.events.agent_events import AgentActEvent
        from src.infrastructure.agent.core.message import ToolPart, ToolState

        config = ProcessorConfig(model="test-model")
        processor = SessionProcessor(config=config, tools=[])

        call_count = 0

        async def parallel_execute(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ToolResult(
                    output=(
                        "Error: workspace-authority delegation requires workspace_task_id. "
                        "Call todoread first, select the target child task's workspace_task_id, "
                        "then retry delegate_to_subagent."
                    ),
                    is_error=True,
                )
            tasks = kwargs["tasks"]
            assert tasks[1]["workspace_task_id"] == "wt-1"
            return ToolResult(output="parallel delegated successfully", is_error=False)

        async def todoread_execute(**kwargs):
            return ToolResult(
                output='{"todos":[{"id":"t1","workspace_task_id":"wt-1","content":"Task A","status":"pending"}]}',
                is_error=False,
            )

        processor.tools["parallel_delegate_subagents"] = ToolDefinition(
            name="parallel_delegate_subagents",
            description="Parallel delegate to subagents",
            parameters={},
            execute=parallel_execute,
        )
        processor.tools["todoread"] = ToolDefinition(
            name="todoread",
            description="Read todos",
            parameters={},
            execute=todoread_execute,
        )

        processor._pending_tool_calls["call-parallel-auto-retry"] = ToolPart(
            call_id="call-parallel-auto-retry",
            tool="parallel_delegate_subagents",
            input={},
            status=ToolState.RUNNING,
        )

        events = []
        async for event in processor._execute_tool(
            session_id="test-session",
            call_id="call-parallel-auto-retry",
            tool_name="parallel_delegate_subagents",
            arguments={
                "tasks": [
                    {"subagent_name": "worker-a", "task": "done", "workspace_task_id": "wt-0"},
                    {"subagent_name": "worker-b", "task": "do work"},
                ]
            },
        ):
            events.append(event)

        retry_act = next(
            event
            for event in events
            if isinstance(event, AgentActEvent)
            and event.call_id == "call-parallel-auto-retry-workspace-retry"
        )
        assert retry_act.tool_name == "parallel_delegate_subagents"
        assert retry_act.tool_input["tasks"][1]["workspace_task_id"] == "wt-1"
        assert call_count == 2
