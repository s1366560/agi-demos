"""
Plan Adjuster for Plan Mode.

This module provides the PlanAdjuster class that applies
adjustments to execution plans.
"""

import uuid
from dataclasses import replace
from typing import Any

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
)
from src.domain.model.agent.reflection_result import (
    StepAdjustment,
    AdjustmentType,
)


class AdjustmentError(Exception):
    """Raised when adjustment application fails."""

    def __init__(self, message: str, step_id: str | None = None):
        super().__init__(message)
        self.step_id = step_id


class PlanAdjuster:
    """
    Applies adjustments to execution plans.

    The PlanAdjuster modifies execution plans based on reflection
    results, ensuring immutability by returning new plan instances.

    Attributes:
        None (stateless utility)
    """

    def __init__(self) -> None:
        """Initialize the PlanAdjuster."""
        pass

    def apply_adjustment(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply a single adjustment to the plan.

        Args:
            plan: The execution plan to adjust
            adjustment: The adjustment to apply

        Returns:
            New ExecutionPlan with adjustment applied

        Raises:
            AdjustmentError: If step not found or adjustment invalid
            ValueError: If adjustment type is unknown
        """
        adjustment_type = adjustment.adjustment_type

        if adjustment_type == AdjustmentType.MODIFY:
            return self._apply_modify(plan, adjustment)
        elif adjustment_type == AdjustmentType.RETRY:
            return self._apply_retry(plan, adjustment)
        elif adjustment_type == AdjustmentType.SKIP:
            return self._apply_skip(plan, adjustment)
        elif adjustment_type == AdjustmentType.ADD_BEFORE:
            return self._apply_add_before(plan, adjustment)
        elif adjustment_type == AdjustmentType.ADD_AFTER:
            return self._apply_add_after(plan, adjustment)
        elif adjustment_type == AdjustmentType.REPLACE:
            return self._apply_replace(plan, adjustment)
        else:
            raise ValueError(f"Unknown adjustment type: {adjustment_type}")

    def apply_adjustments(
        self,
        plan: ExecutionPlan,
        adjustments: list[StepAdjustment],
    ) -> ExecutionPlan:
        """
        Apply multiple adjustments to the plan.

        Adjustments are applied in order.

        Args:
            plan: The execution plan to adjust
            adjustments: List of adjustments to apply

        Returns:
            New ExecutionPlan with all adjustments applied
        """
        updated_plan = plan
        for adjustment in adjustments:
            updated_plan = self.apply_adjustment(updated_plan, adjustment)

        return updated_plan

    def _apply_modify(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply a MODIFY adjustment.

        Updates the step's tool input while keeping other properties.
        """
        step = plan.get_step_by_id(adjustment.step_id)
        if step is None:
            raise AdjustmentError(f"Step not found: {adjustment.step_id}")

        new_tool_input = adjustment.new_tool_input or step.tool_input

        updated_step = replace(
            step,
            tool_input=new_tool_input,
        )

        return plan.update_step(updated_step)

    def _apply_retry(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply a RETRY adjustment.

        Resets the step to PENDING status with new input parameters.
        Also removes from failed_steps.
        """
        step = plan.get_step_by_id(adjustment.step_id)
        if step is None:
            raise AdjustmentError(f"Step not found: {adjustment.step_id}")

        new_tool_input = adjustment.new_tool_input or step.tool_input

        # Reset step to PENDING
        updated_step = replace(
            step,
            status=ExecutionStepStatus.PENDING,
            tool_input=new_tool_input,
            result=None,
            error=None,
            started_at=None,
            completed_at=None,
        )

        # Update step and remove from failed_steps
        new_plan = plan.update_step(updated_step)
        new_failed = [s for s in new_plan.failed_steps if s != adjustment.step_id]

        return replace(new_plan, failed_steps=new_failed)

    def _apply_skip(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply a SKIP adjustment.

        Marks the step as skipped and updates dependent steps.
        """
        step = plan.get_step_by_id(adjustment.step_id)
        if step is None:
            raise AdjustmentError(f"Step not found: {adjustment.step_id}")

        # Mark step as skipped
        updated_step = step.mark_skipped(adjustment.reason)
        new_plan = plan.update_step(updated_step)

        # Update dependencies of other steps
        # Remove the skipped step from other steps' dependencies
        new_steps = []
        for s in new_plan.steps:
            if s.step_id != adjustment.step_id:
                new_deps = [d for d in s.dependencies if d != adjustment.step_id]
                if new_deps != list(s.dependencies):
                    new_steps.append(replace(s, dependencies=new_deps))
                else:
                    new_steps.append(s)
            else:
                new_steps.append(updated_step)

        return replace(new_plan, steps=new_steps)

    def _apply_add_before(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply an ADD_BEFORE adjustment.

        Adds a new step before the target step.
        The target step is made to depend on the new step.
        """
        step = plan.get_step_by_id(adjustment.step_id)
        if step is None:
            raise AdjustmentError(f"Step not found: {adjustment.step_id}")

        new_step = adjustment.new_step
        if new_step is None:
            raise AdjustmentError(
                f"new_step required for ADD_BEFORE adjustment",
                step_id=adjustment.step_id,
            )

        # Insert new step before target
        new_steps = []
        for s in plan.steps:
            if s.step_id == adjustment.step_id:
                # Add new step first
                new_steps.append(new_step)
                # Then add target step, updated to depend on new step
                new_deps = list(s.dependencies)
                if new_step.step_id not in new_deps:
                    new_deps.insert(0, new_step.step_id)
                new_steps.append(replace(s, dependencies=new_deps))
            else:
                new_steps.append(s)

        return replace(plan, steps=new_steps)

    def _apply_add_after(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply an ADD_AFTER adjustment.

        Adds a new step after the target step.
        The new step depends on the target step.
        """
        step = plan.get_step_by_id(adjustment.step_id)
        if step is None:
            raise AdjustmentError(f"Step not found: {adjustment.step_id}")

        new_step = adjustment.new_step
        if new_step is None:
            raise AdjustmentError(
                f"new_step required for ADD_AFTER adjustment",
                step_id=adjustment.step_id,
            )

        # Make new step depend on target
        new_step_with_deps = replace(
            new_step,
            dependencies=[adjustment.step_id],
        )

        # Insert new step after target
        new_steps = []
        for s in plan.steps:
            new_steps.append(s)
            if s.step_id == adjustment.step_id:
                new_steps.append(new_step_with_deps)

        return replace(plan, steps=new_steps)

    def _apply_replace(
        self,
        plan: ExecutionPlan,
        adjustment: StepAdjustment,
    ) -> ExecutionPlan:
        """
        Apply a REPLACE adjustment.

        Replaces a step with a new step entirely.
        Maintains dependencies from other steps.
        """
        step = plan.get_step_by_id(adjustment.step_id)
        if step is None:
            raise AdjustmentError(f"Step not found: {adjustment.step_id}")

        new_step = adjustment.new_step
        if new_step is None:
            raise AdjustmentError(
                f"new_step required for REPLACE adjustment",
                step_id=adjustment.step_id,
            )

        # Ensure new step has same ID
        if new_step.step_id != adjustment.step_id:
            new_step = replace(new_step, step_id=adjustment.step_id)

        # Replace the step
        new_steps = []
        for s in plan.steps:
            if s.step_id == adjustment.step_id:
                new_steps.append(new_step)
            else:
                new_steps.append(s)

        new_plan = replace(plan, steps=new_steps)

        # Remove from failed_steps if present
        if adjustment.step_id in new_plan.failed_steps:
            new_failed = [s for s in new_plan.failed_steps if s != adjustment.step_id]
            new_plan = replace(new_plan, failed_steps=new_failed)

        return new_plan
