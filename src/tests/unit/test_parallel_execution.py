"""
Unit tests for Phase 3: Parallel Execution & Task Decomposition.

Tests for:
- TaskDecomposer (LLM-driven task splitting)
- ResultAggregator (multi-result aggregation)
- ParallelScheduler (concurrent SubAgent execution)
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent, AgentModel
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.parallel_scheduler import (
    ParallelScheduler,
    ParallelSchedulerConfig,
    SubTaskExecution,
)
from src.infrastructure.agent.subagent.result_aggregator import (
    AggregatedResult,
    ResultAggregator,
)
from src.infrastructure.agent.subagent.task_decomposer import (
    DecompositionResult,
    SubTask,
    TaskDecomposer,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client():
    return AsyncMock()


@pytest.fixture
def sample_subagents() -> list[SubAgent]:
    return [
        SubAgent.create(
            tenant_id="t1",
            name="coder",
            display_name="Coder Agent",
            system_prompt="You are a coding assistant.",
            trigger_description="Coding tasks",
            trigger_keywords=["code", "implement"],
        ),
        SubAgent.create(
            tenant_id="t1",
            name="researcher",
            display_name="Research Agent",
            system_prompt="You are a research assistant.",
            trigger_description="Research tasks",
            trigger_keywords=["search", "find"],
        ),
    ]


@pytest.fixture
def sample_results() -> list[SubAgentResult]:
    return [
        SubAgentResult(
            subagent_id="sa-1",
            subagent_name="coder",
            summary="Implemented the function successfully.",
            final_content="Implemented the function successfully.",
            success=True,
            tokens_used=500,
            tool_calls_count=3,
        ),
        SubAgentResult(
            subagent_id="sa-2",
            subagent_name="researcher",
            summary="Found 5 relevant papers on the topic.",
            final_content="Found 5 relevant papers on the topic.",
            success=True,
            tokens_used=300,
            tool_calls_count=1,
        ),
    ]


# ============================================================================
# Test SubTask
# ============================================================================


@pytest.mark.unit
class TestSubTask:
    def test_subtask_frozen(self):
        t = SubTask(id="t1", description="Do something")
        with pytest.raises(AttributeError):
            t.id = "t2"

    def test_subtask_defaults(self):
        t = SubTask(id="t1", description="Task")
        assert t.target_subagent is None
        assert t.dependencies == ()
        assert t.priority == 0

    def test_subtask_with_dependencies(self):
        t = SubTask(id="t2", description="Depends on t1", dependencies=("t1",))
        assert "t1" in t.dependencies


# ============================================================================
# Test TaskDecomposer
# ============================================================================


@pytest.mark.unit
class TestTaskDecomposer:
    async def test_decompose_success(self, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "decompose_task",
                        "arguments": json.dumps({
                            "subtasks": [
                                {
                                    "id": "t1",
                                    "description": "Research the API",
                                    "target_agent": "researcher",
                                },
                                {
                                    "id": "t2",
                                    "description": "Implement the code",
                                    "target_agent": "coder",
                                    "depends_on": ["t1"],
                                },
                            ],
                            "reasoning": "Research first, then implement",
                        }),
                    }
                }
            ],
        }

        decomposer = TaskDecomposer(
            llm_client=mock_llm_client,
            available_agent_names=["coder", "researcher"],
        )
        result = await decomposer.decompose("Research the API and implement a client")

        assert result.is_decomposed is True
        assert len(result.subtasks) == 2
        assert result.subtasks[0].target_subagent == "researcher"
        assert result.subtasks[1].target_subagent == "coder"
        assert "t1" in result.subtasks[1].dependencies

    async def test_decompose_single_task(self, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "decompose_task",
                        "arguments": json.dumps({
                            "subtasks": [
                                {"id": "t1", "description": "Fix the bug"},
                            ],
                            "reasoning": "Simple single task",
                        }),
                    }
                }
            ],
        }

        decomposer = TaskDecomposer(llm_client=mock_llm_client)
        result = await decomposer.decompose("Fix the bug")

        assert result.is_decomposed is False
        assert len(result.subtasks) == 1

    async def test_decompose_no_llm_client(self):
        decomposer = TaskDecomposer(llm_client=None)
        result = await decomposer.decompose("Do something")

        assert result.is_decomposed is False
        assert len(result.subtasks) == 1
        assert result.subtasks[0].description == "Do something"

    async def test_decompose_llm_failure(self, mock_llm_client):
        mock_llm_client.generate.side_effect = Exception("API timeout")
        decomposer = TaskDecomposer(llm_client=mock_llm_client)
        result = await decomposer.decompose("Complex task")

        assert result.is_decomposed is False
        assert len(result.subtasks) == 1
        assert "failed" in result.reasoning.lower()

    async def test_decompose_no_tool_calls(self, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "I'll just do the task",
            "tool_calls": [],
        }
        decomposer = TaskDecomposer(llm_client=mock_llm_client)
        result = await decomposer.decompose("Simple task")
        assert result.is_decomposed is False

    async def test_decompose_max_subtasks_limit(self, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "decompose_task",
                        "arguments": json.dumps({
                            "subtasks": [
                                {"id": f"t{i}", "description": f"Task {i}"}
                                for i in range(10)
                            ],
                            "reasoning": "Many tasks",
                        }),
                    }
                }
            ],
        }
        decomposer = TaskDecomposer(llm_client=mock_llm_client, max_subtasks=3)
        result = await decomposer.decompose("Do many things")
        assert len(result.subtasks) == 3

    async def test_decompose_auto_target(self, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "",
            "tool_calls": [
                {
                    "function": {
                        "name": "decompose_task",
                        "arguments": json.dumps({
                            "subtasks": [
                                {"id": "t1", "description": "Auto task", "target_agent": "auto"},
                            ],
                            "reasoning": "Auto-detect agent",
                        }),
                    }
                }
            ],
        }
        decomposer = TaskDecomposer(llm_client=mock_llm_client)
        result = await decomposer.decompose("Something")
        assert result.subtasks[0].target_subagent is None

    def test_update_agents(self, mock_llm_client):
        decomposer = TaskDecomposer(llm_client=mock_llm_client)
        assert decomposer._agent_names == []
        decomposer.update_agents(["coder", "researcher"])
        assert decomposer._agent_names == ["coder", "researcher"]


# ============================================================================
# Test ResultAggregator
# ============================================================================


@pytest.mark.unit
class TestResultAggregator:
    def test_aggregate_empty(self):
        agg = ResultAggregator()
        result = agg.aggregate([])
        assert result.summary == "No results to aggregate."
        assert len(result.results) == 0

    def test_aggregate_single(self, sample_results):
        agg = ResultAggregator()
        result = agg.aggregate([sample_results[0]])
        assert result.all_succeeded is True
        assert result.total_tokens == 500
        assert result.total_tool_calls == 3
        assert "function" in result.summary.lower()

    def test_aggregate_multiple(self, sample_results):
        agg = ResultAggregator()
        result = agg.aggregate(sample_results)
        assert result.all_succeeded is True
        assert result.total_tokens == 800
        assert result.total_tool_calls == 4
        assert "coder" in result.summary
        assert "researcher" in result.summary

    def test_aggregate_with_failure(self):
        results = [
            SubAgentResult(
                subagent_id="sa-1",
                subagent_name="coder",
                summary="Done",
                final_content="Done",
                success=True,
                tokens_used=100,
                tool_calls_count=1,
            ),
            SubAgentResult(
                subagent_id="sa-2",
                subagent_name="researcher",
                summary="Failed",
                final_content="",
                success=False,
                error="API timeout",
                tokens_used=50,
                tool_calls_count=0,
            ),
        ]
        agg = ResultAggregator()
        result = agg.aggregate(results)
        assert result.all_succeeded is False
        assert "researcher" in result.failed_agents
        assert "FAILED" in result.summary

    async def test_aggregate_with_llm(self, sample_results, mock_llm_client):
        mock_llm_client.generate.return_value = {
            "content": "Unified summary: code was written and research completed.",
        }
        agg = ResultAggregator(llm_client=mock_llm_client)
        result = await agg.aggregate_with_llm(sample_results)
        assert "Unified summary" in result.summary
        mock_llm_client.generate.assert_called_once()

    async def test_aggregate_with_llm_failure(self, sample_results, mock_llm_client):
        mock_llm_client.generate.side_effect = Exception("LLM error")
        agg = ResultAggregator(llm_client=mock_llm_client)
        result = await agg.aggregate_with_llm(sample_results)
        # Should fall back to simple aggregation
        assert "coder" in result.summary

    async def test_aggregate_with_llm_single_result(self, sample_results, mock_llm_client):
        agg = ResultAggregator(llm_client=mock_llm_client)
        result = await agg.aggregate_with_llm([sample_results[0]])
        # Single result should not call LLM
        mock_llm_client.generate.assert_not_called()

    def test_aggregated_result_frozen(self):
        result = AggregatedResult(summary="test", results=())
        with pytest.raises(AttributeError):
            result.summary = "changed"


# ============================================================================
# Test ParallelScheduler
# ============================================================================


@pytest.mark.unit
class TestParallelScheduler:
    async def test_execute_empty_tasks(self):
        scheduler = ParallelScheduler()
        events = []
        async for event in scheduler.execute(
            subtasks=[],
            subagent_map={},
            tools=[],
            base_model="test",
        ):
            events.append(event)
        assert len(events) == 0

    async def test_resolve_agent_specific(self, sample_subagents):
        agent_map = {s.name: s for s in sample_subagents}
        task = SubTask(id="t1", description="Code task", target_subagent="coder")
        agent = ParallelScheduler._resolve_agent(task, agent_map)
        assert agent is not None
        assert agent.name == "coder"

    async def test_resolve_agent_auto(self, sample_subagents):
        agent_map = {s.name: s for s in sample_subagents}
        task = SubTask(id="t1", description="Task", target_subagent=None)
        agent = ParallelScheduler._resolve_agent(task, agent_map)
        assert agent is not None  # Falls back to first available

    async def test_resolve_agent_missing(self):
        task = SubTask(id="t1", description="Task", target_subagent="nonexistent")
        agent = ParallelScheduler._resolve_agent(task, {})
        assert agent is None

    async def test_execute_single_task_lifecycle(self, sample_subagents):
        """Test that parallel execution yields lifecycle events."""
        scheduler = ParallelScheduler()
        agent_map = {s.name: s for s in sample_subagents}
        subtasks = [SubTask(id="t1", description="Test task", target_subagent="coder")]

        events = []

        # Mock SubAgentProcess.execute to yield minimal events
        with patch(
            "src.infrastructure.agent.subagent.parallel_scheduler.SubAgentProcess"
        ) as MockProcess:
            mock_instance = MagicMock()

            async def mock_execute():
                yield {
                    "type": "subagent_started",
                    "data": {"subagent_name": "coder"},
                    "timestamp": "2024-01-01T00:00:00Z",
                }
                yield {
                    "type": "subagent_completed",
                    "data": {"subagent_name": "coder"},
                    "timestamp": "2024-01-01T00:00:01Z",
                }

            mock_instance.execute = mock_execute
            mock_instance.result = SubAgentResult(
                subagent_id="sa-1",
                subagent_name="coder",
                summary="Done",
                final_content="Done",
                success=True,
            )
            MockProcess.return_value = mock_instance

            async for event in scheduler.execute(
                subtasks=subtasks,
                subagent_map=agent_map,
                tools=[],
                base_model="test-model",
            ):
                events.append(event)

        event_types = [e["type"] for e in events]
        assert "parallel_started" in event_types
        assert "subtask_started" in event_types
        assert "subtask_completed" in event_types
        assert "parallel_completed" in event_types

    async def test_scheduler_config_defaults(self):
        config = ParallelSchedulerConfig()
        assert config.max_concurrency == 3
        assert config.subtask_timeout == 120.0
        assert config.abort_on_first_failure is False

    async def test_subtask_execution_dataclass(self, sample_subagents):
        execution = SubTaskExecution(
            subtask=SubTask(id="t1", description="test"),
            subagent=sample_subagents[0],
        )
        assert not execution.started
        assert not execution.completed
        assert execution.result is None
        assert execution.error is None


# ============================================================================
# Test DecompositionResult
# ============================================================================


@pytest.mark.unit
class TestDecompositionResult:
    def test_decomposition_result_frozen(self):
        result = DecompositionResult(subtasks=(), reasoning="test")
        with pytest.raises(AttributeError):
            result.reasoning = "changed"

    def test_decomposition_result_single(self):
        result = DecompositionResult(
            subtasks=(SubTask(id="t1", description="Single"),),
            is_decomposed=False,
        )
        assert not result.is_decomposed
        assert len(result.subtasks) == 1

    def test_decomposition_result_multiple(self):
        result = DecompositionResult(
            subtasks=(
                SubTask(id="t1", description="First"),
                SubTask(id="t2", description="Second"),
            ),
            is_decomposed=True,
        )
        assert result.is_decomposed
        assert len(result.subtasks) == 2
