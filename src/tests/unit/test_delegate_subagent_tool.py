"""Tests for SubAgent-as-Tool delegation feature.

Tests the delegate_subagent_tool, parallel_delegate_subagent_tool, and integration.
"""

from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.delegate_subagent import (
    configure_delegate_subagent,
    delegate_subagent_tool,
    parallel_delegate_subagent_tool,
)


@pytest.fixture
def tool_ctx():
    return ToolContext(
        session_id="sess-1",
        message_id="msg-1",
        call_id="call-1",
        agent_name="test-agent",
        conversation_id="conv-1",
    )


@pytest.fixture(autouse=True)
def _reset_delegate_state():
    from src.infrastructure.agent.tools import delegate_subagent as mod

    mod._delegate_execute_callback = None
    mod._delegate_run_registry = None
    mod._delegate_conversation_id = None
    mod._delegate_subagent_names = []
    mod._delegate_subagent_descriptions = {}
    mod._delegate_delegation_depth = 0
    mod._delegate_max_active_runs = None
    mod._delegate_max_concurrency = 5
    yield
    mod._delegate_execute_callback = None
    mod._delegate_run_registry = None
    mod._delegate_conversation_id = None
    mod._delegate_subagent_names = []
    mod._delegate_subagent_descriptions = {}
    mod._delegate_delegation_depth = 0
    mod._delegate_max_active_runs = None
    mod._delegate_max_concurrency = 5


