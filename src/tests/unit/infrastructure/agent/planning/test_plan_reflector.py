"""
Unit tests for PlanReflector.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

from unittest.mock import AsyncMock, Mock
from typing import Any

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionPlanStatus,
)
from src.domain.model.agent.reflection_result import (
    ReflectionResult,
    ReflectionAssessment,
    StepAdjustment,
    AdjustmentType,
)
from src.infrastructure.agent.planning.plan_reflector import PlanReflector


class TestPlanReflectorInit:
    """Tests for PlanReflector initialization."""

    def test_init_with_llm_client(self) -> None:
        """Test creating PlanReflector with LLM client."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock()

        reflector = PlanReflector(llm_client=mock_llm)

        assert reflector.llm_client == mock_llm

    def test_init_with_default_params(self) -> None:
        """Test PlanReflector with default parameters."""
        mock_llm = AsyncMock()

        reflector = PlanReflector(llm_client=mock_llm)

        assert reflector.max_retries == 3
        assert reflector.timeout_ms == 30000


class TestReflectOnExecution:
    """Tests for the main reflect method."""

    @pytest.mark.asyncio
    async def test_reflect_on_track_execution(self) -> None:
        """Test reflection when execution is on track."""
        # Setup LLM response for on_track assessment
        response = '''```json
{
    "overall_assessment": "on_track",
    "summary": "All steps completed successfully",
    "recommended_action": "continue",
    "step_adjustments": [],
    "confidence": 0.9,
    "reasoning": "The plan is progressing as expected",
    "alternative_suggestions": []
}
```'''

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=response)

        reflector = PlanReflector(llm_client=mock_llm)

        # Create a plan with some completed steps
        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search memory",
                tool_name="MemorySearch",
                tool_input={"query": "Python"},
                status=ExecutionStepStatus.COMPLETED,
                result="Found 5 memories about Python",
            ),
            ExecutionStep(
                step_id="step-2",
                description="Summarize results",
                tool_name="Summary",
                tool_input={},
                status=ExecutionStepStatus.PENDING,
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Summarize Python knowledge",
            steps=steps,
            completed_steps=["step-1"],
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.ON_TRACK
        assert not result.has_adjustments()
        assert result.confidence == 0.9
        assert "progressing" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_reflect_with_adjustments_needed(self) -> None:
        """Test reflection when adjustments are needed."""
        response = '''```json
{
    "overall_assessment": "needs_adjustment",
    "summary": "Step failed, needs retry with different parameters",
    "recommended_action": "adjust",
    "step_adjustments": [
        {
            "step_id": "step-1",
            "action": "retry",
            "new_input": {"query": "Python programming", "limit": 10},
            "new_description": "Retry search with more specific query",
            "reason": "Previous search was too broad"
        }
    ],
    "confidence": 0.8,
    "reasoning": "The search failed due to timeout",
    "alternative_suggestions": ["Try entity lookup instead"]
}
```'''

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=response)

        reflector = PlanReflector(llm_client=mock_llm)

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search memory",
                tool_name="MemorySearch",
                tool_input={"query": "Python"},
                status=ExecutionStepStatus.FAILED,
                error="Timeout after 30s",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Search Python knowledge",
            steps=steps,
            failed_steps=["step-1"],
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.NEEDS_ADJUSTMENT
        assert result.has_adjustments()
        assert len(result.adjustments) == 1
        assert result.adjustments[0].adjustment_type == AdjustmentType.RETRY
        assert result.adjustments[0].step_id == "step-1"

    @pytest.mark.asyncio
    async def test_reflect_complete(self) -> None:
        """Test reflection when plan is complete."""
        response = '''```json
{
    "overall_assessment": "complete",
    "summary": "Goal has been achieved",
    "recommended_action": "complete",
    "step_adjustments": [],
    "confidence": 1.0,
    "reasoning": "All steps completed and goal met",
    "alternative_suggestions": []
}
```'''

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=response)

        reflector = PlanReflector(llm_client=mock_llm)

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search memory",
                tool_name="MemorySearch",
                status=ExecutionStepStatus.COMPLETED,
                result="Found relevant memories",
            ),
            ExecutionStep(
                step_id="step-2",
                description="Summarize",
                tool_name="Summary",
                status=ExecutionStepStatus.COMPLETED,
                result="Summary complete",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Summarize Python knowledge",
            steps=steps,
            completed_steps=["step-1", "step-2"],
            status=ExecutionPlanStatus.COMPLETED,
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.COMPLETE
        assert result.is_terminal
        assert result.final_summary is not None

    @pytest.mark.asyncio
    async def test_reflect_failed(self) -> None:
        """Test reflection when plan has failed."""
        response = '''```json
{
    "overall_assessment": "critical_failure",
    "summary": "Unable to recover from failures",
    "recommended_action": "rollback",
    "step_adjustments": [],
    "confidence": 0.5,
    "reasoning": "Multiple critical steps failed with no recovery options",
    "alternative_suggestions": []
}
```'''

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=response)

        reflector = PlanReflector(llm_client=mock_llm)

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search memory",
                tool_name="MemorySearch",
                status=ExecutionStepStatus.FAILED,
                error="Service unavailable",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Search knowledge",
            steps=steps,
            failed_steps=["step-1"],
            status=ExecutionPlanStatus.FAILED,
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.FAILED
        assert result.is_terminal

    @pytest.mark.asyncio
    async def test_reflect_with_off_track_assessment(self) -> None:
        """Test reflection when execution is off track."""
        response = '''```json
{
    "overall_assessment": "off_track",
    "summary": "Plan is not heading toward the goal",
    "recommended_action": "adjust",
    "step_adjustments": [
        {
            "step_id": "step-2",
            "action": "skip",
            "new_input": {},
            "new_description": "",
            "reason": "This step is no longer relevant"
        }
    ],
    "confidence": 0.7,
    "reasoning": "The search results don't match user intent",
    "alternative_suggestions": ["Clarify user intent", "Try different search terms"]
}
```'''

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=response)

        reflector = PlanReflector(llm_client=mock_llm)

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search memory",
                tool_name="MemorySearch",
                status=ExecutionStepStatus.COMPLETED,
                result="Irrelevant results",
            ),
            ExecutionStep(
                step_id="step-2",
                description="Summarize",
                tool_name="Summary",
                status=ExecutionStepStatus.PENDING,
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Find specific information",
            steps=steps,
            completed_steps=["step-1"],
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.OFF_TRACK
        assert result.suggested_next_steps is not None
        assert len(result.suggested_next_steps) == 2


class TestReflectWithLLMError:
    """Tests for reflection error handling."""

    @pytest.mark.asyncio
    async def test_reflect_llm_error_returns_default_on_track(self) -> None:
        """Test that LLM error returns a safe default reflection."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM unavailable"))

        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=[],
        )

        result = await reflector.reflect(plan)

        # Should return a safe default
        assert result.assessment == ReflectionAssessment.ON_TRACK
        assert "error" in result.reasoning.lower() or "unable" in result.reasoning.lower()

    @pytest.mark.asyncio
    async def test_reflect_invalid_json_returns_default(self) -> None:
        """Test that invalid JSON returns a safe default reflection."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="This is not valid JSON")

        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=[],
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.ON_TRACK

    @pytest.mark.asyncio
    async def test_reflect_missing_required_fields_returns_default(self) -> None:
        """Test that missing required fields returns a safe default."""
        response = '''```json
{
    "summary": "Missing assessment field"
}
```'''

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value=response)

        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test query",
            steps=[],
        )

        result = await reflector.reflect(plan)

        assert result.assessment == ReflectionAssessment.ON_TRACK


