"""Tests for SubAgent-as-Tool delegation feature.

Tests the DelegateSubAgentTool, ParallelDelegateSubAgentTool, and integration.
"""

from unittest.mock import AsyncMock

import pytest

from src.domain.model.agent.subagent import AgentTrigger, SubAgent
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.delegate_subagent import (
    DelegateSubAgentTool,
    ParallelDelegateSubAgentTool,
)


@pytest.mark.unit
class TestDelegateSubAgentTool:
    """Tests for DelegateSubAgentTool."""

    def _make_callback(self, return_value="SubAgent result"):
        callback = AsyncMock(return_value=return_value)
        return callback

    def _make_tool(self, callback=None):
        if callback is None:
            callback = self._make_callback()
        return DelegateSubAgentTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            execute_callback=callback,
        )

    def test_init(self):
        tool = self._make_tool()
        assert tool.name == "delegate_to_subagent"
        assert "researcher" in tool.description
        assert "coder" in tool.description

    def test_parameters_schema(self):
        tool = self._make_tool()
        schema = tool.get_parameters_schema()
        assert schema["type"] == "object"
        assert "subagent_name" in schema["properties"]
        assert "task" in schema["properties"]
        assert schema["properties"]["subagent_name"]["enum"] == ["researcher", "coder"]
        assert schema["required"] == ["subagent_name", "task"]

    async def test_execute_success(self):
        callback = self._make_callback("Research findings: ...")
        tool = self._make_tool(callback)
        result = await tool.execute(subagent_name="researcher", task="Find info about X")
        assert result == "Research findings: ..."
        callback.assert_awaited_once()
        assert callback.await_args.args == ("researcher", "Find info about X")
        assert "on_event" in callback.await_args.kwargs

    async def test_execute_callback_without_on_event_called_once(self):
        called = 0

        async def _callback(name, task):
            nonlocal called
            called += 1
            return f"{name}:{task}"

        tool = self._make_tool(_callback)
        result = await tool.execute(subagent_name="researcher", task="Find info about X")
        assert result == "researcher:Find info about X"
        assert called == 1

    async def test_consume_pending_events(self):
        async def _callback(name, task, on_event=None):
            if on_event:
                on_event({"type": "subagent_started", "data": {"name": name}})
                on_event({"type": "subagent_completed", "data": {"task": task}})
            return "done"

        tool = self._make_tool(_callback)
        await tool.execute(subagent_name="researcher", task="Find info")

        events = tool.consume_pending_events()
        assert len(events) == 2
        assert events[0]["type"] == "subagent_started"
        assert events[1]["type"] == "subagent_completed"
        assert tool.consume_pending_events() == []

    async def test_execute_missing_name(self):
        tool = self._make_tool()
        result = await tool.execute(subagent_name="", task="test")
        assert "Error" in result
        assert "required" in result

    async def test_execute_unknown_subagent(self):
        tool = self._make_tool()
        result = await tool.execute(subagent_name="unknown", task="test")
        assert "Error" in result
        assert "not found" in result
        assert "researcher" in result

    async def test_execute_missing_task(self):
        tool = self._make_tool()
        result = await tool.execute(subagent_name="researcher", task="")
        assert "Error" in result
        assert "required" in result

    async def test_execute_callback_error(self):
        callback = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        tool = self._make_tool(callback)
        result = await tool.execute(subagent_name="researcher", task="test")
        assert "Error" in result
        assert "LLM timeout" in result

    async def test_execute_emits_run_lifecycle_events(self):
        callback = self._make_callback("done")
        tool = DelegateSubAgentTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            conversation_id="conv-1",
        )

        await tool.execute(subagent_name="researcher", task="Find info about X")
        events = tool.consume_pending_events()

        assert [event["type"] for event in events] == [
            "subagent_run_started",
            "subagent_run_completed",
        ]
        assert events[0]["data"]["conversation_id"] == "conv-1"
        assert events[1]["data"]["status"] == "completed"

    async def test_execute_emits_run_failed_event(self):
        callback = AsyncMock(side_effect=RuntimeError("boom"))
        tool = DelegateSubAgentTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            conversation_id="conv-1",
        )

        await tool.execute(subagent_name="researcher", task="Find info about X")
        events = tool.consume_pending_events()

        assert [event["type"] for event in events] == [
            "subagent_run_started",
            "subagent_run_failed",
        ]
        assert events[1]["data"]["status"] == "failed"
        assert events[1]["data"]["error"] == "boom"

    async def test_execute_respects_max_active_runs_limit(self):
        registry = SubAgentRunRegistry()
        existing = registry.create_run(
            conversation_id="conv-1",
            subagent_name="coder",
            task="Already running",
        )
        registry.mark_running("conv-1", existing.run_id)

        tool = DelegateSubAgentTool(
            subagent_names=["researcher", "coder"],
            subagent_descriptions={
                "researcher": "Handles research tasks",
                "coder": "Writes and debugs code",
            },
            execute_callback=self._make_callback("done"),
            run_registry=registry,
            conversation_id="conv-1",
            max_active_runs=1,
        )

        result = await tool.execute(subagent_name="researcher", task="Find info about X")
        assert "active SubAgent run limit reached" in result


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
    """Tests for ParallelDelegateSubAgentTool."""

    def _make_callback(self, side_effect=None):
        if side_effect:
            return AsyncMock(side_effect=side_effect)

        async def _cb(name, task):
            return f"Result from {name}: {task[:30]}"

        return AsyncMock(side_effect=_cb)

    def _make_tool(self, callback=None):
        if callback is None:
            callback = self._make_callback()
        return ParallelDelegateSubAgentTool(
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research tasks",
                "coder": "Coding tasks",
                "writer": "Writing tasks",
            },
            execute_callback=callback,
        )

    def test_init(self):
        tool = self._make_tool()
        assert tool.name == "parallel_delegate_subagents"
        assert "researcher" in tool.description
        assert "parallel" in tool.description.lower()

    def test_parameters_schema(self):
        tool = self._make_tool()
        schema = tool.get_parameters_schema()
        assert schema["required"] == ["tasks"]
        tasks_prop = schema["properties"]["tasks"]
        assert tasks_prop["type"] == "array"
        assert tasks_prop["minItems"] == 2
        items = tasks_prop["items"]
        assert "subagent_name" in items["properties"]
        assert items["properties"]["subagent_name"]["enum"] == ["researcher", "coder", "writer"]

    async def test_execute_parallel_success(self):
        callback = self._make_callback()
        tool = self._make_tool(callback)
        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "Find info"},
                {"subagent_name": "coder", "task": "Write code"},
            ]
        )
        assert "researcher" in result
        assert "coder" in result
        assert "success" in result.lower()
        assert callback.call_count == 2

    async def test_execute_parallel_three_tasks(self):
        callback = self._make_callback()
        tool = self._make_tool(callback)
        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
                {"subagent_name": "writer", "task": "Write"},
            ]
        )
        assert callback.call_count == 3
        assert "3/3 succeeded" in result

    async def test_execute_empty_tasks(self):
        tool = self._make_tool()
        result = await tool.execute(tasks=[])
        assert "Error" in result

    async def test_execute_single_task_rejected(self):
        tool = self._make_tool()
        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "Solo task"},
            ]
        )
        assert "Error" in result
        assert "at least 2" in result

    async def test_execute_invalid_subagent(self):
        tool = self._make_tool()
        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "ok"},
                {"subagent_name": "nonexistent", "task": "bad"},
            ]
        )
        assert "Error" in result
        assert "nonexistent" in result

    async def test_execute_missing_task_field(self):
        tool = self._make_tool()
        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "ok"},
                {"subagent_name": "coder"},
            ]
        )
        assert "Error" in result
        assert "missing" in result.lower()

    async def test_execute_json_string_input(self):
        """Test that JSON string input is parsed correctly."""
        import json

        callback = self._make_callback()
        tool = self._make_tool(callback)
        tasks_json = json.dumps(
            [
                {"subagent_name": "researcher", "task": "Find info"},
                {"subagent_name": "coder", "task": "Write code"},
            ]
        )
        result = await tool.execute(tasks=tasks_json)
        assert callback.call_count == 2
        assert "2/2 succeeded" in result

    async def test_execute_partial_failure(self):
        """One SubAgent fails, others succeed."""
        call_count = 0

        async def _mixed(name, task):
            nonlocal call_count
            call_count += 1
            if name == "coder":
                raise RuntimeError("LLM timeout")
            return f"Result from {name}"

        callback = AsyncMock(side_effect=_mixed)
        tool = self._make_tool(callback)
        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
            ]
        )
        assert "1/2 succeeded" in result
        assert "researcher" in result
        assert "failed" in result.lower()

    async def test_execute_none_input(self):
        tool = self._make_tool()
        result = await tool.execute(tasks=None)
        assert "Error" in result

    async def test_execute_concurrency_limit(self):
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

        tool = ParallelDelegateSubAgentTool(
            subagent_names=["a", "b", "c", "d"],
            subagent_descriptions={"a": "A", "b": "B", "c": "C", "d": "D"},
            execute_callback=_tracking,
            max_concurrency=2,
        )
        result = await tool.execute(
            tasks=[
                {"subagent_name": "a", "task": "t1"},
                {"subagent_name": "b", "task": "t2"},
                {"subagent_name": "c", "task": "t3"},
                {"subagent_name": "d", "task": "t4"},
            ]
        )
        assert "4/4 succeeded" in result
        assert max_concurrent <= 2

    async def test_parallel_execute_emits_run_lifecycle_events(self):
        callback = self._make_callback()
        tool = ParallelDelegateSubAgentTool(
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research tasks",
                "coder": "Coding tasks",
                "writer": "Writing tasks",
            },
            execute_callback=callback,
            run_registry=SubAgentRunRegistry(),
            conversation_id="conv-2",
        )

        await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
            ]
        )

        events = tool.consume_pending_events()
        event_types = [event["type"] for event in events]
        assert event_types.count("subagent_run_started") == 2
        assert event_types.count("subagent_run_completed") == 2

    async def test_parallel_execute_respects_max_active_runs_limit(self):
        registry = SubAgentRunRegistry()
        existing = registry.create_run(
            conversation_id="conv-1",
            subagent_name="writer",
            task="Already running",
        )
        registry.mark_running("conv-1", existing.run_id)

        tool = ParallelDelegateSubAgentTool(
            subagent_names=["researcher", "coder", "writer"],
            subagent_descriptions={
                "researcher": "Research tasks",
                "coder": "Coding tasks",
                "writer": "Writing tasks",
            },
            execute_callback=self._make_callback(),
            run_registry=registry,
            conversation_id="conv-1",
            max_active_runs=2,
        )

        result = await tool.execute(
            tasks=[
                {"subagent_name": "researcher", "task": "Research"},
                {"subagent_name": "coder", "task": "Code"},
            ]
        )
        assert "active SubAgent run limit reached" in result