@pytest.mark.unit
class TestDelegateSubAgentTool:
    """Tests for delegate_subagent_tool."""

    def _make_callback(self, return_value="SubAgent result"):
        callback = AsyncMock(return_value=return_value)
        return callback

    def _configure(self, callback=None):
        if callback is None:
            callback = self._make_callback()
        configure_delegate_subagent(
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
        )
        return callback

    def test_init(self):
        self._configure()
        assert delegate_subagent_tool.name == "delegate_to_subagent"
        assert "SubAgent" in delegate_subagent_tool.description
        assert "task" in delegate_subagent_tool.description.lower()

    def test_parameters_schema(self):
        self._configure()
        schema = delegate_subagent_tool.parameters
        assert schema["type"] == "object"
        assert "subagent_name" in schema["properties"]
        assert "task" in schema["properties"]
        assert schema["required"] == ["subagent_name", "task"]

    async def test_execute_success(self, tool_ctx):
        callback = self._make_callback("Research findings: ...")
        self._configure(callback)
        result = await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="researcher", task="Find info about X"
        )
        assert result.output == "Research findings: ..."
        callback.assert_awaited_once()
        assert callback.await_args.args == ("researcher", "Find info about X")
        assert "on_event" in callback.await_args.kwargs

    async def test_execute_forwards_workspace_task_id_when_present(self, tool_ctx):
        callback = self._make_callback("Research findings: ...")
        self._configure(callback)
        await delegate_subagent_tool.execute(
            tool_ctx,
            subagent_name="researcher",
            task="Find info about X",
            workspace_task_id="task-123",
        )
        assert callback.await_args.kwargs["workspace_task_id"] == "task-123"

    async def test_execute_workspace_authority_requires_workspace_task_id(self, tool_ctx):
        callback = self._make_callback("Research findings: ...")
        self._configure(callback)
        tool_ctx.runtime_context = {
            "task_authority": "workspace",
            "workspace_id": "ws-1",
            "root_goal_task_id": "root-1",
        }
        result = await delegate_subagent_tool.execute(
            tool_ctx,
            subagent_name="researcher",
            task="Find info about X",
        )
        assert result.is_error is True
        assert "workspace_task_id" in result.output
        assert "todoread" in result.output
        callback.assert_not_awaited()

    async def test_execute_callback_without_on_event_called_once(self, tool_ctx):
        called = 0

        async def _callback(name, task):
            nonlocal called
            called += 1
            return f"{name}:{task}"

        self._configure(_callback)
        result = await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="researcher", task="Find info about X"
        )
        assert result.output == "researcher:Find info about X"
        assert called == 1

    async def test_consume_pending_events(self, tool_ctx):
        async def _callback(name, task, on_event=None):
            if on_event:
                on_event({"type": "subagent_started", "data": {"name": name}})
                on_event({"type": "subagent_completed", "data": {"task": task}})
            return "done"

        self._configure(_callback)
        await delegate_subagent_tool.execute(tool_ctx, subagent_name="researcher", task="Find info")

        events = tool_ctx.consume_pending_events()
        # Events include: subagent_started, subagent_completed from callback,
        # plus subagent_started/completed from registry (which include run_id).
        # Filter to the callback-emitted events (no run_id in data).
        callback_events = [
            e
            for e in events
            if isinstance(e, dict) and e.get("type") in ("subagent_started", "subagent_completed")
            and "run_id" not in e.get("data", {})
        ]
        assert len(callback_events) == 2
        assert callback_events[0]["type"] == "subagent_started"
        assert callback_events[1]["type"] == "subagent_completed"
        assert tool_ctx.consume_pending_events() == []

    async def test_execute_missing_name(self, tool_ctx):
        self._configure()
        result = await delegate_subagent_tool.execute(tool_ctx, subagent_name="", task="test")
        assert result.is_error is True
        assert "required" in result.output

    async def test_execute_unknown_subagent(self, tool_ctx):
        self._configure()
        result = await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="unknown", task="test"
        )
        assert result.is_error is True
        assert "not found" in result.output
        assert "researcher" in result.output

    async def test_execute_missing_task(self, tool_ctx):
        self._configure()
        result = await delegate_subagent_tool.execute(tool_ctx, subagent_name="researcher", task="")
        assert result.is_error is True
        assert "required" in result.output

    async def test_execute_callback_error(self, tool_ctx):
        callback = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        self._configure(callback)
        result = await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="researcher", task="test"
        )
        assert result.is_error is True
        assert "LLM timeout" in result.output

    async def test_execute_emits_run_lifecycle_events(self, tool_ctx):
        callback = self._make_callback("done")
        configure_delegate_subagent(
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            conversation_id="conv-1",
        )

        await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="researcher", task="Find info about X"
        )
        events = tool_ctx.consume_pending_events()

        event_types = [
            event["type"] for event in events if isinstance(event, dict) and "type" in event
        ]
        assert event_types == [
            "subagent_started",
            "subagent_completed",
        ]
        assert events[0]["data"]["conversation_id"] == "conv-1"
        assert events[1]["data"]["status"] == "completed"

    async def test_execute_emits_run_failed_event(self, tool_ctx):
        callback = AsyncMock(side_effect=RuntimeError("boom"))
        configure_delegate_subagent(
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            conversation_id="conv-1",
        )

        await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="researcher", task="Find info about X"
        )
        events = tool_ctx.consume_pending_events()

        event_types = [
            event["type"] for event in events if isinstance(event, dict) and "type" in event
        ]
        assert event_types == [
            "subagent_started",
            "subagent_failed",
        ]
        assert events[1]["data"]["status"] == "failed"
        assert events[1]["data"]["error"] == "boom"

    async def test_execute_respects_max_active_runs_limit(self, tool_ctx):
        registry = SubAgentRunRegistry()
        existing = registry.create_run(
            conversation_id="conv-1",
            subagent_name="coder",
            task="Already running",
        )
        registry.mark_running("conv-1", existing.run_id)

        configure_delegate_subagent(
            execute_callback=self._make_callback("done"),
            run_registry=registry,
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            conversation_id="conv-1",
            max_active_runs=1,
        )

        result = await delegate_subagent_tool.execute(
            tool_ctx, subagent_name="researcher", task="Find info about X"
        )
        assert "active SubAgent run limit reached" in result.output


