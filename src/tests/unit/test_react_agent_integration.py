"""Tests for Phase 6: ReActAgent integration with SubAgent modules.

Tests that ReActAgent correctly wires MemoryAccessor, BackgroundExecutor,
and TemplateRegistry when graph_service is available.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent


def _make_subagent(name: str = "test-agent") -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-1",
        name=name,
        display_name=name,
        system_prompt=f"You are {name}.",
        trigger_description=f"Trigger for {name}",
        trigger_keywords=[name],
    )


def _make_react_agent(**kwargs):
    """Create a ReActAgent with minimal config for testing."""
    from src.infrastructure.agent.core.react_agent import ReActAgent

    defaults = {
        "model": "test-model",
        "tools": {"test_tool": MagicMock()},
    }
    defaults.update(kwargs)
    return ReActAgent(**defaults)


@pytest.mark.unit
class TestReActAgentGraphServiceInit:
    """Test ReActAgent initialization with graph_service."""

    def test_init_without_graph_service(self):
        agent = _make_react_agent()
        assert agent._graph_service is None

    def test_init_with_graph_service(self):
        graph = MagicMock()
        agent = _make_react_agent(graph_service=graph)
        assert agent._graph_service is graph

    def test_background_executor_initialized(self):
        agent = _make_react_agent()
        assert agent._background_executor is not None

    def test_template_registry_initialized(self):
        agent = _make_react_agent()
        assert agent._template_registry is not None


@pytest.mark.unit
class TestReActAgentMemoryIntegration:
    """Test that _execute_subagent integrates MemoryAccessor."""

    async def test_execute_subagent_with_graph_service(self):
        """When graph_service is available, memory should be searched."""
        graph = AsyncMock()
        graph.search.return_value = [
            {"content": "User prefers concise output", "type": "entity", "score": 0.9},
        ]

        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            graph_service=graph,
            subagents=[sa],
        )

        # Mock SubAgentProcess to avoid real execution
        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Research result"
            mock_result.to_event_data.return_value = {"summary": "done"}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in agent._execute_subagent(
                subagent=sa,
                user_message="Research AI trends",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                events.append(event)

        # Verify graph.search was called
        graph.search.assert_called_once_with(
            query="Research AI trends",
            project_id="proj-1",
            limit=5,
        )

        # Verify SubAgentProcess received memory_context in its context
        call_kwargs = MockProcess.call_args[1]
        context = call_kwargs.get("context")
        assert context is not None
        assert (
            "memory" in context.memory_context.lower()
            or "knowledge" in context.memory_context.lower()
        )

    async def test_execute_subagent_without_graph_service(self):
        """When no graph_service, memory_context should be empty."""
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa])

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=sa,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                pass

        # Verify SubAgentProcess context has empty memory_context
        call_kwargs = MockProcess.call_args[1]
        context = call_kwargs.get("context")
        assert context.memory_context == ""

    async def test_execute_subagent_memory_search_error_graceful(self):
        """Memory search failure should not block SubAgent execution."""
        graph = AsyncMock()
        graph.search.side_effect = RuntimeError("Graph unavailable")

        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            graph_service=graph,
            subagents=[sa],
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Still works"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in agent._execute_subagent(
                subagent=sa,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                events.append(event)

        # Should complete without error despite graph failure
        event_types = [e["type"] for e in events]
        assert "subagent_started" in event_types
        assert "complete" in event_types

    async def test_execute_subagent_no_project_id_skips_memory(self):
        """When project_id is empty, memory search should be skipped."""
        graph = AsyncMock()

        sa = _make_subagent("researcher")
        agent = _make_react_agent(
            graph_service=graph,
            subagents=[sa],
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=sa,
                user_message="Do work",
                conversation_context=[],
                project_id="",
                tenant_id="tenant-1",
            ):
                pass

        # graph.search should NOT have been called
        graph.search.assert_not_called()

    async def test_execute_subagent_injects_nested_delegate_tool(self):
        """Nested SubAgent execution should include delegate_to_subagent tool."""
        researcher = _make_subagent("researcher")
        coder = _make_subagent("coder")
        agent = _make_react_agent(
            subagents=[researcher, coder],
            enable_subagent_as_tool=True,
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=researcher,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
            ):
                pass

        tool_names = [tool.name for tool in MockProcess.call_args.kwargs["tools"]]
        assert "delegate_to_subagent" in tool_names

    async def test_execute_subagent_skips_nested_delegate_tool_at_max_depth(self):
        """Nested delegation tools should not be injected at max recursion depth."""
        researcher = _make_subagent("researcher")
        coder = _make_subagent("coder")
        agent = _make_react_agent(
            subagents=[researcher, coder],
            enable_subagent_as_tool=True,
        )

        with patch("src.infrastructure.agent.subagent.process.SubAgentProcess") as MockProcess:
            mock_result = MagicMock()
            mock_result.final_content = "Output"
            mock_result.to_event_data.return_value = {}

            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            async for _ in agent._execute_subagent(
                subagent=researcher,
                user_message="Do work",
                conversation_context=[],
                project_id="proj-1",
                tenant_id="tenant-1",
                delegation_depth=2,
            ):
                pass

        tool_names = [tool.name for tool in MockProcess.call_args.kwargs["tools"]]
        assert "delegate_to_subagent" not in tool_names


@pytest.mark.unit
class TestReActAgentBackgroundExecutor:
    """Test BackgroundExecutor access from ReActAgent."""

    def test_background_executor_accessible(self):
        agent = _make_react_agent()
        from src.infrastructure.agent.subagent.background_executor import BackgroundExecutor

        assert isinstance(agent._background_executor, BackgroundExecutor)

    def test_template_registry_accessible(self):
        agent = _make_react_agent()
        from src.infrastructure.agent.subagent.template_registry import TemplateRegistry

        assert isinstance(agent._template_registry, TemplateRegistry)
