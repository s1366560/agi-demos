"""
Unit tests for PlanModeOrchestrator.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionPlanStatus,
    ExecutionStep,
    ExecutionStepStatus,
)
from src.domain.model.agent.reflection_result import (
    AdjustmentType,
    ReflectionResult,
    StepAdjustment,
)
from src.infrastructure.agent.planning.plan_mode_orchestrator import PlanModeOrchestrator


class TestPlanModeOrchestratorInit:
    """Tests for PlanModeOrchestrator initialization."""

    def test_init_with_required_dependencies(self) -> None:
        """Test creating orchestrator with all dependencies."""
        mock_generator = Mock()
        mock_executor = Mock()
        mock_reflector = Mock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        assert orchestrator.plan_generator == mock_generator
        assert orchestrator.plan_executor == mock_executor
        assert orchestrator.plan_reflector == mock_reflector
        assert orchestrator.plan_adjuster == mock_adjuster
        assert orchestrator.event_emitter == mock_event_emitter

    def test_init_with_default_params(self) -> None:
        """Test creating orchestrator with default parameters."""
        mock_generator = Mock()
        mock_executor = Mock()
        mock_reflector = Mock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        assert orchestrator.max_reflection_cycles == 3


class TestExecutePlanSimple:
    """Tests for simple plan execution (no reflection)."""

    @pytest.mark.asyncio
    async def test_execute_plan_to_completion(self) -> None:
        """Test executing a plan that completes successfully."""
        # Setup mocks
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        # Create a plan in EXECUTING state (will be completed by executor)
        input_plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.PENDING,
                ),
            ],
            status=ExecutionPlanStatus.EXECUTING,
        )

        # After execution, plan is completed
        completed_plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                ),
            ],
            completed_steps=["step-1"],
            status=ExecutionPlanStatus.COMPLETED,
        )

        # Executor returns completed plan
        mock_executor.execute_plan = AsyncMock(return_value=completed_plan)

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        result = await orchestrator.execute_plan(
            plan=input_plan,
            abort_signal=abort_signal,
        )

        assert result.status == ExecutionPlanStatus.COMPLETED
        # Executor should have been called once
        assert mock_executor.execute_plan.call_count == 1
        # Reflector should NOT be called when plan is already terminal after execution
        assert mock_reflector.reflect.call_count == 0

    @pytest.mark.asyncio
    async def test_execute_plan_with_reflection_disabled(self) -> None:
        """Test executing plan with reflection disabled."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.PENDING,
                ),
            ],
            status=ExecutionPlanStatus.EXECUTING,
            reflection_enabled=False,
        )

        completed_plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                ),
            ],
            completed_steps=["step-1"],
            status=ExecutionPlanStatus.COMPLETED,
            reflection_enabled=False,
        )

        mock_executor.execute_plan = AsyncMock(return_value=completed_plan)

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        assert result.status == ExecutionPlanStatus.COMPLETED
        # Reflector should NOT be called when disabled
        assert mock_reflector.reflect.call_count == 0


class TestExecutePlanWithReflection:
    """Tests for plan execution with reflection and adjustment."""

    @pytest.mark.asyncio
    async def test_execute_plan_with_needs_adjustment(self) -> None:
        """Test workflow when reflection suggests adjustments."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        # Initial plan with a failed step
        initial_plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Failed step",
                    tool_name="Tool",
                    status=ExecutionStepStatus.FAILED,
                    error="Failed",
                ),
            ],
            failed_steps=["step-1"],
        )

        # After first execution
        after_first_exec = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Failed step",
                    tool_name="Tool",
                    status=ExecutionStepStatus.FAILED,
                    error="Failed",
                ),
            ],
            failed_steps=["step-1"],
            status=ExecutionPlanStatus.EXECUTING,
        )

        # Adjusted plan
        adjusted_plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Retry step",
                    tool_name="Tool",
                    status=ExecutionStepStatus.PENDING,
                    tool_input={"retry": True},
                ),
            ],
        )

        # Final completed plan
        final_plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Retry step",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                    result="Success",
                ),
            ],
            completed_steps=["step-1"],
            status=ExecutionPlanStatus.COMPLETED,
        )

        # Setup executor to return different results
        mock_executor.execute_plan = AsyncMock(
            side_effect=[after_first_exec, final_plan]
        )

        # Reflector suggests adjustment
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.RETRY,
            reason="Retry",
            new_tool_input={"retry": True},
        )

        mock_reflector.reflect = AsyncMock(
            return_value=ReflectionResult.needs_adjustment(
                reasoning="Need to retry",
                adjustments=[adjustment],
            ),
        )

        # Adjuster returns adjusted plan (not async)
        mock_adjuster.apply_adjustments = Mock(return_value=adjusted_plan)

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        result = await orchestrator.execute_plan(
            plan=initial_plan,
            abort_signal=abort_signal,
        )

        assert result.status == ExecutionPlanStatus.COMPLETED
        # Executor called twice (initial + after adjustment)
        assert mock_executor.execute_plan.call_count == 2
        # Reflector called once (after first execution)
        assert mock_reflector.reflect.call_count == 1
        # Adjuster called once
        assert mock_adjuster.apply_adjustments.call_count == 1


class TestExecutePlanWithAbort:
    """Tests for abort signal handling."""

    @pytest.mark.asyncio
    async def test_abort_during_execution(self) -> None:
        """Test aborting during plan execution."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                ),
            ],
            status=ExecutionPlanStatus.CANCELLED,
        )

        mock_executor.execute_plan = AsyncMock(return_value=plan)

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()
        abort_signal.set()  # Already set

        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        assert result.status == ExecutionPlanStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_abort_before_execution(self) -> None:
        """Test abort is checked before execution."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                ),
            ],
        )

        mock_executor.execute_plan = AsyncMock(return_value=plan)

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()
        abort_signal.set()

        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        # Should check abort first and return cancelled plan
        assert result.status == ExecutionPlanStatus.CANCELLED


class TestMaxReflectionCycles:
    """Tests for max reflection cycles enforcement."""

    @pytest.mark.asyncio
    async def test_max_reflection_cycles_enforced(self) -> None:
        """Test that max reflection cycles is respected."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                ),
            ],
        )

        # Always return the same plan (incomplete)
        mock_executor.execute_plan = AsyncMock(return_value=plan)

        # Always request adjustment
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Keep adjusting",
        )

        mock_reflector.reflect = AsyncMock(
            return_value=ReflectionResult.needs_adjustment(
                reasoning="Keep adjusting",
                adjustments=[adjustment],
            )
        )

        mock_adjuster.apply_adjustments = Mock(return_value=plan)

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
            max_reflection_cycles=2,
        )

        abort_signal = asyncio.Event()

        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        # Should stop after max cycles
        # Initial execution + max cycles = total calls
        assert mock_executor.execute_plan.call_count <= 3  # Initial + 2 cycles
        assert mock_reflector.reflect.call_count <= 2


