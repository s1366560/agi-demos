"""
Integration tests for Plan Mode.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

from unittest.mock import AsyncMock, Mock, patch
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
from src.infrastructure.agent.planning.plan_generator import PlanGenerator
from src.infrastructure.agent.planning.plan_executor import PlanExecutor
from src.infrastructure.agent.planning.plan_reflector import PlanReflector
from src.infrastructure.agent.planning.plan_adjuster import PlanAdjuster
from src.infrastructure.agent.planning.plan_mode_orchestrator import PlanModeOrchestrator


@pytest.mark.integration
class TestPlanModeWorkflow:
    """Integration tests for complete Plan Mode workflow."""

    @pytest.mark.asyncio
    async def test_end_to_end_simple_execution(self) -> None:
        """Test complete workflow: plan -> execute -> complete."""
        # Setup mock LLM
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value='''```json
{
    "steps": [
        {
            "description": "Search memory",
            "action_type": "tool",
            "tool_name": "MemorySearch",
            "input_data": {"query": "Python"},
            "expected_output": "Memories",
            "dependencies": [],
            "estimated_duration_ms": 1000
        }
    ]
}
```'''
        )

        # Setup mock tools
        mock_tool = Mock()
        mock_tool.name = "MemorySearch"
        mock_tool.description = "Search memory"

        # Create components
        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[mock_tool],
        )

        # Mock session processor for executor
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Search results found")

        # Mock event emitter
        events = []
        mock_event_emitter = lambda e: events.append(e)

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        reflector = PlanReflector(llm_client=mock_llm)
        adjuster = PlanAdjuster()

        # Generate plan
        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Search for Python memories",
        )

        assert plan.status == ExecutionPlanStatus.DRAFT
        assert len(plan.steps) == 1

        # Execute plan
        result = await executor.execute_plan(plan=plan, abort_signal=None)

        assert result.status == ExecutionPlanStatus.COMPLETED
        assert len(result.completed_steps) == 1

        # Verify events were emitted
        assert len(events) >= 2
        event_types = [e.get("type") for e in events]
        assert "PLAN_EXECUTION_START" in event_types
        assert "PLAN_EXECUTION_COMPLETE" in event_types

    @pytest.mark.asyncio
    async def test_workflow_with_reflection_and_adjustment(self) -> None:
        """Test complete workflow with reflection and adjustment cycle."""
        # Setup LLM for plan generation
        mock_llm = AsyncMock()

        # Plan generation response
        mock_llm.generate = AsyncMock(
            side_effect=[
                # First call: plan generation
                '''```json
{
    "steps": [
        {
            "description": "Search memory",
            "action_type": "tool",
            "tool_name": "MemorySearch",
            "input_data": {"query": "Python"},
            "expected_output": "Results",
            "dependencies": [],
            "estimated_duration_ms": 1000
        }
    ]
}
```''',
                # Second call: reflection
                '''```json
{
    "overall_assessment": "needs_adjustment",
    "summary": "Search needs more specific query",
    "recommended_action": "adjust",
    "step_adjustments": [
        {
            "step_id": "step-1",
            "action": "modify",
            "new_input": {"query": "Python programming"},
            "new_description": "Retry with specific query",
            "reason": "Query too broad"
        }
    ],
    "confidence": 0.8,
    "reasoning": "Initial search returned too many results",
    "alternative_suggestions": []
}
```''',
            ]
        )

        # Setup mock tools
        mock_tool = Mock()
        mock_tool.name = "MemorySearch"
        mock_tool.description = "Search memory"

        # Create components
        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[mock_tool],
        )

        # Mock session processor - succeeds first (to get reflection)
        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(
            return_value="Too many results - need refinement"
        )

        events = []
        mock_event_emitter = lambda e: events.append(e)

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        reflector = PlanReflector(llm_client=mock_llm)
        adjuster = PlanAdjuster()

        # Generate plan
        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Search for Python",
        )

        # Execute first time (succeeds but reflection suggests adjustment)
        plan = await executor.execute_plan(plan=plan, abort_signal=None)
        assert plan.status == ExecutionPlanStatus.COMPLETED
        assert len(plan.completed_steps) == 1

        # Get the actual step_id
        actual_step_id = plan.completed_steps[0]

        # Reflect with correct step_id
        mock_llm.generate = AsyncMock(
            return_value=f'''```json
{{
    "overall_assessment": "needs_adjustment",
    "summary": "Search needs more specific query",
    "recommended_action": "adjust",
    "step_adjustments": [
        {{
            "step_id": "{actual_step_id}",
            "action": "modify",
            "new_input": {{"query": "Python programming"}},
            "new_description": "Retry with specific query",
            "reason": "Query too broad"
        }}
    ],
    "confidence": 0.8,
    "reasoning": "Initial search returned too many results",
    "alternative_suggestions": []
}}
```'''
        )

        # Reflect (suggests adjustment despite success)
        reflection = await reflector.reflect(plan)
        assert reflection.assessment == ReflectionAssessment.NEEDS_ADJUSTMENT
        assert reflection.has_adjustments()

        # Adjust
        plan = adjuster.apply_adjustments(plan, reflection.adjustments)

        # Verify adjustment was applied
        step = plan.get_step_by_id(actual_step_id)
        if step:
            assert step.tool_input.get("query") == "Python programming"

    @pytest.mark.asyncio
    async def test_orchestrator_full_workflow(self) -> None:
        """Test orchestrator coordinating the full workflow."""
        mock_llm = AsyncMock()

        # Plan generation
        mock_llm.generate = AsyncMock(
            return_value='''```json
{
    "steps": [
        {
            "description": "Test step",
            "action_type": "tool",
            "tool_name": "TestTool",
            "input_data": {},
            "expected_output": "Done",
            "dependencies": [],
            "estimated_duration_ms": 1000
        }
    ]
}
```'''
        )

        mock_tool = Mock()
        mock_tool.name = "TestTool"
        mock_tool.description = "Test"

        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[mock_tool],
        )

        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Success")

        events = []
        mock_event_emitter = lambda e: events.append(e)

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        reflector = PlanReflector(llm_client=mock_llm)
        adjuster = PlanAdjuster()

        orchestrator = PlanModeOrchestrator(
            plan_generator=generator,
            plan_executor=executor,
            plan_reflector=reflector,
            plan_adjuster=adjuster,
            event_emitter=mock_event_emitter,
            max_reflection_cycles=3,
        )

        # Generate initial plan
        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Test query",
        )

        # Execute with orchestrator
        result = await orchestrator.execute_plan(plan=plan, abort_signal=None)

        assert result.status == ExecutionPlanStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_reflection_cycle_with_complete_assessment(self) -> None:
        """Test workflow where reflection determines completion."""
        mock_llm = AsyncMock()

        # Reflection returns complete
        mock_llm.generate = AsyncMock(
            return_value='''```json
{
    "overall_assessment": "complete",
    "summary": "Goal achieved",
    "recommended_action": "complete",
    "step_adjustments": [],
    "confidence": 1.0,
    "reasoning": "All steps completed successfully",
    "alternative_suggestions": []
}
```'''
        )

        reflector = PlanReflector(llm_client=mock_llm)

        # Plan with some completed steps
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Completed step",
                    tool_name="Tool",
                    status=ExecutionStepStatus.COMPLETED,
                    result="Done",
                ),
            ],
            completed_steps=["step-1"],
            status=ExecutionPlanStatus.EXECUTING,
        )

        reflection = await reflector.reflect(plan)

        assert reflection.assessment == ReflectionAssessment.COMPLETE
        assert reflection.is_terminal

    @pytest.mark.asyncio
    async def test_reflection_cycle_with_failed_assessment(self) -> None:
        """Test workflow where reflection determines failure."""
        mock_llm = AsyncMock()

        # Reflection returns failed
        mock_llm.generate = AsyncMock(
            return_value='''```json
{
    "overall_assessment": "critical_failure",
    "summary": "Cannot recover",
    "recommended_action": "rollback",
    "step_adjustments": [],
    "confidence": 0.5,
    "reasoning": "Multiple critical failures",
    "alternative_suggestions": []
}
```'''
        )

        reflector = PlanReflector(llm_client=mock_llm)

        # Plan with failed steps
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Failed step",
                    tool_name="Tool",
                    status=ExecutionStepStatus.FAILED,
                    error="Critical error",
                ),
            ],
            failed_steps=["step-1"],
            status=ExecutionPlanStatus.FAILED,
        )

        reflection = await reflector.reflect(plan)

        assert reflection.assessment == ReflectionAssessment.FAILED
        assert reflection.is_terminal


@pytest.mark.integration
class TestPlanModeErrorHandling:
    """Integration tests for error handling in Plan Mode."""

    @pytest.mark.asyncio
    async def test_llm_failure_during_plan_generation(self) -> None:
        """Test that LLM failure uses fallback plan generation."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM down"))

        mock_tool = Mock()
        mock_tool.name = "MemorySearch"
        mock_tool.description = "Search memory"

        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[mock_tool],
        )

        # Should still get a plan (fallback)
        plan = await generator.generate_plan(
            conversation_id="conv-1",
            query="Search for Python",
        )

        assert plan is not None
        assert isinstance(plan, ExecutionPlan)

    @pytest.mark.asyncio
    async def test_llm_failure_during_reflection(self) -> None:
        """Test that LLM failure during reflection uses safe default."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM down"))

        reflector = PlanReflector(llm_client=mock_llm)

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.EXECUTING,
        )

        # Should still get a reflection (safe default)
        reflection = await reflector.reflect(plan)

        assert reflection is not None
        assert isinstance(reflection, ReflectionResult)

    @pytest.mark.asyncio
    async def test_max_reflection_cycles_enforced(self) -> None:
        """Test that orchestrator enforces max reflection cycles."""
        mock_llm = AsyncMock()

        # Always request adjustment
        mock_llm.generate = AsyncMock(
            return_value='''```json
{
    "overall_assessment": "needs_adjustment",
    "summary": "Keep adjusting",
    "recommended_action": "adjust",
    "step_adjustment": [
        {
            "step_id": "step-1",
            "action": "modify",
            "new_input": {},
            "new_description": "",
            "reason": "Keep adjusting"
        }
    ],
    "confidence": 0.5,
    "reasoning": "Test max cycles",
    "alternative_suggestions": []
}
```'''
        )

        mock_tool = Mock()
        mock_tool.name = "TestTool"
        mock_tool.description = "Test"

        generator = PlanGenerator(
            llm_client=mock_llm,
            available_tools=[mock_tool],
        )

        mock_processor = AsyncMock()
        mock_processor.execute_tool = AsyncMock(return_value="Result")

        events = []
        mock_event_emitter = lambda e: events.append(e)

        executor = PlanExecutor(
            session_processor=mock_processor,
            event_emitter=mock_event_emitter,
        )

        reflector = PlanReflector(llm_client=mock_llm)
        adjuster = PlanAdjuster()

        orchestrator = PlanModeOrchestrator(
            plan_generator=generator,
            plan_executor=executor,
            plan_reflector=reflector,
            plan_adjuster=adjuster,
            event_emitter=mock_event_emitter,
            max_reflection_cycles=2,  # Low limit for testing
        )

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[
                ExecutionStep(
                    step_id="step-1",
                    description="Test",
                    tool_name="TestTool",
                ),
            ],
        )

        import asyncio

        # Should complete (not infinite) due to max cycles
        result = await orchestrator.execute_plan(
            plan=plan,
            abort_signal=asyncio.Event(),
        )

        # Should not have executed forever
        assert len(events) < 20  # Reasonable upper bound