@pytest.mark.unit
class TestSubAgentAsToolIntegration:
    """Tests for SubAgent-as-Tool integration in ReActAgent."""

    def _make_subagent(self, name="test-agent", description="Test agent"):
        return SubAgent(
            id=f"sa-{name}",
            tenant_id="tenant-1",
            name=name,
            display_name=name.title(),
            system_prompt="You are a test agent.",
            trigger=AgentTrigger(description=description, keywords=["test"]),
        )

    def test_enable_subagent_as_tool_default(self):
        """Test that enable_subagent_as_tool defaults to True."""
        from src.infrastructure.agent.core.react_agent import ReActAgent

        agent = ReActAgent(
            model="test-model",
            tools={},
            subagents=[self._make_subagent()],
        )
        assert agent._enable_subagent_as_tool is True

    def test_disable_subagent_as_tool(self):
        """Test that enable_subagent_as_tool can be set to False."""
        from src.infrastructure.agent.core.react_agent import ReActAgent

        agent = ReActAgent(
            model="test-model",
            tools={},
            subagents=[self._make_subagent()],
            enable_subagent_as_tool=False,
        )
        assert agent._enable_subagent_as_tool is False

    async def test_system_prompt_includes_subagents(self):
        """Test that system prompt includes SubAgent descriptions."""
        from src.infrastructure.agent.prompts.manager import (
            PromptContext,
            PromptMode,
            SystemPromptManager,
        )

        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("test-model"),
            mode=PromptMode.BUILD,
            tool_definitions=[],
            subagents=[
                {
                    "name": "researcher",
                    "display_name": "Researcher",
                    "description": "Research specialist",
                    "trigger_description": "Handles research and analysis tasks",
                },
                {
                    "name": "coder",
                    "display_name": "Coder",
                    "description": "Code specialist",
                    "trigger_description": "Writes and debugs code",
                },
            ],
        )
        prompt = await manager.build_system_prompt(context)
        assert "SubAgent" in prompt or "delegate_to_subagent" in prompt
        assert "researcher" in prompt
        assert "coder" in prompt

    async def test_system_prompt_no_subagents_when_empty(self):
        """Test that system prompt doesn't include SubAgent section when empty."""
        from src.infrastructure.agent.prompts.manager import (
            PromptContext,
            PromptMode,
            SystemPromptManager,
        )

        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("test-model"),
            mode=PromptMode.BUILD,
            tool_definitions=[],
            subagents=None,
        )
        prompt = await manager.build_system_prompt(context)
        assert "Available SubAgents" not in prompt

    def test_build_subagent_section(self):
        """Test _build_subagent_section produces correct output."""
        from src.infrastructure.agent.prompts.manager import (
            PromptContext,
            SystemPromptManager,
        )

        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("test-model"),
            subagents=[
                {
                    "name": "researcher",
                    "display_name": "Researcher",
                    "trigger_description": "Research and analysis",
                },
            ],
        )
        section = manager._build_subagent_section(context)
        assert "researcher" in section
        assert "Research and analysis" in section
        assert "delegate_to_subagent" in section

    def test_build_subagent_section_empty(self):
        """Test _build_subagent_section returns empty for no subagents."""
        from src.infrastructure.agent.prompts.manager import (
            PromptContext,
            SystemPromptManager,
        )

        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("test-model"),
            subagents=None,
        )
        assert manager._build_subagent_section(context) == ""

    def test_build_subagent_section_parallel_guidance(self):
        """Test parallel guidance appears when 2+ subagents."""
        from src.infrastructure.agent.prompts.manager import (
            PromptContext,
            SystemPromptManager,
        )

        manager = SystemPromptManager()
        context = PromptContext(
            model_provider=SystemPromptManager.detect_model_provider("test-model"),
            subagents=[
                {"name": "a", "display_name": "A", "trigger_description": "do A"},
                {"name": "b", "display_name": "B", "trigger_description": "do B"},
            ],
        )
        section = manager._build_subagent_section(context)
        assert "parallel_delegate_subagents" in section


