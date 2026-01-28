"""
Unit tests for PlanExecutor.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

from unittest.mock import AsyncMock, Mock, call
from typing import Any

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionPlanStatus,
)
from src.infrastructure.agent.planning.plan_executor import PlanExecutor


class TestPlanExecutorInit:
    """Tests for PlanExecutor initialization."""

    def test_init_with_session_processor(self) -> None:
        """Test creating PlanExecutor with session processor."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        assert executor.session_processor == mock_processor
        assert executor.event_emitter == mock_event_emitter
        assert executor.parallel_execution is False
        assert executor.max_parallel_steps == 3

    def test_init_with_parallel_enabled(self) -> None:
        """Test creating PlanExecutor with parallel execution enabled."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
            parallel_execution=True,
            max_parallel_steps=5,
        )

        assert executor.parallel_execution is True
        assert executor.max_parallel_steps == 5


class TestExecuteStep:
    """Tests for single step execution."""

    @pytest.mark.asyncio
    async def test_execute_step_success(self) -> None:
        """Test successful execution of a single step."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Tool result")
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
            tool_input={"arg": "value"},
        )

        result = await executor._execute_step(
            step=step,
            conversation_id="conv-1",
        )

        assert result == "Tool result"
        mock_processor.execute_tool.assert_called_once_with(
            tool_name="TestTool",
            tool_input={"arg": "value"},
            conversation_id="conv-1",
        )

    @pytest.mark.asyncio
    async def test_execute_step_with_think_tool(self) -> None:
        """Test execution of a think step (no actual tool)."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Think about the problem",
            tool_name="__think__",
            tool_input={},
        )

        result = await executor._execute_step(
            step=step,
            conversation_id="conv-1",
        )

        # Think steps should return a completion message
        assert "thought" in result.lower() or "complete" in result.lower()
        # Should not call the processor for think steps
        mock_processor.execute_tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_step_failure(self) -> None:
        """Test handling of step execution failure."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(
            side_effect=Exception("Tool error")
        )
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
            tool_input={},
        )

        with pytest.raises(Exception, match="Tool error"):
            await executor._execute_step(
                step=step,
                conversation_id="conv-1",
            )


class TestExecutePlanSequential:
    """Tests for sequential plan execution."""

    @pytest.mark.asyncio
    async def test_execute_plan_with_no_dependencies(self) -> None:
        """Test executing a plan with steps that have no dependencies."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Done")
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Step 1",
                tool_name="Tool1",
                tool_input={},
            ),
            ExecutionStep(
                step_id="step-2",
                description="Step 2",
                tool_name="Tool2",
                tool_input={},
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=steps,
        )

        result_plan = await executor.execute_plan(
            plan=plan,
            abort_signal=None,
        )

        assert result_plan.status == ExecutionPlanStatus.COMPLETED
        assert len(result_plan.completed_steps) == 2
        assert "step-1" in result_plan.completed_steps
        assert "step-2" in result_plan.completed_steps

    @pytest.mark.asyncio
    async def test_execute_plan_with_dependencies(self) -> None:
        """Test executing a plan with dependent steps."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Done")
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="First step",
                tool_name="Tool1",
                tool_input={},
            ),
            ExecutionStep(
                step_id="step-2",
                description="Second step (depends on step-1)",
                tool_name="Tool2",
                tool_input={},
                dependencies=["step-1"],
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=steps,
        )

        result_plan = await executor.execute_plan(
            plan=plan,
            abort_signal=None,
        )

        assert result_plan.status == ExecutionPlanStatus.COMPLETED
        assert "step-1" in result_plan.completed_steps
        assert "step-2" in result_plan.completed_steps

    @pytest.mark.asyncio
    async def test_execute_plan_emits_events(self) -> None:
        """Test that execution emits proper events."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Done")
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
            tool_input={},
        )

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=[step],
        )

        await executor.execute_plan(
            plan=plan,
            abort_signal=None,
        )

        # Verify events were emitted
        assert mock_event_emitter.call_count >= 2  # Start + at least one step event

    @pytest.mark.asyncio
    async def test_execute_plan_with_step_failure(self) -> None:
        """Test plan execution when a step fails."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(
            side_effect=["Success", Exception("Step failed")]
        )
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="First step",
                tool_name="Tool1",
                tool_input={},
            ),
            ExecutionStep(
                step_id="step-2",
                description="Failing step",
                tool_name="Tool2",
                tool_input={},
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=steps,
        )

        result_plan = await executor.execute_plan(
            plan=plan,
            abort_signal=None,
        )

        # Plan should be marked as failed
        assert result_plan.status == ExecutionPlanStatus.FAILED
        assert "step-1" in result_plan.completed_steps
        assert "step-2" in result_plan.failed_steps


class TestExecutePlanWithAbort:
    """Tests for abort signal handling."""

    @pytest.mark.asyncio
    async def test_execute_plan_with_abort_signal(self) -> None:
        """Test that abort signal stops execution."""
        import asyncio

        execution_count = 0

        async def slow_tool(*args, **kwargs):
            nonlocal execution_count
            execution_count += 1
            # Add a small delay so abort can happen
            await asyncio.sleep(0.02)
            return "Done"

        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(side_effect=slow_tool)
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        # Create an abort event
        abort_signal = asyncio.Event()

        steps = [
            ExecutionStep(
                step_id=f"step-{i}",
                description=f"Step {i}",
                tool_name="Tool",
                tool_input={},
            )
            for i in range(10)
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=steps,
        )

        # Set abort after a short delay (after ~1 step completes)
        async def abort_after_delay():
            await asyncio.sleep(0.03)
            abort_signal.set()

        abort_task = asyncio.create_task(abort_after_delay())

        result_plan = await executor.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        await abort_task

        # Plan should be cancelled
        assert result_plan.status == ExecutionPlanStatus.CANCELLED
        # Not all steps should be completed
        assert len(result_plan.completed_steps) < 10


