"""GeneratePlanExecutionUseCase for unified plan execution generation.

This use case generates a PlanExecution from a user query, optionally using
an existing Plan document for context (Plan Mode).
"""

import uuid
from typing import Any, Optional

from src.domain.model.agent.plan_execution import (
    ExecutionMode,
    ExecutionStatus,
    ExecutionStep,
    PlanExecution,
    StepStatus,
)
from src.domain.ports.repositories.plan_execution_repository import (
    PlanExecutionRepository,
)
from src.infrastructure.agent.planning.plan_generator import PlanGenerator


class GeneratePlanExecutionUseCase:
    """Use case for generating a plan execution.

    This use case coordinates the generation of a unified plan execution,
    either for multi-level thinking or Plan Mode execution.
    """

    def __init__(
        self,
        plan_execution_repository: PlanExecutionRepository,
        plan_generator: PlanGenerator,
    ):
        """Initialize the use case.

        Args:
            plan_execution_repository: Repository for plan execution persistence
            plan_generator: Generator for creating execution plans
        """
        self._repository = plan_execution_repository
        self._generator = plan_generator

    async def execute(
        self,
        conversation_id: str,
        query: str,
        plan_id: Optional[str] = None,
        context: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL,
        reflection_enabled: bool = True,
        max_reflection_cycles: int = 3,
        workflow_pattern_id: Optional[str] = None,
    ) -> PlanExecution:
        """Generate and save a plan execution.

        Args:
            conversation_id: The conversation ID
            query: User's query/request
            plan_id: Optional plan document ID (for Plan Mode)
            context: Optional context for plan generation
            execution_mode: Execution mode (sequential/parallel)
            reflection_enabled: Whether to enable reflection
            max_reflection_cycles: Maximum number of reflection cycles
            workflow_pattern_id: Optional workflow pattern ID

        Returns:
            The generated and saved plan execution
        """
        # Generate execution plan using the generator
        generated_plan = await self._generator.generate_plan(
            conversation_id=conversation_id,
            query=query,
            context=context,
            reflection_enabled=reflection_enabled,
            max_reflection_cycles=max_reflection_cycles,
        )

        # Convert generated ExecutionPlan steps to unified ExecutionStep format
        steps: list[ExecutionStep] = []
        for i, step in enumerate(generated_plan.steps):
            execution_step = ExecutionStep(
                step_id=step.step_id or f"step-{uuid.uuid4().hex[:8]}",
                step_number=i + 1,
                description=step.description,
                thought_prompt=f"Execute step: {step.description}",
                expected_output="Step execution result",
                tool_name=step.tool_name,
                tool_input=step.tool_input,
                dependencies=step.dependencies,
                status=StepStatus(step.status.value),
            )
            steps.append(execution_step)

        # Create unified plan execution
        plan_execution = PlanExecution(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            plan_id=plan_id,
            steps=steps,
            status=ExecutionStatus.PENDING,
            execution_mode=execution_mode,
            reflection_enabled=reflection_enabled,
            max_reflection_cycles=max_reflection_cycles,
            current_reflection_cycle=0,
            workflow_pattern_id=workflow_pattern_id,
            metadata={
                "original_query": query,
                "generated_from": "plan_generator",
            },
        )

        # Save to repository
        return await self._repository.save(plan_execution)