@pytest.mark.unit
class TestParallelDelegateSubAgentTool:
    """Tests for parallel_delegate_subagent_tool."""

    def _make_callback(self, side_effect=None):
        if side_effect:
            return AsyncMock(side_effect=side_effect)

        async def _cb(name, task):
            return f"Result from {name}: {task[:30]}"

        return AsyncMock(side_effect=_cb)

    def _configure(self, callback=None):
        if callback is None:
            callback = self._make_callback()
        configure_delegate_subagent(
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research tasks",
                "coder": "Coding tasks",
                "writer": "Writing tasks",
            },
        )
        return callback

    def test_init(self):
        self._configure()
        assert parallel_delegate_subagent_tool.name == "parallel_delegate_subagents"
        assert "parallel" in parallel_delegate_subagent_tool.description.lower()

    def test_parameters_schema(self):
        self._configure()
        schema = parallel_delegate_subagent_tool.parameters
        assert schema["required"] == ["tasks"]
        tasks_prop = schema["properties"]["tasks"]
        assert tasks_prop["type"] == "array"
        assert tasks_prop["minItems"] == 2
        items = tasks_prop["items"]
        assert "subagent_name" in items["properties"]

    async def test_execute_parallel_success(self, tool_ctx):
        callback = self._make_callback()
        self._configure(callback)
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Find info"},
                {"subagent_name": "coder", "task": "Write code"},
            ],
        )
        assert "researcher" in result.output
        assert "coder" in result.output
        assert "success" in result.output.lower()
        assert callback.call_count == 2

    async def test_execute_parallel_workspace_authority_requires_workspace_task_id(self, tool_ctx):
        callback = self._make_callback()
        self._configure(callback)
        tool_ctx.runtime_context = {
            "task_authority": "workspace",
            "workspace_id": "ws-1",
            "root_goal_task_id": "root-1",
        }
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Find info"},
                {"subagent_name": "coder", "task": "Write code", "workspace_task_id": "task-2"},
            ],
        )
        assert result.is_error is True
        assert "workspace_task_id" in result.output
        assert "todoread" in result.output
        assert callback.await_count == 0

    async def test_execute_parallel_three_tasks(self, tool_ctx):
        callback = self._make_callback()
        self._configure(callback)
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
                {"subagent_name": "writer", "task": "Write"},
            ],
        )
        assert callback.call_count == 3
        assert "3/3 succeeded" in result.output

    async def test_execute_empty_tasks(self, tool_ctx):
        self._configure()
        result = await parallel_delegate_subagent_tool.execute(tool_ctx, tasks=[])
        assert result.is_error is True

    async def test_execute_single_task_rejected(self, tool_ctx):
        self._configure()
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Solo task"},
            ],
        )
        assert result.is_error is True
        assert "at least 2" in result.output

    async def test_execute_invalid_subagent(self, tool_ctx):
        self._configure()
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "ok"},
                {"subagent_name": "nonexistent", "task": "bad"},
            ],
        )
        assert result.is_error is True
        assert "nonexistent" in result.output

    async def test_execute_missing_task_field(self, tool_ctx):
        self._configure()
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "ok"},
                {"subagent_name": "coder"},
            ],
        )
        assert result.is_error is True
        assert "missing" in result.output.lower()

    async def test_execute_json_string_input(self, tool_ctx):
        """Test that JSON string input is parsed correctly."""
        import json

        callback = self._make_callback()
        self._configure(callback)
        tasks_json = json.dumps(
            [
                {"subagent_name": "researcher", "task": "Find info"},
                {"subagent_name": "coder", "task": "Write code"},
            ]
        )
        result = await parallel_delegate_subagent_tool.execute(tool_ctx, tasks=tasks_json)
        assert callback.call_count == 2
        assert "2/2 succeeded" in result.output

    async def test_execute_partial_failure(self, tool_ctx):
        """One SubAgent fails, others succeed."""
        call_count = 0

        async def _mixed(name, task):
            nonlocal call_count
            call_count += 1
            if name == "coder":
                raise RuntimeError("LLM timeout")
            return f"Result from {name}"

        callback = AsyncMock(side_effect=_mixed)
        self._configure(callback)
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
            ],
        )
        assert "1/2 succeeded" in result.output
        assert "researcher" in result.output
        assert "failed" in result.output.lower()

    async def test_execute_none_input(self, tool_ctx):
        self._configure()
        result = await parallel_delegate_subagent_tool.execute(tool_ctx, tasks=None)
        assert result.is_error is True

    async def test_execute_concurrency_limit(self, tool_ctx):
        """Verify semaphore limits concurrent executions."""
        import asyncio

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def _tracking(name, task):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return f"Done {name}"

        configure_delegate_subagent(
            execute_callback=_tracking,
            run_registry=SubAgentRunRegistry(),
            subagent_names=["a", "b", "c", "d"],
            subagent_descriptions={"a": "A", "b": "B", "c": "C", "d": "D"},
            max_concurrency=2,
        )
        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "a", "task": "t1"},
                {"subagent_name": "b", "task": "t2"},
                {"subagent_name": "c", "task": "t3"},
                {"subagent_name": "d", "task": "t4"},
            ],
        )
        assert "4/4 succeeded" in result.output
        assert max_concurrent <= 2

    async def test_parallel_execute_emits_run_lifecycle_events(self, tool_ctx):
        callback = self._make_callback()
        configure_delegate_subagent(
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research tasks",
                "coder": "Coding tasks",
                "writer": "Writing tasks",
            },
            conversation_id="conv-2",
        )

        await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
            ],
        )

        events = tool_ctx.consume_pending_events()
        event_types = [
            event["type"] for event in events if isinstance(event, dict) and "type" in event
        ]
        assert event_types.count("subagent_started") == 2
        assert event_types.count("subagent_completed") == 2

    async def test_parallel_execute_respects_max_active_runs_limit(self, tool_ctx):
        registry = SubAgentRunRegistry()
        existing = registry.create_run(
            conversation_id="conv-1",
            subagent_name="writer",
            task="Already running",
        )
        registry.mark_running("conv-1", existing.run_id)

        configure_delegate_subagent(
            execute_callback=self._make_callback(),
            run_registry=registry,
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research tasks",
                "coder": "Coding tasks",
                "writer": "Writing tasks",
            },
            conversation_id="conv-1",
            max_active_runs=2,
        )

        result = await parallel_delegate_subagent_tool.execute(
            tool_ctx,
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
            ],
        )
        assert "active SubAgent run limit reached" in result.output
