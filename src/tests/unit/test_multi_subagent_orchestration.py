"""Tests for Phase 7.1: Multi-SubAgent orchestration in stream().

Tests that ReActAgent correctly routes to parallel/chain/single SubAgent
execution based on TaskDecomposer results.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.task_decomposer import (
    DecompositionResult,
    SubTask,
)


def _make_subagent(name: str = "test-agent") -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-1",
        name=name,
        display_name=name.title(),
        system_prompt=f"You are {name}.",
        trigger_description=f"Trigger for {name}",
        trigger_keywords=[name],
    )


def _make_react_agent(**kwargs):
    from src.infrastructure.agent.core.react_agent import ReActAgent

    defaults = {
        "model": "test-model",
        "tools": {"test_tool": MagicMock()},
        "enable_subagent_as_tool": False,  # Test legacy pre-routing behavior
    }
    defaults.update(kwargs)
    return ReActAgent(**defaults)


def _make_result(name: str = "agent", success: bool = True) -> SubAgentResult:
    return SubAgentResult(
        subagent_id=f"id-{name}",
        subagent_name=name,
        summary=f"Result from {name}",
        success=success,
        final_content=f"Content from {name}",
        tokens_used=100,
        tool_calls_count=2,
        execution_time_ms=500,
    )


# === Initialization Tests ===


@pytest.mark.unit
class TestTaskDecomposerInit:
    """Test TaskDecomposer initialization in ReActAgent."""

    def test_no_decomposer_without_llm_client(self):
        agent = _make_react_agent(subagents=[_make_subagent()])
        assert agent._task_decomposer is None

    def test_no_decomposer_without_subagents(self):
        llm = MagicMock()
        agent = _make_react_agent(llm_client=llm)
        assert agent._task_decomposer is None

    def test_decomposer_created_with_llm_and_subagents(self):
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agent = _make_react_agent(llm_client=llm, subagents=[sa])
        assert agent._task_decomposer is not None

    def test_decomposer_has_agent_names(self):
        llm = MagicMock()
        agents = [_make_subagent("researcher"), _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)
        assert agent._task_decomposer._agent_names == ["researcher", "coder"]

    def test_result_aggregator_always_created(self):
        agent = _make_react_agent()
        assert agent._result_aggregator is not None


# === Topological Sort Tests ===


@pytest.mark.unit
class TestTopologicalSort:
    """Test _topological_sort_subtasks."""

    def test_no_dependencies(self):
        from src.infrastructure.agent.core.react_agent import ReActAgent

        tasks = [
            SubTask(id="t1", description="Task 1"),
            SubTask(id="t2", description="Task 2"),
        ]
        result = ReActAgent._topological_sort_subtasks(tasks)
        assert len(result) == 2
        ids = [r.id for r in result]
        assert "t1" in ids and "t2" in ids

    def test_linear_chain(self):
        from src.infrastructure.agent.core.react_agent import ReActAgent

        tasks = [
            SubTask(id="t1", description="Task 1"),
            SubTask(id="t2", description="Task 2", dependencies=("t1",)),
            SubTask(id="t3", description="Task 3", dependencies=("t2",)),
        ]
        result = ReActAgent._topological_sort_subtasks(tasks)
        ids = [r.id for r in result]
        assert ids == ["t1", "t2", "t3"]

    def test_diamond_deps(self):
        from src.infrastructure.agent.core.react_agent import ReActAgent

        tasks = [
            SubTask(id="t1", description="Root"),
            SubTask(id="t2", description="Left", dependencies=("t1",)),
            SubTask(id="t3", description="Right", dependencies=("t1",)),
            SubTask(id="t4", description="Merge", dependencies=("t2", "t3")),
        ]
        result = ReActAgent._topological_sort_subtasks(tasks)
        ids = [r.id for r in result]
        assert ids.index("t1") < ids.index("t2")
        assert ids.index("t1") < ids.index("t3")
        assert ids.index("t2") < ids.index("t4")
        assert ids.index("t3") < ids.index("t4")


# === Stream Orchestration Tests ===


@pytest.mark.unit
class TestStreamOrchestration:
    """Test stream() routes to correct orchestration path."""

    async def _collect_events(self, agent, **kwargs):
        events = []
        async for event in agent.stream(**kwargs):
            events.append(event)
        return events

    async def test_single_subagent_no_decomposer(self):
        """Without decomposer, single SubAgent path is used."""
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa])

        # Mock the match to return the subagent
        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent, "_execute_subagent") as mock_exec,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_exec.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        # Should have routed event + execute events
        types = [e["type"] for e in events]
        assert "subagent_routed" in types
        mock_exec.assert_called_once()

    async def test_decomposition_triggers_parallel(self):
        """When decomposer returns independent tasks, parallel path is used."""
        llm = MagicMock()
        agents = [_make_subagent("researcher"), _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        decomposition = DecompositionResult(
            subtasks=(
                SubTask(id="t1", description="Research", target_subagent="researcher"),
                SubTask(id="t2", description="Code", target_subagent="coder"),
            ),
            reasoning="Independent tasks",
            is_decomposed=True,
        )

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent._task_decomposer, "decompose", return_value=decomposition),
            patch.object(agent, "_execute_parallel") as mock_parallel,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=agents[0], confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "parallel_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_parallel.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research and code",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_parallel.assert_called_once()
        # Verify subtasks were passed
        call_kwargs = mock_parallel.call_args[1]
        assert len(call_kwargs["subtasks"]) == 2

    async def test_decomposition_triggers_chain(self):
        """When decomposer returns tasks with linear deps, chain path is used."""
        llm = MagicMock()
        agents = [_make_subagent("researcher"), _make_subagent("writer")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        decomposition = DecompositionResult(
            subtasks=(
                SubTask(id="t1", description="Research first", target_subagent="researcher"),
                SubTask(
                    id="t2",
                    description="Write report",
                    target_subagent="writer",
                    dependencies=("t1",),
                ),
            ),
            reasoning="Sequential pipeline",
            is_decomposed=True,
        )

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent._task_decomposer, "decompose", return_value=decomposition),
            patch.object(agent, "_execute_chain") as mock_chain,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=agents[0], confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "chain_started", "data": {}, "timestamp": "t"}
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_chain.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research then write",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_chain.assert_called_once()

    async def test_decomposition_single_task_falls_to_single(self):
        """When decomposer returns 1 task, single SubAgent path is used."""
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agents = [sa, _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        decomposition = DecompositionResult(
            subtasks=(SubTask(id="t1", description="Simple research"),),
            reasoning="Simple task",
            is_decomposed=False,
        )

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent._task_decomposer, "decompose", return_value=decomposition),
            patch.object(agent, "_execute_subagent") as mock_single,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_single.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_single.assert_called_once()

    async def test_decomposition_failure_falls_to_single(self):
        """When decomposer fails, single SubAgent path is used."""
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agents = [sa, _make_subagent("coder")]
        agent = _make_react_agent(llm_client=llm, subagents=agents)

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(
                agent._task_decomposer,
                "decompose",
                side_effect=RuntimeError("LLM down"),
            ),
            patch.object(agent, "_execute_subagent") as mock_single,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_single.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        mock_single.assert_called_once()

    async def test_only_one_subagent_skips_decomposition(self):
        """With only 1 SubAgent, decomposition is skipped."""
        llm = MagicMock()
        sa = _make_subagent("researcher")
        agent = _make_react_agent(llm_client=llm, subagents=[sa])

        with (
            patch.object(agent, "_match_subagent_async") as mock_match,
            patch.object(agent, "_execute_subagent") as mock_single,
        ):
            from src.infrastructure.agent.core.subagent_router import SubAgentMatch

            mock_match.return_value = SubAgentMatch(
                subagent=sa, confidence=0.9, match_reason="keyword"
            )

            async def mock_events(*a, **kw):
                yield {"type": "complete", "data": {"content": "done"}, "timestamp": "t"}

            mock_single.return_value = mock_events()

            events = await self._collect_events(
                agent,
                conversation_id="c1",
                user_message="research AI",
                project_id="p1",
                user_id="u1",
                tenant_id="t1",
            )

        # Should go directly to single SubAgent, no decomposition
        mock_single.assert_called_once()
        # _task_decomposer should NOT have been set since only 1 subagent
        # (but it was created since llm_client and subagents were both present)
        # The guard in stream() checks len(self.subagents) > 1


# === _execute_parallel Tests ===


@pytest.mark.unit
class TestExecuteParallel:
    """Test _execute_parallel method."""

    async def test_parallel_emits_lifecycle_events(self):
        """Parallel execution emits started and completed events."""
        agents = [_make_subagent("researcher"), _make_subagent("coder")]
        agent = _make_react_agent(subagents=agents)

        subtasks = [
            SubTask(id="t1", description="Research", target_subagent="researcher"),
            SubTask(id="t2", description="Code", target_subagent="coder"),
        ]

        with patch(
            "src.infrastructure.agent.subagent.parallel_scheduler.ParallelScheduler"
        ) as MockScheduler:

            async def mock_execute(*a, **kw):
                yield {
                    "type": "subtask_started",
                    "data": {"task_id": "t1"},
                    "timestamp": "t",
                }
                yield {
                    "type": "subtask_completed",
                    "data": {"task_id": "t1", "result": _make_result("researcher")},
                    "timestamp": "t",
                }

            MockScheduler.return_value.execute = mock_execute

            events = []
            async for event in agent._execute_parallel(
                subtasks=subtasks,
                user_message="Do both",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert types[0] == "parallel_started"
        assert "parallel_completed" in types
        assert "complete" in types
        # Check parallel_started has task_count
        assert events[0]["data"]["task_count"] == 2


# === _execute_chain Tests ===


@pytest.mark.unit
class TestExecuteChain:
    """Test _execute_chain method."""

    async def test_chain_emits_lifecycle_events(self):
        """Chain execution delegates to SubAgentChain."""
        agents = [_make_subagent("researcher"), _make_subagent("writer")]
        agent = _make_react_agent(subagents=agents)

        subtasks = [
            SubTask(id="t1", description="Research", target_subagent="researcher"),
            SubTask(
                id="t2",
                description="Write",
                target_subagent="writer",
                dependencies=("t1",),
            ),
        ]

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentChain"
        ) as MockChain:
            mock_chain_instance = MockChain.return_value

            from src.infrastructure.agent.subagent.chain import ChainResult

            mock_chain_instance.result = ChainResult(
                steps_completed=2,
                total_steps=2,
                final_summary="Chain done",
                execution_time_ms=1000,
            )

            async def mock_execute(*a, **kw):
                yield {"type": "chain_started", "data": {}, "timestamp": "t"}
                yield {"type": "chain_step_completed", "data": {}, "timestamp": "t"}

            mock_chain_instance.execute = mock_execute

            events = []
            async for event in agent._execute_chain(
                subtasks=subtasks,
                user_message="Research then write",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "chain_started" in types
        assert "complete" in types
        # Final complete should have chain content
        complete_event = [e for e in events if e["type"] == "complete"][0]
        assert complete_event["data"]["orchestration_mode"] == "chain"


# === _execute_background Tests ===


@pytest.mark.unit
class TestExecuteBackground:
    """Test _execute_background method."""

    async def test_background_emits_launch_event(self):
        """Background launch emits confirmation event."""
        sa = _make_subagent("researcher")
        agent = _make_react_agent(subagents=[sa])

        with patch.object(
            agent._background_executor, "launch", return_value="bg-abc123"
        ):
            events = []
            async for event in agent._execute_background(
                subagent=sa,
                user_message="Long research task",
                conversation_id="c1",
                conversation_context=[],
                project_id="p1",
                tenant_id="t1",
            ):
                events.append(event)

        types = [e["type"] for e in events]
        assert "background_launched" in types
        assert "complete" in types

        launch_event = [e for e in events if e["type"] == "background_launched"][0]
        assert launch_event["data"]["execution_id"] == "bg-abc123"
        assert launch_event["data"]["subagent_name"] == "Researcher"

        complete_event = [e for e in events if e["type"] == "complete"][0]
        assert complete_event["data"]["orchestration_mode"] == "background"
