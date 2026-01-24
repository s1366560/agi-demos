"""PlanWork use case for multi-level thinking.

This use case handles work-level planning where the agent breaks down
complex queries into sequential steps.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.domain.llm_providers.llm_types import LLMClient
from src.domain.model.agent import PlanStatus, PlanStep, WorkPlan

if TYPE_CHECKING:
    from src.domain.ports.repositories.work_plan_repository import WorkPlanRepositoryPort

logger = logging.getLogger(__name__)


class PlanWorkUseCase:
    """Use case for generating work-level plans."""

    def __init__(
        self,
        work_plan_repository: WorkPlanRepositoryPort,
        llm: LLMClient,
    ):
        """
        Initialize the use case.

        Args:
            work_plan_repository: Repository for work plan persistence
            llm: LLM for generating plans
        """
        self._work_plan_repo = work_plan_repository
        self._llm = llm

    async def execute(
        self,
        conversation_id: str,
        user_query: str,
        available_tools: list[str],
        workflow_pattern_id: str | None = None,
    ) -> WorkPlan:
        """
        Generate a work-level plan for the user's query.

        Args:
            conversation_id: Conversation ID
            user_query: User's query
            available_tools: List of available tool names
            workflow_pattern_id: Optional pattern ID if similar plan exists

        Returns:
            Generated WorkPlan entity

        Raises:
            ValueError: If required parameters are missing
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if not user_query:
            raise ValueError("user_query is required")
        if not available_tools:
            raise ValueError("available_tools is required")

        logger.info(
            f"Generating work plan for conversation {conversation_id}, query: {user_query[:100]}..."
        )

        # If a workflow pattern is available, use it as a template
        if workflow_pattern_id:
            logger.debug(f"Using workflow pattern {workflow_pattern_id} as template")
            # TODO: Load pattern and use as template
            # For now, we'll generate from scratch

        # Generate plan using LLM
        steps = await self._generate_plan_steps(user_query, available_tools)

        # Create work plan
        work_plan = WorkPlan(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            status=PlanStatus.PLANNING,
            steps=steps,
            current_step_index=0,
            workflow_pattern_id=workflow_pattern_id,
        )

        # Save to repository
        await self._work_plan_repo.save(work_plan)

        logger.info(
            f"Generated work plan {work_plan.id} with {len(steps)} steps "
            f"for conversation {conversation_id}"
        )

        return work_plan

    async def _generate_plan_steps(
        self, user_query: str, available_tools: list[str]
    ) -> list[PlanStep]:
        """
        Generate plan steps using the LLM.

        Args:
            user_query: User's query
            available_tools: List of available tool names

        Returns:
            List of PlanStep objects
        """
        tools_desc = "\n".join(f"- {tool}" for tool in available_tools)

        system_prompt = f"""You are an AI assistant that breaks down complex queries into sequential steps.

Available tools:
{tools_desc}

Your task is to analyze the user's query and create a step-by-step plan to answer it.

For each step, provide:
1. A clear description of what the step does
2. A thought prompt for detailed reasoning during execution
3. The tools needed for this step
4. The expected output from this step
5. Any step dependencies (which steps must complete first)

Respond in JSON format:
{{
    "steps": [
        {{
            "step_number": 0,
            "description": "Search for information about...",
            "thought_prompt": "I need to find...",
            "required_tools": ["memory_search"],
            "expected_output": "Relevant memories about...",
            "dependencies": []
        }},
        {{
            "step_number": 1,
            "description": "Analyze and synthesize the findings",
            "thought_prompt": "Based on the search results...",
            "required_tools": ["summary"],
            "expected_output": "A comprehensive summary",
            "dependencies": [0]
        }}
    ]
}}
"""

        try:
            # No timeout - allow long-running LLM calls
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_query),
                ]
            )

            # Parse the response
            import json

            content = response.content.strip()

            # Try to extract JSON from markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            plan_data = json.loads(content)

            steps = []
            for step_data in plan_data.get("steps", []):
                steps.append(
                    PlanStep(
                        step_number=step_data.get("step_number", len(steps)),
                        description=step_data.get("description", ""),
                        thought_prompt=step_data.get("thought_prompt", ""),
                        required_tools=step_data.get("required_tools", []),
                        expected_output=step_data.get("expected_output", ""),
                        dependencies=step_data.get("dependencies", []),
                    )
                )

            return steps

        except Exception as e:
            logger.error(f"Error generating plan steps: {e}")
            # Return a default single-step plan as fallback
            return [
                PlanStep(
                    step_number=0,
                    description=f"Process the query: {user_query[:50]}...",
                    thought_prompt=f"How can I help with: {user_query}",
                    required_tools=available_tools[:3],  # Limit to first 3 tools
                    expected_output="A helpful response",
                    dependencies=[],
                )
            ]
