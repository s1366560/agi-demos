"""
Plan Generator for Plan Mode.

This module provides the PlanGenerator class that uses LLM to generate
structured execution plans for complex queries.
"""

import json
import re
import uuid
from types import TracebackType
from typing import Any

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
)
from src.infrastructure.agent.planning.prompts import (
    PLAN_GENERATION_SYSTEM_PROMPT,
    PLAN_GENERATION_USER_PROMPT_TEMPLATE,
)


# Type alias for exception handling
Throwable = BaseException | tuple[type[BaseException], BaseException, TracebackType] | None


class PlanGenerationError(Exception):
    """Raised when plan generation fails."""

    def __init__(self, message: str, cause: Throwable | None = None):
        super().__init__(message)
        self.cause = cause


class PlanGenerator:
    """
    Generates execution plans using LLM.

    The PlanGenerator uses an LLM to analyze user queries and create
    structured execution plans with steps, dependencies, and tool selections.

    Attributes:
        llm_client: Async LLM client for generation
        available_tools: List of tools that can be used in plans
        max_steps: Maximum number of steps to generate
    """

    def __init__(
        self,
        llm_client: Any,
        available_tools: list[Any],
        max_steps: int = 10,
    ) -> None:
        """
        Initialize the PlanGenerator.

        Args:
            llm_client: Async LLM client with generate() method
            available_tools: List of available tool objects with name/description
            max_steps: Maximum number of steps to allow in generated plans
        """
        self.llm_client = llm_client
        self.available_tools = available_tools
        self.max_steps = max_steps

    def _format_tool_descriptions(self) -> str:
        """
        Format available tools into a descriptive string.

        Returns:
            Formatted string describing available tools
        """
        if not self.available_tools:
            return "No tools available"

        descriptions = []
        for tool in self.available_tools:
            tool_name = getattr(tool, "name", "Unknown")
            tool_desc = getattr(tool, "description", "No description")
            descriptions.append(f"- {tool_name}: {tool_desc}")

        return "\n".join(descriptions)

    def _build_system_prompt(self) -> str:
        """
        Build the system prompt for plan generation.

        Returns:
            Formatted system prompt string
        """
        tools_desc = self._format_tool_descriptions()
        return PLAN_GENERATION_SYSTEM_PROMPT.format(
            tools=tools_desc,
            max_steps=self.max_steps,
        )

    def _build_user_prompt(
        self,
        query: str,
        context: str | None = None,
    ) -> str:
        """
        Build the user prompt for plan generation.

        Args:
            query: User's query/request
            context: Optional context information

        Returns:
            Formatted user prompt string
        """
        context_str = context if context else "No specific context"
        return PLAN_GENERATION_USER_PROMPT_TEMPLATE.format(
            context=context_str,
            query=query,
        )

    def _parse_llm_response(self, response: str) -> dict[str, Any]:
        """
        Parse the LLM response to extract the plan JSON.

        Handles both plain JSON and markdown-wrapped JSON.

        Args:
            response: Raw LLM response string

        Returns:
            Parsed dictionary with plan data

        Raises:
            ValueError: If response cannot be parsed as valid plan JSON
        """
        # Try to extract JSON from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try parsing the whole response as JSON
            json_str = response.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse plan JSON: {e}") from e

        if "steps" not in data:
            raise ValueError("Missing 'steps' key in plan response")

        return data

    def _map_dependencies(
        self,
        dep_indices: list[int],
        step_indices: dict[str, int],
    ) -> list[str]:
        """
        Map step index dependencies to step IDs.

        Args:
            dep_indices: List of step indices (0-based)
            step_indices: Mapping of step_id to index

        Returns:
            List of step IDs that this step depends on
        """
        dependencies = []
        index_to_id = {idx: sid for sid, idx in step_indices.items()}

        for idx in dep_indices:
            if idx in index_to_id:
                dependencies.append(index_to_id[idx])

        return dependencies

    def _validate_tool_availability(self, tool_name: str | None) -> bool:
        """
        Check if a tool is available.

        Args:
            tool_name: Name of the tool to check (None for think steps)

        Returns:
            True if tool is available or None (think step), False otherwise
        """
        if tool_name is None:
            return True  # Think steps don't need tools

        available_names = {getattr(t, "name", None) for t in self.available_tools}
        return tool_name in available_names

    def _create_execution_steps(
        self,
        raw_steps: list[dict[str, Any]],
    ) -> list[ExecutionStep]:
        """
        Create ExecutionStep instances from raw LLM output.

        Args:
            raw_steps: List of step dictionaries from LLM response

        Returns:
            List of ExecutionStep instances
        """
        steps: list[ExecutionStep] = []
        step_indices: dict[str, int] = {}

        for i, raw_step in enumerate(raw_steps):
            step_id = f"step-{uuid.uuid4().hex[:8]}"
            step_indices[step_id] = i

            # Extract step data with defaults
            description = raw_step.get("description", "Unnamed step")
            tool_name = raw_step.get("tool_name")
            tool_input = raw_step.get("input_data", {})
            dependencies_indices = raw_step.get("dependencies", [])

            # Map index-based dependencies to step IDs
            dependencies = self._map_dependencies(dependencies_indices, step_indices)

            # For think steps without a tool, use a placeholder
            if tool_name is None:
                tool_name = "__think__"

            # Create the step
            step = ExecutionStep(
                step_id=step_id,
                description=description,
                tool_name=tool_name,
                tool_input=tool_input,
                dependencies=dependencies,
            )
            steps.append(step)

        return steps

    def _generate_fallback_plan(
        self,
        conversation_id: str,
        query: str,
        reflection_enabled: bool = True,
    ) -> ExecutionPlan:
        """
        Generate a fallback plan when LLM generation fails.

        Analyzes the query to create a basic plan without LLM assistance.

        Args:
            conversation_id: ID of the conversation
            query: User's query
            reflection_enabled: Whether reflection is enabled

        Returns:
            Basic ExecutionPlan for the query
        """
        query_lower = query.lower()
        steps: list[ExecutionStep] = []

        # Check for search-related queries
        if any(keyword in query_lower for keyword in ["search", "find", "look up", "retrieve"]):
            # Look for available search tools
            search_tools = [
                t for t in self.available_tools
                if any(keyword in getattr(t, "name", "").lower()
                       for keyword in ["search", "memory", "entity"])
            ]

            if search_tools:
                tool = search_tools[0]
                steps.append(ExecutionStep(
                    step_id=f"step-{uuid.uuid4().hex[:8]}",
                    description=f"Search for information about: {query}",
                    tool_name=tool.name,
                    tool_input={"query": query},
                ))
            else:
                steps.append(ExecutionStep(
                    step_id=f"step-{uuid.uuid4().hex[:8]}",
                    description=f"Clarify search request: {query}",
                    tool_name="__think__",
                    tool_input={},
                ))

        # Check for summary-related queries
        elif any(keyword in query_lower for keyword in ["summarize", "summary", "brief"]):
            steps.append(ExecutionStep(
                step_id=f"step-{uuid.uuid4().hex[:8]}",
                description=f"Analyze and summarize: {query}",
                tool_name="__think__",
                tool_input={},
            ))

        # Generic fallback
        else:
            steps.append(ExecutionStep(
                step_id=f"step-{uuid.uuid4().hex[:8]}",
                description=f"Analyze request and determine next steps: {query}",
                tool_name="__think__",
                tool_input={},
            ))

        return ExecutionPlan(
            conversation_id=conversation_id,
            user_query=query,
            steps=steps,
            reflection_enabled=reflection_enabled,
        )

    async def generate_plan(
        self,
        conversation_id: str,
        query: str,
        context: str | None = None,
        reflection_enabled: bool = True,
        max_reflection_cycles: int = 3,
    ) -> ExecutionPlan:
        """
        Generate an execution plan for the given query.

        Uses the LLM to create a structured plan with steps and dependencies.
        Falls back to a basic plan if LLM generation fails.

        Args:
            conversation_id: ID of the conversation
            query: User's query/request
            context: Optional context for plan generation
            reflection_enabled: Whether to enable reflection for this plan
            max_reflection_cycles: Maximum number of reflection cycles

        Returns:
            ExecutionPlan with generated steps

        Raises:
            PlanGenerationError: If plan generation critically fails
        """
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(query, context)

        try:
            # Call LLM for plan generation
            response = await self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            # Parse the response
            plan_data = self._parse_llm_response(response)
            raw_steps = plan_data.get("steps", [])

            # Create execution steps (empty steps list is valid)
            steps = self._create_execution_steps(raw_steps)

            # Filter out steps with unavailable tools (but keep think steps)
            valid_steps = []
            for step in steps:
                if step.tool_name == "__think__" or self._validate_tool_availability(step.tool_name):
                    valid_steps.append(step)

            return ExecutionPlan(
                conversation_id=conversation_id,
                user_query=query,
                steps=valid_steps,
                reflection_enabled=reflection_enabled,
                max_reflection_cycles=max_reflection_cycles,
            )

        except Exception:
            # Log the error and use fallback
            # In production, would log here
            return self._generate_fallback_plan(
                conversation_id=conversation_id,
                query=query,
                reflection_enabled=reflection_enabled,
            )
