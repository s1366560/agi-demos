"""
Plan Mode Orchestrator for Plan Mode.

This module provides the PlanModeOrchestrator class that coordinates
the complete Plan Mode workflow: plan -> execute -> reflect -> adjust -> repeat.
"""

import asyncio
from typing import Any

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionPlanStatus,
)
from src.domain.model.agent.reflection_result import (
    ReflectionAssessment,
    ReflectionResult,
)
from src.infrastructure.agent.planning.plan_adjuster import PlanAdjuster
from src.infrastructure.agent.planning.plan_executor import PlanExecutor
from src.infrastructure.agent.planning.plan_generator import PlanGenerator
from src.infrastructure.agent.planning.plan_reflector import PlanReflector


class OrchestratorError(Exception):
    """Raised when orchestrator workflow fails."""

    def __init__(self, message: str, cause: BaseException | None = None):
        super().__init__(message)
        self.cause = cause


class PlanModeOrchestrator:
    """
    Orchestrates the complete Plan Mode workflow.

    The PlanModeOrchestrator coordinates:
    1. Plan generation (if needed)
    2. Plan execution
    3. Reflection on results
    4. Adjustment application (if needed)
    5. Repeat until terminal state or max cycles

    Attributes:
        plan_generator: Generates execution plans
        plan_executor: Executes plans
        plan_reflector: Reflects on execution results
        plan_adjuster: Applies adjustments to plans
        event_emitter: Callback for emitting SSE events
        max_reflection_cycles: Maximum number of reflection cycles
    """

    def __init__(
        self,
        plan_generator: PlanGenerator,
        plan_executor: PlanExecutor,
        plan_reflector: PlanReflector,
        plan_adjuster: PlanAdjuster,
        event_emitter: Any,
        max_reflection_cycles: int = 3,
    ) -> None:
        """
        Initialize the PlanModeOrchestrator.

        Args:
            plan_generator: PlanGenerator instance
            plan_executor: PlanExecutor instance
            plan_reflector: PlanReflector instance
            plan_adjuster: PlanAdjuster instance
            event_emitter: Callback for emitting SSE events
            max_reflection_cycles: Maximum reflection cycles
        """
        self.plan_generator = plan_generator
        self.plan_executor = plan_executor
        self.plan_reflector = plan_reflector
        self.plan_adjuster = plan_adjuster
        self.event_emitter = event_emitter
        self.max_reflection_cycles = max_reflection_cycles

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        abort_signal: asyncio.Event | None = None,
    ) -> ExecutionPlan:
        """
        Execute the plan with reflection and adjustment.

        Args:
            plan: The execution plan to execute
            abort_signal: Optional signal for aborting execution

        Returns:
            Final execution plan after all cycles

        Raises:
            OrchestratorError: If critical failure occurs
        """
        current_plan = plan
        reflection_cycle = 0
        abort_signal = abort_signal or asyncio.Event()

        # Main workflow loop
        while True:
            # Check abort before execution
            if abort_signal.is_set():
                current_plan = current_plan.mark_cancelled()
                break

            # Execute the plan
            try:
                current_plan = await self.plan_executor.execute_plan(
                    plan=current_plan,
                    abort_signal=abort_signal,
                )
            except Exception as e:
                # Executor threw an exception
                raise OrchestratorError(f"Plan execution failed: {e}") from e

            # Check abort after execution
            if abort_signal.is_set():
                current_plan = current_plan.mark_cancelled()
                break

            # Skip reflection if disabled
            if not current_plan.reflection_enabled:
                break

            # Check if plan is in terminal state
            if current_plan.status in (
                ExecutionPlanStatus.COMPLETED,
                ExecutionPlanStatus.FAILED,
                ExecutionPlanStatus.CANCELLED,
            ):
                break

            # Reflect on execution
            try:
                reflection = await self.plan_reflector.reflect(current_plan)
            except Exception:
                # Reflector failed - create safe default
                reflection = self._create_safe_reflection(current_plan)

            # Emit reflection event
            self._emit_reflection_event(current_plan, reflection)

            # Check for terminal states
            if reflection.is_terminal:
                if reflection.assessment == ReflectionAssessment.COMPLETE:
                    current_plan = current_plan.mark_completed()
                elif reflection.assessment == ReflectionAssessment.FAILED:
                    current_plan = current_plan.mark_failed(reflection.reasoning)
                break

            # Check if adjustments are needed
            if reflection.has_adjustments():
                # Apply adjustments (sync method)
                try:
                    current_plan = self.plan_adjuster.apply_adjustments(
                        plan=current_plan,
                        adjustments=reflection.adjustments,
                    )
                except Exception as e:
                    raise OrchestratorError(f"Failed to apply adjustments: {e}") from e

                # Emit adjustment event
                self._emit_adjustment_event(current_plan, reflection)

            # Check max reflection cycles
            reflection_cycle += 1
            if reflection_cycle >= self.max_reflection_cycles:
                # Max cycles reached, stop with current state
                break

            # If on_track without adjustments, we're done
            if reflection.assessment == ReflectionAssessment.ON_TRACK:
                if not reflection.has_adjustments():
                    break

            # If off_track but no adjustments provided, stop
            if reflection.assessment == ReflectionAssessment.OFF_TRACK:
                if not reflection.has_adjustments():
                    current_plan = current_plan.mark_failed(reflection.reasoning)
                    break

        return current_plan

    def _create_safe_reflection(
        self,
        plan: ExecutionPlan,
    ) -> ReflectionResult:
        """
        Create a safe default reflection when reflector fails.

        Args:
            plan: The execution plan

        Returns:
            Safe default ReflectionResult
        """
        if plan.status == ExecutionPlanStatus.COMPLETED:
            return ReflectionResult.complete(
                reasoning="Plan completed",
                final_summary="Execution finished",
            )
        elif plan.status == ExecutionPlanStatus.FAILED:
            return ReflectionResult.failed(
                reasoning=plan.error or "Plan failed",
            )
        else:
            return ReflectionResult.on_track(
                reasoning="Continuing execution",
            )

    def _emit_reflection_event(
        self,
        plan: ExecutionPlan,
        reflection: ReflectionResult,
    ) -> None:
        """Emit a reflection completion event."""
        if self.event_emitter:
            self.event_emitter({
                "type": "REFLECTION_COMPLETE",
                "data": {
                    "plan_id": plan.id,
                    "assessment": reflection.assessment.value,
                    "reasoning": reflection.reasoning,
                    "has_adjustments": reflection.has_adjustments(),
                    "adjustment_count": len(reflection.adjustments),
                },
            })

    def _emit_adjustment_event(
        self,
        plan: ExecutionPlan,
        reflection: ReflectionResult,
    ) -> None:
        """Emit an adjustment applied event."""
        if self.event_emitter:
            self.event_emitter({
                "type": "ADJUSTMENT_APPLIED",
                "data": {
                    "plan_id": plan.id,
                    "adjustment_count": len(reflection.adjustments),
                    "adjustments": [a.to_dict() for a in reflection.adjustments],
                },
            })
