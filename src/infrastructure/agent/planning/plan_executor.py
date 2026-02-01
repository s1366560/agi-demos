"""
Plan Executor for Plan Mode.

This module provides the PlanExecutor class that executes
execution plans created by the PlanGenerator.
"""

import asyncio
import logging
from typing import Any

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
)

logger = logging.getLogger(__name__)


class PlanExecutor:
    """
    Executes execution plans with support for sequential and parallel execution.

    The PlanExecutor takes an ExecutionPlan and runs its steps, respecting
    dependencies and emitting progress events.

    Attributes:
        session_processor: Async processor for executing tools
        event_emitter: Callback for emitting SSE events
        parallel_execution: Whether to enable parallel execution
        max_parallel_steps: Maximum number of parallel steps
    """

    def __init__(
        self,
        session_processor: Any,
        event_emitter: Any,
        parallel_execution: bool = False,
        max_parallel_steps: int = 3,
    ) -> None:
        """
        Initialize the PlanExecutor.

        Args:
            session_processor: Async processor with execute_tool method
            event_emitter: Callable for emitting events
            parallel_execution: Enable parallel execution of independent steps
            max_parallel_steps: Maximum parallel steps when parallel enabled
        """
        self.session_processor = session_processor
        self.event_emitter = event_emitter
        self.parallel_execution = parallel_execution
        self.max_parallel_steps = max_parallel_steps

    async def _execute_step(
        self,
        step: ExecutionStep,
        conversation_id: str,
    ) -> str:
        """
        Execute a single step.

        Args:
            step: The step to execute
            conversation_id: ID of the conversation

        Returns:
            The result of the step execution

        Raises:
            Exception: If step execution fails
        """
        # Handle think steps (no actual tool execution)
        if step.tool_name == "__think__":
            return f"Thought: {step.description}"

        # Execute the tool through the session processor
        result = await self.session_processor.execute_tool(
            tool_name=step.tool_name,
            tool_input=step.tool_input,
            conversation_id=conversation_id,
        )

        return result

    def _get_ready_steps(self, plan: ExecutionPlan) -> list[str]:
        """
        Get list of step IDs that are ready to execute.

        A step is ready if:
        - It is PENDING status
        - All its dependencies are in completed_steps

        Args:
            plan: The execution plan

        Returns:
            List of step IDs ready to execute
        """
        return plan.get_ready_steps()

    async def _handle_step_failure(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
        error: Exception,
    ) -> ExecutionPlan:
        """
        Handle a step execution failure.

        Args:
            plan: The current execution plan
            step: The step that failed
            error: The exception that occurred

        Returns:
            Updated plan with step marked as failed
        """
        failed_step = step.mark_failed(str(error))
        plan = plan.update_step(failed_step)
        plan = plan.mark_step_failed(step.step_id, str(error))
        return plan

    def _emit_step_ready_event(self, step: ExecutionStep) -> None:
        """Emit an event when a step is ready to execute."""
        if self.event_emitter:
            self.event_emitter(
                {
                    "type": "PLAN_STEP_READY",
                    "data": {
                        "step_id": step.step_id,
                        "description": step.description,
                        "tool_name": step.tool_name,
                    },
                }
            )

    def _emit_step_complete_event(self, step: ExecutionStep) -> None:
        """Emit an event when a step completes."""
        if self.event_emitter:
            self.event_emitter(
                {
                    "type": "PLAN_STEP_COMPLETE",
                    "data": {
                        "step_id": step.step_id,
                        "status": step.status.value,
                        "result": step.result,
                    },
                }
            )

    def _emit_plan_start_event(self, plan: ExecutionPlan) -> None:
        """Emit an event when plan execution starts."""
        if self.event_emitter:
            self.event_emitter(
                {
                    "type": "PLAN_EXECUTION_START",
                    "data": {
                        "plan_id": plan.id,
                        "total_steps": len(plan.steps),
                        "user_query": plan.user_query,
                    },
                }
            )

    def _emit_plan_complete_event(self, plan: ExecutionPlan) -> None:
        """Emit an event when plan execution completes."""
        if self.event_emitter:
            self.event_emitter(
                {
                    "type": "PLAN_EXECUTION_COMPLETE",
                    "data": {
                        "plan_id": plan.id,
                        "status": plan.status.value,
                        "completed_steps": len(plan.completed_steps),
                        "failed_steps": len(plan.failed_steps),
                    },
                }
            )

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        abort_signal: Any | None,
    ) -> ExecutionPlan:
        """
        Execute an execution plan.

        Args:
            plan: The execution plan to execute
            abort_signal: Optional asyncio.Event for aborting execution

        Returns:
            Updated execution plan after execution
        """
        # Emit start event
        self._emit_plan_start_event(plan)

        # Mark plan as executing
        plan = plan.mark_executing()

        try:
            if self.parallel_execution:
                plan = await self._execute_plan_parallel(plan, abort_signal)
            else:
                plan = await self._execute_plan_sequential(plan, abort_signal)

            # Determine final status based on execution results
            if abort_signal and abort_signal.is_set():
                plan = plan.mark_cancelled()
            elif plan.failed_steps:
                # If there are failed steps, mark as failed
                plan = plan.mark_failed("One or more steps failed")
            elif plan.is_complete:
                plan = plan.mark_completed()

        except Exception as e:
            plan = plan.mark_failed(str(e))

        # Emit completion event
        self._emit_plan_complete_event(plan)

        return plan

    async def _execute_plan_sequential(
        self,
        plan: ExecutionPlan,
        abort_signal: Any | None,
    ) -> ExecutionPlan:
        """
        Execute plan sequentially, respecting dependencies.

        Args:
            plan: The execution plan
            abort_signal: Optional abort signal

        Returns:
            Updated execution plan
        """
        while not plan.is_complete:
            # Check abort signal
            if abort_signal and abort_signal.is_set():
                break

            # Get ready steps
            ready_steps = self._get_ready_steps(plan)

            if not ready_steps:
                # No steps ready - check if we're stuck or done
                if plan.completed_steps or plan.failed_steps:
                    # Some progress made, might just be waiting on dependencies
                    # Check if there are any pending steps left
                    pending_steps = [
                        s for s in plan.steps if s.status == ExecutionStepStatus.PENDING
                    ]
                    if not pending_steps:
                        break
                else:
                    # No progress and no ready steps - stuck
                    break

            # Execute one ready step (or first of ready steps for sequential)
            step_id = ready_steps[0]
            step = plan.get_step_by_id(step_id)

            if step is None:
                continue

            # Emit ready event
            self._emit_step_ready_event(step)

            # Mark step as started
            plan = plan.mark_step_started(step_id)
            step = plan.get_step_by_id(step_id)

            if step is None:
                continue

            try:
                # Execute the step
                result = await self._execute_step(step, plan.conversation_id)

                # Mark step as completed
                plan = plan.mark_step_completed(step_id, result)
                step = plan.get_step_by_id(step_id)

                if step:
                    self._emit_step_complete_event(step)

            except Exception as e:
                # Handle step failure
                plan = await self._handle_step_failure(plan, step, e)
                # Stop execution on step failure
                break

        return plan

    async def _execute_plan_parallel(
        self,
        plan: ExecutionPlan,
        abort_signal: Any | None,
    ) -> ExecutionPlan:
        """
        Execute plan with parallel execution of independent steps.

        Uses Semaphore to limit concurrent execution and properly handles
        errors, abort signals, and step dependencies.

        Args:
            plan: The execution plan
            abort_signal: Optional abort signal

        Returns:
            Updated execution plan
        """
        # Use Semaphore to limit concurrent executions
        semaphore = asyncio.Semaphore(self.max_parallel_steps)
        # Use a mutable container to allow inner function to update plan state
        plan_state = {"plan": plan}

        async def execute_with_limit(step_id: str) -> tuple[str, ExecutionStep | None]:
            """Execute step with semaphore limit."""
            nonlocal plan_state
            async with semaphore:
                # Check abort signal before executing
                if abort_signal and abort_signal.is_set():
                    return step_id, None

                try:
                    current_plan = plan_state["plan"]
                    step = current_plan.get_step_by_id(step_id)
                    if not step:
                        logger.error(f"Step {step_id} not found in plan")
                        return step_id, None

                    # Emit ready event
                    self._emit_step_ready_event(step)

                    # Mark step as started
                    current_plan = current_plan.mark_step_started(step_id)
                    plan_state["plan"] = current_plan
                    step = current_plan.get_step_by_id(step_id)

                    if not step:
                        return step_id, None

                    # Execute the step
                    result = await self._execute_step(step, current_plan.conversation_id)

                    # Mark step as completed
                    current_plan = plan_state["plan"]  # Re-fetch in case other tasks updated it
                    current_plan = current_plan.mark_step_completed(step_id, result)
                    plan_state["plan"] = current_plan
                    updated_step = current_plan.get_step_by_id(step_id)

                    if updated_step:
                        self._emit_step_complete_event(updated_step)

                    return step_id, updated_step
                except Exception as e:
                    logger.error(f"Step {step_id} failed with error: {e}")
                    # Mark step as failed
                    current_plan = plan_state["plan"]
                    step = current_plan.get_step_by_id(step_id)
                    if step:
                        current_plan = await self._handle_step_failure(current_plan, step, e)
                        plan_state["plan"] = current_plan
                        failed_step = current_plan.get_step_by_id(step_id)
                        return step_id, failed_step
                    return step_id, None

        while not plan_state["plan"].is_complete:
            current_plan = plan_state["plan"]
            # Check abort signal
            if abort_signal and abort_signal.is_set():
                logger.info("Abort signal set, stopping parallel execution")
                # Mark plan as cancelled
                plan_state["plan"] = current_plan.mark_cancelled()
                break

            # Get ready steps
            ready_steps = self._get_ready_steps(current_plan)

            if not ready_steps:
                # No steps ready - check if we're done
                pending_steps = [
                    s for s in current_plan.steps if s.status == ExecutionStepStatus.PENDING
                ]
                if not pending_steps:
                    break
                # If there are pending steps but none ready, we might be stuck
                # waiting on a failed dependency
                if current_plan.failed_steps:
                    logger.warning("No ready steps but failed steps detected, stopping execution")
                    break
                # Wait a bit and check again
                await asyncio.sleep(0.01)
                continue

            # Execute all ready steps in parallel (Semaphore will limit concurrency)
            tasks = [execute_with_limit(step_id) for step_id in ready_steps]

            if tasks:
                # Execute all tasks in parallel
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Update plan state based on results
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Task failed with exception: {result}")
                        continue

                    if isinstance(result, tuple):
                        step_id, updated_step = result
                        if updated_step:
                            # Plan is already updated inside execute_with_limit
                            pass
                        else:
                            # Step was skipped or aborted
                            pass

        return plan_state["plan"]

    async def _execute_and_update_step(
        self,
        plan: ExecutionPlan,
        step_id: str,
        step: ExecutionStep,
    ) -> str:
        """
        Execute a step and return its result.

        Helper for parallel execution where we need to return results.

        Args:
            plan: The execution plan
            step_id: ID of the step to execute
            step: The step to execute

        Returns:
            The step execution result

        Raises:
            Exception: If step execution fails
        """
        return await self._execute_step(step, plan.conversation_id)