class TestExecutePlanParallel:
    """Tests for parallel plan execution."""

    @pytest.mark.asyncio
    async def test_execute_plan_parallel_with_independent_steps(self) -> None:
        """Test parallel execution of independent steps."""
        import asyncio
        import time

        execution_order = []

        async def slow_tool(*args, **kwargs):
            execution_order.append(kwargs.get("tool_input", {}).get("id"))
            await asyncio.sleep(0.05)
            return "Done"

        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(side_effect=slow_tool)
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
            parallel_execution=True,
            max_parallel_steps=3,
        )

        steps = [
            ExecutionStep(
                step_id=f"step-{i}",
                description=f"Step {i}",
                tool_name="Tool",
                tool_input={"id": i},
            )
            for i in range(3)
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=steps,
        )

        start_time = time.time()
        result_plan = await executor.execute_plan(
            plan=plan,
            abort_signal=None,
        )
        elapsed = time.time() - start_time

        # With 3 steps of 0.05s each, parallel should be ~0.05s, sequential ~0.15s
        # Allow some overhead
        assert elapsed < 0.2
        assert result_plan.status == ExecutionPlanStatus.COMPLETED
        assert len(result_plan.completed_steps) == 3

    @pytest.mark.asyncio
    async def test_execute_plan_parallel_respects_dependencies(self) -> None:
        """Test that parallel execution respects step dependencies."""
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Done")
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
            parallel_execution=True,
        )

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="First",
                tool_name="Tool",
                tool_input={},
            ),
            ExecutionStep(
                step_id="step-2",
                description="Depends on 1",
                tool_name="Tool",
                tool_input={},
                dependencies=["step-1"],
            ),
            ExecutionStep(
                step_id="step-3",
                description="Depends on 2",
                tool_name="Tool",
                tool_input={},
                dependencies=["step-2"],
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=steps,
        )

        result_plan = await executor.execute_plan(
            plan=plan,
            abort_signal=None,
        )

        assert result_plan.status == ExecutionPlanStatus.COMPLETED
        # All steps should complete in order despite parallel mode
        assert "step-1" in result_plan.completed_steps
        assert "step-2" in result_plan.completed_steps
        assert "step-3" in result_plan.completed_steps


class TestGetReadySteps:
    """Tests for getting ready steps."""

    def test_get_ready_steps_empty_plan(self) -> None:
        """Test getting ready steps from empty plan."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        ready = executor._get_ready_steps(plan)
        assert ready == []

    def test_get_ready_steps_with_no_dependencies(self) -> None:
        """Test getting ready steps when none have dependencies."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        steps = [
            ExecutionStep(step_id="s1", description="1", tool_name="T1"),
            ExecutionStep(step_id="s2", description="2", tool_name="T2"),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        ready = executor._get_ready_steps(plan)
        assert len(ready) == 2
        assert "s1" in ready
        assert "s2" in ready

    def test_get_ready_steps_with_unmet_dependencies(self) -> None:
        """Test getting ready steps when dependencies are not met."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        steps = [
            ExecutionStep(step_id="s1", description="1", tool_name="T1"),
            ExecutionStep(
                step_id="s2",
                description="2",
                tool_name="T2",
                dependencies=["s1"],
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        ready = executor._get_ready_steps(plan)
        assert ready == ["s1"]

    def test_get_ready_steps_with_met_dependencies(self) -> None:
        """Test getting ready steps when dependencies are met."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        steps = [
            ExecutionStep(
                step_id="s1",
                description="1",
                tool_name="T1",
                status=ExecutionStepStatus.COMPLETED,
            ),
            ExecutionStep(
                step_id="s2",
                description="2",
                tool_name="T2",
                dependencies=["s1"],
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["s1"],
        )

        ready = executor._get_ready_steps(plan)
        assert ready == ["s2"]


class TestEmitEvents:
    """Tests for event emission."""

    def test_emit_step_ready_event(self) -> None:
        """Test emitting step ready event."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="Tool",
        )

        executor._emit_step_ready_event(step)

        mock_event_emitter.assert_called_once()
        call_args = mock_event_emitter.call_args
        assert "step" in str(call_args).lower() or "ready" in str(call_args).lower()

    def test_emit_step_complete_event(self) -> None:
        """Test emitting step complete event."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="Tool",
            status=ExecutionStepStatus.COMPLETED,
            result="Step result",
        )

        executor._emit_step_complete_event(step)

        mock_event_emitter.assert_called_once()

    def test_emit_plan_complete_event(self) -> None:
        """Test emitting plan complete event."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.COMPLETED,
        )

        executor._emit_plan_complete_event(plan)

        mock_event_emitter.assert_called_once()


class TestHandleStepFailure:
    """Tests for step failure handling."""

    @pytest.mark.asyncio
    async def test_handle_step_failure_marks_failed(self) -> None:
        """Test that step failure marks step as failed."""
        mock_processor = AsyncMock()
        mock_event_emitter = Mock()

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="Tool",
        )

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        error = Exception("Step failed")

        result_plan = await executor._handle_step_failure(
            plan=plan,
            step=step,
            error=error,
        )

        assert "step-1" in result_plan.failed_steps
        failed_step = result_plan.get_step_by_id("step-1")
        assert failed_step is not None
        assert failed_step.status == ExecutionStepStatus.FAILED
        assert "Step failed" in failed_step.error
