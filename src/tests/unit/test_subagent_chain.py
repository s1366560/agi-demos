"""Tests for Phase 5.2: SubAgent Chain execution."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.chain import (
    ChainResult,
    ChainStep,
    SubAgentChain,
)


def _make_subagent(name: str = "test-agent") -> SubAgent:
    return SubAgent.create(
        tenant_id="tenant-1",
        name=name,
        display_name=name,
        system_prompt=f"You are {name}.",
        trigger_description=f"Trigger for {name}",
        trigger_keywords=[name],
    )


def _make_result(
    name: str = "test-agent",
    summary: str = "Done",
    success: bool = True,
    final_content: str = "Full output",
    error: str = None,
) -> SubAgentResult:
    return SubAgentResult(
        subagent_id="sa-1",
        subagent_name=name,
        summary=summary,
        success=success,
        final_content=final_content,
        error=error,
    )


@pytest.mark.unit
class TestChainStep:
    def test_defaults(self):
        sa = _make_subagent("researcher")
        step = ChainStep(subagent=sa)

        assert step.task_template == "{input}"
        assert step.condition is None
        assert step.name == sa.display_name

    def test_custom_name(self):
        sa = _make_subagent("researcher")
        step = ChainStep(subagent=sa, name="My Step")

        assert step.name == "My Step"


@pytest.mark.unit
class TestChainResult:
    def test_to_event_data(self):
        result = ChainResult(
            steps_completed=2,
            total_steps=3,
            final_summary="All done",
            success=True,
            skipped_steps=("step-3",),
            total_tokens=500,
            total_tool_calls=10,
            execution_time_ms=2000,
        )

        data = result.to_event_data()
        assert data["steps_completed"] == 2
        assert data["total_steps"] == 3
        assert data["success"]
        assert data["skipped_steps"] == ["step-3"]


@pytest.mark.unit
class TestSubAgentChainValidation:
    def test_empty_steps_raises(self):
        with pytest.raises(ValueError, match="at least one step"):
            SubAgentChain(steps=[])


@pytest.mark.unit
class TestSubAgentChainExecution:
    async def test_single_step_chain(self):
        sa = _make_subagent("analyst")
        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa, task_template="{input}"),
        ])

        mock_result = _make_result("analyst", summary="Analysis complete")

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:
            instance = MockProcess.return_value
            instance.result = mock_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in chain.execute(
                user_message="Analyze trends",
                tools=[],
                base_model="test-model",
            ):
                events.append(event)

        assert chain.result is not None
        assert chain.result.steps_completed == 1
        assert chain.result.success
        assert chain.result.final_summary == "Analysis complete"

        # Verify lifecycle events
        event_types = [e["type"] for e in events]
        assert "chain_started" in event_types
        assert "chain_step_started" in event_types
        assert "chain_step_completed" in event_types
        assert "chain_completed" in event_types

    async def test_two_step_pipeline(self):
        researcher = _make_subagent("researcher")
        writer = _make_subagent("writer")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=researcher, task_template="{input}"),
            ChainStep(
                subagent=writer,
                task_template="Write a report based on: {prev}\n\nOriginal question: {input}",
            ),
        ])

        research_result = _make_result("researcher", summary="Found 3 trends")
        writer_result = _make_result("writer", summary="Report written")

        call_count = 0

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:

            def create_mock(*args, **kwargs):
                nonlocal call_count
                instance = MagicMock()

                if call_count == 0:
                    instance.result = research_result
                else:
                    instance.result = writer_result

                async def mock_execute():
                    yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                    yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

                instance.execute = mock_execute
                call_count += 1
                return instance

            MockProcess.side_effect = create_mock

            events = []
            async for event in chain.execute(
                user_message="Market analysis",
                tools=[],
                base_model="test-model",
            ):
                events.append(event)

        assert chain.result.steps_completed == 2
        assert chain.result.success
        assert chain.result.final_summary == "Report written"

        # Verify the writer received the researcher's output in the task
        second_call = MockProcess.call_args_list[1]
        context_arg = second_call[1].get("context") or second_call[0][1]
        task = context_arg.task_description
        assert "Found 3 trends" in task
        assert "Market analysis" in task

    async def test_conditional_step_skipped(self):
        sa1 = _make_subagent("step1")
        sa2 = _make_subagent("step2-conditional")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa1, task_template="{input}"),
            ChainStep(
                subagent=sa2,
                task_template="{input}",
                condition=lambda prev: prev is not None and not prev.success,
            ),
        ])

        result1 = _make_result("step1", summary="Success", success=True)

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:
            instance = MockProcess.return_value
            instance.result = result1

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in chain.execute(
                user_message="Do something",
                tools=[],
                base_model="test-model",
            ):
                events.append(event)

        assert chain.result.steps_completed == 1
        assert chain.result.success
        assert "step2-conditional" in chain.result.skipped_steps

        event_types = [e["type"] for e in events]
        assert "chain_step_skipped" in event_types

    async def test_conditional_step_runs(self):
        sa1 = _make_subagent("step1")
        sa2 = _make_subagent("step2-conditional")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa1, task_template="{input}"),
            ChainStep(
                subagent=sa2,
                task_template="{input}",
                condition=lambda prev: prev is not None and prev.success,
            ),
        ])

        result1 = _make_result("step1", summary="Done", success=True)
        result2 = _make_result("step2-conditional", summary="Also done", success=True)

        call_count = 0

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:

            def create_mock(*args, **kwargs):
                nonlocal call_count
                instance = MagicMock()
                instance.result = result1 if call_count == 0 else result2

                async def mock_execute():
                    yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                    yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

                instance.execute = mock_execute
                call_count += 1
                return instance

            MockProcess.side_effect = create_mock

            async for _ in chain.execute(
                user_message="Do task",
                tools=[],
                base_model="test-model",
            ):
                pass

        assert chain.result.steps_completed == 2

    async def test_chain_stops_on_failure(self):
        sa1 = _make_subagent("step1")
        sa2 = _make_subagent("step2")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa1),
            ChainStep(subagent=sa2),
        ])

        failed_result = _make_result("step1", success=False, error="Crashed")

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:
            instance = MockProcess.return_value
            instance.result = failed_result

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_failed", "data": {}, "timestamp": "t"}

            instance.execute = mock_execute

            events = []
            async for event in chain.execute(
                user_message="Do task",
                tools=[],
                base_model="test-model",
            ):
                events.append(event)

        assert chain.result.steps_completed == 1
        assert not chain.result.success

        event_types = [e["type"] for e in events]
        assert "chain_step_failed" in event_types

    async def test_chain_abort_signal(self):
        sa1 = _make_subagent("step1")
        sa2 = _make_subagent("step2")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa1),
            ChainStep(subagent=sa2),
        ])

        result1 = _make_result("step1", summary="Done")
        abort = asyncio.Event()

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:
            instance = MockProcess.return_value
            instance.result = result1

            async def mock_execute():
                yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}
                # Set abort after first step
                abort.set()

            instance.execute = mock_execute

            async for _ in chain.execute(
                user_message="Do task",
                tools=[],
                base_model="test-model",
                abort_signal=abort,
            ):
                pass

        # Should have stopped after step1
        assert chain.result.steps_completed == 1

    async def test_template_step_n_reference(self):
        """Test {step_N} template references."""
        sa1 = _make_subagent("sa1")
        sa2 = _make_subagent("sa2")
        sa3 = _make_subagent("sa3")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa1, task_template="{input}"),
            ChainStep(subagent=sa2, task_template="{input}"),
            ChainStep(
                subagent=sa3,
                task_template="Combine: {step_0} and {step_1}",
            ),
        ])

        results = [
            _make_result("sa1", summary="Result A"),
            _make_result("sa2", summary="Result B"),
            _make_result("sa3", summary="Combined"),
        ]
        call_count = 0

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:

            def create_mock(*args, **kwargs):
                nonlocal call_count
                instance = MagicMock()
                instance.result = results[call_count]

                async def mock_execute():
                    yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                    yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

                instance.execute = mock_execute
                call_count += 1
                return instance

            MockProcess.side_effect = create_mock

            async for _ in chain.execute(
                user_message="Question",
                tools=[],
                base_model="test-model",
            ):
                pass

        # Verify the third call received {step_0} and {step_1}
        third_call = MockProcess.call_args_list[2]
        context_arg = third_call[1].get("context") or third_call[0][1]
        task = context_arg.task_description
        assert "Result A" in task
        assert "Result B" in task

    async def test_chain_metrics_aggregation(self):
        sa1 = _make_subagent("sa1")
        sa2 = _make_subagent("sa2")

        chain = SubAgentChain(steps=[
            ChainStep(subagent=sa1),
            ChainStep(subagent=sa2),
        ])

        r1 = SubAgentResult(
            subagent_id="1", subagent_name="sa1", summary="R1",
            success=True, tokens_used=100, tool_calls_count=3,
        )
        r2 = SubAgentResult(
            subagent_id="2", subagent_name="sa2", summary="R2",
            success=True, tokens_used=200, tool_calls_count=5,
        )

        call_count = 0

        with patch(
            "src.infrastructure.agent.subagent.chain.SubAgentProcess"
        ) as MockProcess:

            def create_mock(*args, **kwargs):
                nonlocal call_count
                instance = MagicMock()
                instance.result = r1 if call_count == 0 else r2

                async def mock_execute():
                    yield {"type": "subagent_started", "data": {}, "timestamp": "t"}
                    yield {"type": "subagent_completed", "data": {}, "timestamp": "t"}

                instance.execute = mock_execute
                call_count += 1
                return instance

            MockProcess.side_effect = create_mock

            async for _ in chain.execute(
                user_message="Do task",
                tools=[],
                base_model="test-model",
            ):
                pass

        assert chain.result.total_tokens == 300
        assert chain.result.total_tool_calls == 8
        assert chain.result.execution_time_ms >= 0