class TestBuildUserPrompt:
    """Tests for user prompt building."""

    def test_build_user_prompt_with_completed_steps(self) -> None:
        """Test building prompt with completed steps."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search",
                tool_name="MemorySearch",
                status=ExecutionStepStatus.COMPLETED,
                result="Found 10 results",
            ),
            ExecutionStep(
                step_id="step-2",
                description="Summarize",
                tool_name="Summary",
                status=ExecutionStepStatus.PENDING,
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Summarize Python",
            steps=steps,
            completed_steps=["step-1"],
        )

        prompt = reflector._build_user_prompt(plan)

        assert "Summarize Python" in prompt
        assert "Completed Steps: 1/2" in prompt
        assert "Found 10 results" in prompt

    def test_build_user_prompt_with_failed_steps(self) -> None:
        """Test building prompt with failed steps."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search",
                tool_name="MemorySearch",
                status=ExecutionStepStatus.FAILED,
                error="Timeout",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Search knowledge",
            steps=steps,
            failed_steps=["step-1"],
        )

        prompt = reflector._build_user_prompt(plan)

        assert "Failed Steps: 1" in prompt
        assert "Timeout" in prompt

    def test_build_user_prompt_empty_plan(self) -> None:
        """Test building prompt for empty plan."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        prompt = reflector._build_user_prompt(plan)

        assert "Test" in prompt
        assert "Completed Steps: 0/0" in prompt


class TestParseLLMResponse:
    """Tests for LLM response parsing."""

    def test_parse_valid_on_track_response(self) -> None:
        """Test parsing valid on_track response."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        response = '''```json
{
    "overall_assessment": "on_track",
    "summary": "Good progress",
    "recommended_action": "continue",
    "step_adjustments": [],
    "confidence": 0.9,
    "reasoning": "All good",
    "alternative_suggestions": []
}
```'''

        result = reflector._parse_llm_response(response)

        assert result["overall_assessment"] == "on_track"
        assert result["confidence"] == 0.9

    def test_parse_response_with_markdown(self) -> None:
        """Test parsing response wrapped in markdown."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        response = '''Here's my analysis:

```json
{
    "overall_assessment": "needs_adjustment",
    "summary": "Need to adjust",
    "recommended_action": "adjust",
    "step_adjustments": [],
    "confidence": 0.7,
    "reasoning": "Not on track",
    "alternative_suggestions": []
}
```

That's my analysis.'''

        result = reflector._parse_llm_response(response)

        assert result["overall_assessment"] == "needs_adjustment"

    def test_parse_plain_json(self) -> None:
        """Test parsing plain JSON without markdown."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        response = '{"overall_assessment": "complete", "summary": "Done", "recommended_action": "complete", "step_adjustments": [], "confidence": 1.0, "reasoning": "Finished", "alternative_suggestions": []}'

        result = reflector._parse_llm_response(response)

        assert result["overall_assessment"] == "complete"

    def test_parse_invalid_json_raises_value_error(self) -> None:
        """Test that invalid JSON raises ValueError."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        with pytest.raises(ValueError):
            reflector._parse_llm_response("Not JSON at all")

    def test_parse_missing_overall_assessment_defaults(self) -> None:
        """Test that missing overall_assessment defaults to on_track."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        response = '{"summary": "No assessment"}'

        result = reflector._parse_llm_response(response)

        # Should default to on_track
        assert result.get("overall_assessment") == "on_track"


class TestCreateDefaultReflection:
    """Tests for default reflection creation."""

    def test_create_default_for_completed_plan(self) -> None:
        """Test default reflection for completed plan."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.COMPLETED,
        )

        result = reflector._create_default_reflection(plan)

        assert result.assessment == ReflectionAssessment.COMPLETE

    def test_create_default_for_failed_plan(self) -> None:
        """Test default reflection for failed plan."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.FAILED,
            error="Critical failure",
        )

        result = reflector._create_default_reflection(plan)

        assert result.assessment == ReflectionAssessment.FAILED

    def test_create_default_for_incomplete_plan(self) -> None:
        """Test default reflection for incomplete plan."""
        mock_llm = AsyncMock()
        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        result = reflector._create_default_reflection(plan)

        # Default to on_track for continuing execution
        assert result.assessment == ReflectionAssessment.ON_TRACK