class TestTerminalStates:
    """Tests for handling terminal reflection states."""

    @pytest.mark.asyncio
    async def test_reflection_complete_stops_execution(self) -> None:
        """Test that COMPLETE reflection stops execution."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                ),
            ],
            completed_steps=["step-1"],
        )

        mock_executor.execute_plan = AsyncMock(return_value=plan)
        mock_reflector.reflect = AsyncMock(
            return_value=ReflectionResult.complete(
                reasoning="Goal achieved",
                final_summary="Success",
            )
        )

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        assert result.status == ExecutionPlanStatus.COMPLETED
        # Should only execute once
        assert mock_executor.execute_plan.call_count == 1

    @pytest.mark.asyncio
    async def test_reflection_failed_stops_execution(self) -> None:
        """Test that FAILED reflection stops execution."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.FAILED,
                    error="Critical failure",
                ),
            ],
            failed_steps=["step-1"],
        )

        mock_executor.execute_plan = AsyncMock(return_value=plan)
        mock_reflector.reflect = AsyncMock(
            return_value=ReflectionResult.failed(
                reasoning="Cannot recover",
                error_type="critical",
            )
        )

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        assert result.status == ExecutionPlanStatus.FAILED
        # Should only execute once
        assert mock_executor.execute_plan.call_count == 1


class TestErrorHandling:
    """Tests for error handling in orchestrator."""

    @pytest.mark.asyncio
    async def test_executor_error_propagates(self) -> None:
        """Test that executor errors are handled."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                ),
            ],
        )

        mock_executor.execute_plan = AsyncMock(
            side_effect=Exception("Executor failed")
        )

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        with pytest.raises(Exception, match="Executor failed"):
            await orchestrator.execute_plan(
                plan=plan,
                abort_signal=abort_signal,
            )

    @pytest.mark.asyncio
    async def test_reflector_error_uses_default(self) -> None:
        """Test that reflector errors use safe defaults."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                ),
            ],
            completed_steps=["step-1"],
            status=ExecutionPlanStatus.EXECUTING,
        )

        mock_executor.execute_plan = AsyncMock(return_value=plan)
        mock_reflector.reflect = AsyncMock(
            side_effect=Exception("Reflector failed")
        )

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        # Should not raise, use default reflection
        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        # Should complete with default behavior
        assert result.status == ExecutionPlanStatus.EXECUTING


class TestEventEmission:
    """Tests for SSE event emission."""

    @pytest.mark.asyncio
    async def test_emits_reflection_events(self) -> None:
        """Test that reflection events are emitted."""
        mock_generator = Mock()
        mock_executor = AsyncMock()
        mock_reflector = AsyncMock()
        mock_adjuster = Mock()
        mock_event_emitter = Mock()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                ),
            ],
            completed_steps=["step-1"],
        )

        mock_executor.execute_plan = AsyncMock(return_value=plan)
        mock_reflector.reflect = AsyncMock(
            return_value=ReflectionResult.on_track(
                reasoning="On track",
            )
        )

        orchestrator = PlanModeOrchestrator(
            plan_generator=mock_generator,
            plan_executor=mock_executor,
            plan_reflector=mock_reflector,
            plan_adjuster=mock_adjuster,
            event_emitter=mock_event_emitter,
        )

        abort_signal = asyncio.Event()

        await orchestrator.execute_plan(
            plan=plan,
            abort_signal=abort_signal,
        )

        # Should have emitted reflection event
        event_calls = mock_event_emitter.call_args_list
        reflection_events = [
            call for call in event_calls
            if "reflection" in str(call).lower()
        ]
        assert len(reflection_events) >= 1
