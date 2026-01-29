"""
Unit tests for parallel execution in PlanExecutor.

Tests cover:
- Parallel execution of independent steps
- Concurrency limiting with Semaphore
- Error handling and isolation
- AbortSignal support
- Empty ready_steps handling
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionPlanStatus,
)


@pytest.mark.unit
class TestPlanExecutorParallel:
    """Test parallel execution functionality in PlanExecutor."""

    @pytest.fixture
    def mock_session_processor(self):
        """Create a mock session processor."""
        processor = AsyncMock()
        processor.execute_tool = AsyncMock(return_value="Success")
        return processor

    @pytest.fixture
    def mock_event_emitter(self):
        """Create a mock event emitter."""
        emitter = MagicMock()
        return emitter

    @pytest.fixture
    def plan_executor(self, mock_session_processor, mock_event_emitter):
        """Create a PlanExecutor instance for testing."""
        from src.infrastructure.agent.planning.plan_executor import PlanExecutor

        # Limit parallel steps to 3 for testing
        return PlanExecutor(
            session_processor=mock_session_processor,
            event_emitter=mock_event_emitter,
            parallel_execution=True,
            max_parallel_steps=3,
        )

    @pytest.fixture
    def sample_plan(self):
        """Create a sample execution plan with multiple steps."""
        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Step 1",
                tool_name="test_tool",
                tool_input={"param": "value1"},
                dependencies=[],
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-2",
                description="Step 2",
                tool_name="test_tool",
                tool_input={"param": "value2"},
                dependencies=["step-1"],
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-3",
                description="Step 3",
                tool_name="test_tool",
                tool_input={"param": "value3"},
                dependencies=["step-1"],
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-4",
                description="Step 4",
                tool_name="test_tool",
                tool_input={"param": "value4"},
                dependencies=["step-2", "step-3"],
                status=ExecutionStepStatus.PENDING,
            ),
        ]

        return ExecutionPlan(
            id="plan-123",
            conversation_id="conv-456",
            user_query="Test query",
            steps=steps,
            status=ExecutionPlanStatus.DRAFT,
            reflection_enabled=True,
            max_reflection_cycles=3,
            completed_steps=[],
            failed_steps=[],
        )

    @pytest.mark.asyncio
    async def test_parallel_execution_of_independent_steps(
        self, plan_executor, sample_plan
    ):
        """Test that independent steps execute in parallel."""
        # Create a new plan with independent steps
        independent_steps = [
            ExecutionStep(
                step_id="step-1",
                description="Step 1",
                tool_name="test_tool",
                tool_input={"param": "value1"},
                dependencies=[],
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-2",
                description="Step 2",
                tool_name="test_tool",
                tool_input={"param": "value2"},
                dependencies=[],  # No dependencies
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-3",
                description="Step 3",
                tool_name="test_tool",
                tool_input={"param": "value3"},
                dependencies=[],  # No dependencies
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-4",
                description="Step 4",
                tool_name="test_tool",
                tool_input={"param": "value4"},
                dependencies=[],  # No dependencies
                status=ExecutionStepStatus.PENDING,
            ),
        ]

        independent_plan = ExecutionPlan(
            id="plan-123",
            conversation_id="conv-456",
            user_query="Test query",
            steps=independent_steps,
            status=ExecutionPlanStatus.DRAFT,
            reflection_enabled=True,
            max_reflection_cycles=3,
            completed_steps=[],
            failed_steps=[],
        )

        # Track execution order
        execution_order = []
        original_execute = plan_executor._execute_step

        async def track_execution(step, conversation_id):
            execution_order.append(step.step_id)
            await asyncio.sleep(0.01)  # Small delay to allow parallel execution
            return await original_execute(step, conversation_id)

        plan_executor._execute_step = track_execution

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            independent_plan, abort_signal=None
        )

        # Verify all steps completed
        assert len(result.completed_steps) == 4
        assert all(
            result.get_step_by_id(sid).status == ExecutionStepStatus.COMPLETED
            for sid in ["step-1", "step-2", "step-3", "step-4"]
        )

    @pytest.mark.asyncio
    async def test_concurrency_limited_by_max_parallel_steps(
        self, plan_executor, sample_plan
    ):
        """Test that concurrent execution respects max_parallel_steps."""
        # Create 5 independent steps (more than max_parallel_steps=3)
        for i in range(5, 7):
            sample_plan.steps.append(
                ExecutionStep(
                    step_id=f"step-{i}",
                    description=f"Step {i}",
                    tool_name="test_tool",
                    tool_input={"param": f"value{i}"},
                    dependencies=[],
                    status=ExecutionStepStatus.PENDING,
                )
            )

        # Track concurrent executions
        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def tracked_execute(step, conversation_id):
            nonlocal concurrent_count, max_concurrent

            async with lock:
                concurrent_count += 1
                if concurrent_count > max_concurrent:
                    max_concurrent = concurrent_count

            await asyncio.sleep(0.05)  # Simulate work

            async with lock:
                concurrent_count -= 1

            return f"Result for {step.step_id}"

        plan_executor._execute_step = tracked_execute

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            sample_plan, abort_signal=None
        )

        # Verify max concurrent executions didn't exceed limit
        assert max_concurrent <= plan_executor.max_parallel_steps
        assert max_concurrent == 3  # Should hit the limit

    @pytest.mark.asyncio
    async def test_step_failure_does_not_block_other_steps(
        self, plan_executor, sample_plan
    ):
        """Test that a failed step doesn't prevent other steps from executing."""
        # Make step-2 fail
        async def failing_execute(step, conversation_id):
            if step.step_id == "step-2":
                raise Exception("Step 2 failed")
            return f"Result for {step.step_id}"

        plan_executor._execute_step = failing_execute

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            sample_plan, abort_signal=None
        )

        # Verify step-2 failed
        step_2 = result.get_step_by_id("step-2")
        assert step_2.status == ExecutionStepStatus.FAILED

        # Verify other steps still executed
        assert result.get_step_by_id("step-1").status == ExecutionStepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_execution(
        self, plan_executor, sample_plan
    ):
        """Test that Semaphore properly limits concurrent execution."""
        # Create 10 independent steps
        for i in range(5, 15):
            sample_plan.steps.append(
                ExecutionStep(
                    step_id=f"step-{i}",
                    description=f"Step {i}",
                    tool_name="test_tool",
                    tool_input={"param": f"value{i}"},
                    dependencies=[],
                    status=ExecutionStepStatus.PENDING,
                )
            )

        execution_times = []

        async def timed_execute(step, conversation_id):
            import time

            start = time.time()
            await asyncio.sleep(0.1)  # 100ms work
            end = time.time()
            execution_times.append((step.step_id, end - start))
            return f"Result for {step.step_id}"

        plan_executor._execute_step = timed_execute

        # Execute plan
        await plan_executor._execute_plan_parallel(sample_plan, abort_signal=None)

        # With max_parallel_steps=3 and 10 steps taking 100ms each,
        # we expect approximately 4 batches (3+3+3+1) = ~400ms total
        # If all ran in parallel, it would be ~100ms
        total_time = max(t for _, t in execution_times)

        # Verify concurrency limiting worked
        # 10 steps / 3 concurrent ≈ 4 batches
        # 4 batches * 100ms = 400ms (with some overhead)
        assert total_time >= 0.3  # At least 300ms (3 batches minimum)
        assert total_time < 0.6  # Less than 600ms

    @pytest.mark.asyncio
    async def test_errors_logged_correctly(self, plan_executor, sample_plan):
        """Test that execution errors are logged properly."""
        # Make multiple steps fail
        async def failing_execute(step, conversation_id):
            if step.step_id in ["step-2", "step-3"]:
                raise Exception(f"{step.step_id} failed")
            return f"Result for {step.step_id}"

        plan_executor._execute_step = failing_execute

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            sample_plan, abort_signal=None
        )

        # Verify failed steps are in failed_steps
        assert "step-2" in result.failed_steps or any(
            s.step_id == "step-2" and s.status == ExecutionStepStatus.FAILED
            for s in result.steps
        )

    @pytest.mark.asyncio
    async def test_all_steps_completed_on_success(
        self, plan_executor, sample_plan
    ):
        """Test that all steps are marked completed on successful execution."""
        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            sample_plan, abort_signal=None
        )

        # Verify all steps completed
        assert len(result.completed_steps) == 4
        assert len(result.failed_steps) == 0

    @pytest.mark.asyncio
    async def test_abort_signal_cancels_execution(
        self, plan_executor, sample_plan
    ):
        """Test that AbortSignal can cancel ongoing execution."""
        abort_signal = asyncio.Event()

        # Make execution slow enough to abort
        async def slow_execute(step, conversation_id):
            await asyncio.sleep(0.1)
            if step.step_id == "step-2":
                abort_signal.set()  # Abort after step-2 starts
            return f"Result for {step.step_id}"

        plan_executor._execute_step = slow_execute

        # Execute in background
        task = asyncio.create_task(
            plan_executor._execute_plan_parallel(sample_plan, abort_signal)
        )

        # Wait a bit then check result
        await asyncio.sleep(0.05)

        # Signal abort
        abort_signal.set()

        result = await task

        # Verify plan was cancelled
        assert result.status == ExecutionPlanStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_empty_ready_steps_returns_original_plan(
        self, plan_executor, sample_plan
    ):
        """Test that empty ready_steps returns the original plan."""
        # Create a plan with all steps already completed
        completed_steps = []
        for i, step in enumerate(sample_plan.steps):
            completed_step = ExecutionStep(
                step_id=step.step_id,
                description=step.description,
                tool_name=step.tool_name,
                tool_input=step.tool_input,
                dependencies=step.dependencies,
                status=ExecutionStepStatus.COMPLETED,
            )
            completed_steps.append(completed_step)

        completed_plan = ExecutionPlan(
            id=sample_plan.id,
            conversation_id=sample_plan.conversation_id,
            user_query=sample_plan.user_query,
            steps=completed_steps,
            status=ExecutionPlanStatus.EXECUTING,
            reflection_enabled=sample_plan.reflection_enabled,
            max_reflection_cycles=sample_plan.max_reflection_cycles,
            completed_steps=[s.step_id for s in completed_steps],
            failed_steps=[],
        )

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            completed_plan, abort_signal=None
        )

        # Verify plan is complete
        assert result.is_complete
        assert len(result.completed_steps) == 4

    @pytest.mark.asyncio
    async def test_dependencies_respected_in_parallel_execution(
        self, plan_executor, sample_plan
    ):
        """Test that step dependencies are respected during parallel execution."""
        execution_order = []

        async def tracking_execute(step, conversation_id):
            execution_order.append(step.step_id)
            await asyncio.sleep(0.01)
            return f"Result for {step.step_id}"

        plan_executor._execute_step = tracking_execute

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            sample_plan, abort_signal=None
        )

        # Verify step-1 executed before step-2 and step-3
        step_1_idx = execution_order.index("step-1")
        step_2_idx = execution_order.index("step-2")
        step_3_idx = execution_order.index("step-3")

        assert step_1_idx < step_2_idx
        assert step_1_idx < step_3_idx

        # Verify step-4 executed after both step-2 and step-3
        step_4_idx = execution_order.index("step-4")
        assert step_4_idx > step_2_idx
        assert step_4_idx > step_3_idx

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure_states(
        self, plan_executor, sample_plan
    ):
        """Test handling of mixed successful and failed steps."""
        # Make step-2 fail, others succeed
        async def mixed_execute(step, conversation_id):
            if step.step_id == "step-2":
                raise Exception("Step 2 failed")
            return f"Result for {step.step_id}"

        plan_executor._execute_step = mixed_execute

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            sample_plan, abort_signal=None
        )

        # Verify mixed states
        assert result.get_step_by_id("step-1").status == ExecutionStepStatus.COMPLETED
        assert result.get_step_by_id("step-2").status == ExecutionStepStatus.FAILED

        # Steps depending on step-2 should not complete
        step_4 = result.get_step_by_id("step-4")
        assert step_4.status in [ExecutionStepStatus.PENDING, ExecutionStepStatus.FAILED]

    @pytest.mark.asyncio
    async def test_concurrent_limit_of_one_is_sequential(
        self, plan_executor, sample_plan
    ):
        """Test that max_parallel_steps=1 results in sequential execution."""
        # Set limit to 1
        plan_executor.max_parallel_steps = 1

        # Create a plan with all independent steps
        independent_steps = [
            ExecutionStep(
                step_id=f"step-{i}",
                description=f"Step {i}",
                tool_name="test_tool",
                tool_input={"param": f"value{i}"},
                dependencies=[],
                status=ExecutionStepStatus.PENDING,
            )
            for i in range(1, 5)
        ]

        independent_plan = ExecutionPlan(
            id="plan-123",
            conversation_id="conv-456",
            user_query="Test query",
            steps=independent_steps,
            status=ExecutionPlanStatus.DRAFT,
            reflection_enabled=True,
            max_reflection_cycles=3,
            completed_steps=[],
            failed_steps=[],
        )

        execution_order = []

        async def tracking_execute(step, conversation_id):
            execution_order.append(step.step_id)
            await asyncio.sleep(0.01)
            return f"Result for {step.step_id}"

        plan_executor._execute_step = tracking_execute

        # Execute plan
        result = await plan_executor._execute_plan_parallel(
            independent_plan, abort_signal=None
        )

        # With limit of 1, should execute sequentially
        # All steps should complete in order
        assert execution_order == ["step-1", "step-2", "step-3", "step-4"]
