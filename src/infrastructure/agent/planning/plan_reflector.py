"""
Plan Reflector for Plan Mode.

This module provides the PlanReflector class that uses LLM to analyze
execution results and suggest adjustments.
"""

import json
import re
from typing import Any

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionPlanStatus,
)
from src.domain.model.agent.reflection_result import (
    ReflectionResult,
    ReflectionAssessment,
    StepAdjustment,
    AdjustmentType,
)
from src.infrastructure.agent.planning.prompts import (
    PLAN_REFLECTION_SYSTEM_PROMPT,
    PLAN_REFLECTION_USER_PROMPT_TEMPLATE,
)


class ReflectionError(Exception):
    """Raised when reflection fails."""

    def __init__(self, message: str, cause: BaseException | None = None):
        super().__init__(message)
        self.cause = cause


class PlanReflector:
    """
    Analyzes plan execution and suggests adjustments using LLM.

    The PlanReflector evaluates execution progress and determines if
    adjustments are needed to achieve the original goal.

    Attributes:
        llm_client: Async LLM client for reflection
        max_retries: Maximum retries for LLM calls
        timeout_ms: Timeout for LLM calls in milliseconds
    """

    def __init__(
        self,
        llm_client: Any,
        max_retries: int = 3,
        timeout_ms: int = 30000,
    ) -> None:
        """
        Initialize the PlanReflector.

        Args:
            llm_client: Async LLM client with generate() method
            max_retries: Maximum retries for LLM calls
            timeout_ms: Timeout for LLM calls
        """
        self.llm_client = llm_client
        self.max_retries = max_retries
        self.timeout_ms = timeout_ms

    async def reflect(
        self,
        plan: ExecutionPlan,
    ) -> ReflectionResult:
        """
        Analyze execution and generate reflection result.

        Uses LLM to evaluate progress and suggest adjustments.
        Falls back to safe defaults on error.

        Args:
            plan: The execution plan to reflect on

        Returns:
            ReflectionResult with assessment and any adjustments
        """
        try:
            system_prompt = PLAN_REFLECTION_SYSTEM_PROMPT
            user_prompt = self._build_user_prompt(plan)

            response = await self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            reflection_data = self._parse_llm_response(response)
            return self._create_reflection_from_data(reflection_data, plan)

        except Exception:
            # On any error, return a safe default reflection
            return self._create_default_reflection(plan)

    def _build_user_prompt(
        self,
        plan: ExecutionPlan,
    ) -> str:
        """
        Build the user prompt for reflection.

        Args:
            plan: The execution plan

        Returns:
            Formatted user prompt string
        """
        total_steps = len(plan.steps)
        completed_count = len(plan.completed_steps)
        failed_count = len(plan.failed_steps)

        # Build step results section
        step_results = []
        for step in plan.steps:
            status_str = step.status.value
            result_str = ""
            if step.result:
                result_str = f" - Result: {step.result[:200]}..." if len(step.result) > 200 else f" - Result: {step.result}"
            elif step.error:
                result_str = f" - Error: {step.error}"

            step_results.append(f"- {step.step_id} ({status_str}): {step.description}{result_str}")

        step_results_str = "\n".join(step_results) if step_results else "No steps"

        # Current status
        status_str = plan.status.value
        current_status = f"Plan status: {status_str}"

        return PLAN_REFLECTION_USER_PROMPT_TEMPLATE.format(
            user_query=plan.user_query,
            completed_count=completed_count,
            total_count=total_steps,
            failed_count=failed_count,
            step_results=step_results_str,
            current_status=current_status,
        )

    def _parse_llm_response(self, response: str) -> dict[str, Any]:
        """
        Parse LLM response to extract reflection data.

        Handles both plain JSON and markdown-wrapped JSON.

        Args:
            response: Raw LLM response string

        Returns:
            Parsed dictionary with reflection data
        """
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse reflection JSON: {e}") from e

        # Default missing required fields
        if "overall_assessment" not in data:
            data["overall_assessment"] = "on_track"
        if "step_adjustments" not in data:
            data["step_adjustments"] = []
        if "confidence" not in data:
            data["confidence"] = None
        if "reasoning" not in data:
            data["reasoning"] = "No reasoning provided"
        if "alternative_suggestions" not in data:
            data["alternative_suggestions"] = []

        return data

    def _create_reflection_from_data(
        self,
        data: dict[str, Any],
        plan: ExecutionPlan,
    ) -> ReflectionResult:
        """
        Create ReflectionResult from parsed LLM data.

        Args:
            data: Parsed reflection data
            plan: The execution plan

        Returns:
            ReflectionResult instance
        """
        assessment_str = data.get("overall_assessment", "on_track")

        # Map assessment string to enum
        assessment_map = {
            "on_track": ReflectionAssessment.ON_TRACK,
            "needs_adjustment": ReflectionAssessment.NEEDS_ADJUSTMENT,
            "off_track": ReflectionAssessment.OFF_TRACK,
            "complete": ReflectionAssessment.COMPLETE,
            "critical_failure": ReflectionAssessment.FAILED,
            "failed": ReflectionAssessment.FAILED,
        }
        assessment = assessment_map.get(assessment_str, ReflectionAssessment.ON_TRACK)

        # Parse adjustments
        adjustments = []
        for adj_data in data.get("step_adjustments", []):
            adjustment = self._parse_adjustment(adj_data)
            if adjustment:
                adjustments.append(adjustment)

        # Create reflection based on assessment
        if assessment == ReflectionAssessment.COMPLETE:
            return ReflectionResult.complete(
                reasoning=data.get("reasoning", ""),
                final_summary=data.get("summary"),
            )
        elif assessment == ReflectionAssessment.FAILED:
            return ReflectionResult.failed(
                reasoning=data.get("reasoning", ""),
                error_type=data.get("error_type"),
            )
        elif assessment == ReflectionAssessment.OFF_TRACK:
            return ReflectionResult.off_track(
                reasoning=data.get("reasoning", ""),
                suggested_next_steps=data.get("alternative_suggestions"),
            )
        elif assessment == ReflectionAssessment.NEEDS_ADJUSTMENT and adjustments:
            return ReflectionResult.needs_adjustment(
                reasoning=data.get("reasoning", ""),
                adjustments=adjustments,
                confidence=data.get("confidence"),
            )
        else:
            # Default to on_track
            return ReflectionResult.on_track(
                reasoning=data.get("reasoning", ""),
                confidence=data.get("confidence"),
            )

    def _parse_adjustment(self, adj_data: dict[str, Any]) -> StepAdjustment | None:
        """
        Parse adjustment data from LLM response.

        Args:
            adj_data: Raw adjustment dictionary

        Returns:
            StepAdjustment instance or None if invalid
        """
        step_id = adj_data.get("step_id")
        action_str = adj_data.get("action", "modify")

        if not step_id:
            return None

        # Map action string to enum
        action_map = {
            "modify": AdjustmentType.MODIFY,
            "retry": AdjustmentType.RETRY,
            "skip": AdjustmentType.SKIP,
            "add_before": AdjustmentType.ADD_BEFORE,
            "add_after": AdjustmentType.ADD_AFTER,
            "replace": AdjustmentType.REPLACE,
        }
        adjustment_type = action_map.get(action_str)

        if not adjustment_type:
            return None

        return StepAdjustment(
            step_id=step_id,
            adjustment_type=adjustment_type,
            reason=adj_data.get("reason", ""),
            new_tool_input=adj_data.get("new_input"),
            new_tool_name=adj_data.get("new_tool_name"),
            new_step=adj_data.get("new_step"),
        )

    def _create_default_reflection(
        self,
        plan: ExecutionPlan,
    ) -> ReflectionResult:
        """
        Create a default reflection when LLM fails.

        Args:
            plan: The execution plan

        Returns:
            Safe default ReflectionResult
        """
        if plan.status == ExecutionPlanStatus.COMPLETED:
            return ReflectionResult.complete(
                reasoning="Plan completed successfully",
                final_summary="All steps completed",
            )
        elif plan.status == ExecutionPlanStatus.FAILED:
            return ReflectionResult.failed(
                reasoning=plan.error or "Plan execution failed",
                error_type="execution_failure",
            )
        elif plan.failed_steps:
            return ReflectionResult.needs_adjustment(
                reasoning=f"Some steps failed: {', '.join(plan.failed_steps)}",
                adjustments=[],
                confidence=0.5,
            )
        else:
            return ReflectionResult.on_track(
                reasoning="Unable to perform reflection, continuing execution",
            )
