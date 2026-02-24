"""ComposeTools use case (T112).

This use case handles the intelligent composition of multiple tools
to accomplish complex tasks through chaining.

Key Features:
- Discover existing tool compositions for given tools
- Create new compositions based on tool compatibility
- Execute composed tool chains with data transformations
- Track composition success for learning
- Support parallel and conditional execution
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from src.domain.model.agent import ToolComposition
from src.domain.ports.agent.agent_tool_port import AgentToolBase
from src.domain.ports.repositories.tool_composition_repository import (
    ToolCompositionRepositoryPort,
)

logger = logging.getLogger(__name__)


class ComposeToolsUseCase:
    """Use case for composing multiple tools together."""

    def __init__(
        self,
        composition_repository: ToolCompositionRepositoryPort,
        available_tools: dict[str, AgentToolBase],
    ) -> None:
        """
        Initialize the use case.

        Args:
            composition_repository: Repository for tool compositions
            available_tools: Dictionary of available tools by name
        """
        self._composition_repository = composition_repository
        self._available_tools = available_tools

    async def execute(
        self,
        tool_names: list[str],
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a tool composition.

        This method either:
        1. Finds an existing composition for the given tools
        2. Creates a new composition based on tool compatibility
        3. Executes the composition and tracks success

        Args:
            tool_names: Ordered list of tool names to compose
            execution_context: Context parameters for tool execution

        Returns:
            Result dictionary with:
                - success: Whether execution succeeded
                - result: The final output
                - composition: The composition used (existing or new)
                - steps: Individual tool execution results

        Raises:
            ValueError: If tools are not available or incompatible
        """
        execution_context = execution_context or {}

        # Validate tools are available
        missing_tools = set(tool_names) - set(self._available_tools.keys())
        if missing_tools:
            raise ValueError(f"Tools not available: {missing_tools}")

        # Get tool instances
        tools = [self._available_tools[name] for name in tool_names]

        # Check for existing composition
        existing_composition = await self._find_composition_for_tools(tool_names)

        if existing_composition:
            logger.info(f"Using existing composition: {existing_composition.name}")
            composition = existing_composition
        else:
            # Create new composition
            composition = await self._create_composition(tool_names, tools)
            logger.info(f"Created new composition: {composition.name}")

        # Execute the composition
        result = await self._execute_composition(
            composition,
            tools,
            execution_context,
        )

        # Track usage
        await self._composition_repository.update_usage(
            composition.id,
            success=result["success"],
        )

        return result

    async def _find_composition_for_tools(
        self,
        tool_names: list[str],
    ) -> ToolComposition | None:
        """Find an existing composition for the given tools."""
        compositions = await self._composition_repository.list_by_tools(tool_names)

        # Find composition with exact tool order match
        for composition in compositions:
            if composition.tools == tool_names:
                return composition

        return None

    async def _create_composition(
        self,
        tool_names: list[str],
        tools: list[AgentToolBase],
    ) -> ToolComposition:
        """Create a new tool composition."""
        # Validate tool compatibility
        for i in range(len(tools) - 1):
            current_tool = tools[i]
            next_tool = tools[i + 1]

            if not current_tool.can_compose_with(next_tool):
                raise ValueError(f"Tool {current_tool.name} cannot compose with {next_tool.name}")

        # Generate composition name
        primary_name = tools[0].name
        if len(tools) > 1:
            name = f"{primary_name}_and_{len(tools) - 1}_more"
        else:
            name = primary_name

        # Create composition
        composition = ToolComposition.create(
            tenant_id="",
            name=name,
            description=f"Composition of {', '.join(tool_names)}",
            tools=tool_names,
            composition_type="sequential",
        )

        # Save composition
        saved = await self._composition_repository.save(composition)
        return saved

    async def _execute_composition(
        self,
        composition: ToolComposition,
        tools: list[AgentToolBase],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute the tool composition.

        Supports three execution modes:
        - sequential: Execute tools one after another (default)
        - parallel: Execute all tools concurrently
        - conditional: Execute tools based on conditions
        """
        composition_type = composition.get_composition_type()

        if composition_type == "parallel":
            return await self._execute_parallel(composition, tools, execution_context)
        elif composition_type == "conditional":
            return await self._execute_conditional(composition, tools, execution_context)
        else:  # sequential (default)
            return await self._execute_sequential(composition, tools, execution_context)

    async def _execute_sequential(
        self,
        composition: ToolComposition,
        tools: list[AgentToolBase],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute tools sequentially, passing output from one to the next."""
        steps = []
        current_output = None
        success = True
        final_result = None

        try:
            for i, tool in enumerate(tools):
                step_result = await self._execute_tool_step(
                    tool,
                    current_output,
                    execution_context,
                    i > 0,  # is_chained
                )
                steps.append(step_result)

                if not step_result["success"]:
                    success = False
                    final_result = step_result["error"]
                    break

                current_output = step_result["output"]

            if success:
                final_result = current_output

        except Exception as e:
            logger.error(f"Error executing composition {composition.name}: {e}")
            success = False
            final_result = f"Error: {e!s}"

        return {
            "success": success,
            "result": final_result,
            "composition": composition.to_dict(),
            "steps": steps,
        }

    async def _execute_parallel(
        self,
        composition: ToolComposition,
        tools: list[AgentToolBase],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute all tools in parallel.

        All tools receive the same execution context and run concurrently.
        Results are aggregated into a dictionary keyed by tool name.
        """
        steps = []
        success = True
        results = {}

        try:
            # Execute all tools concurrently
            tasks = [
                self._execute_tool_step(
                    tool,
                    None,  # No previous output in parallel mode
                    execution_context,
                    False,  # Not chained
                )
                for tool in tools
            ]

            step_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Process results
            for tool, step_result in zip(tools, step_results, strict=False):
                if isinstance(step_result, Exception):
                    logger.error(f"Tool {tool.name} failed: {step_result}")
                    step_result = {
                        "success": False,
                        "tool": tool.name,
                        "error": str(step_result),
                        "output": None,
                    }
                    success = False

                steps.append(step_result)
                results[tool.name] = (
                    step_result.get("output") if step_result.get("success") else None
                )

            final_result: str | dict[str, object] = {
                "results": results,
                "all_succeeded": success,
                "succeeded_tools": [s["tool"] for s in steps if s["success"]],
                "failed_tools": [s["tool"] for s in steps if not s["success"]],
            }

        except Exception as e:
            logger.error(f"Error executing parallel composition {composition.name}: {e}")
            success = False
            final_result = f"Error: {e!s}"

        return {
            "success": success,
            "result": final_result,
            "composition": composition.to_dict(),
            "steps": steps,
        }

    async def _execute_conditional(
        self,
        composition: ToolComposition,
        tools: list[AgentToolBase],
        execution_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute tools conditionally based on execution_template conditions.

        execution_template should contain:
        {
            "type": "conditional",
            "conditions": [
                {"tool_index": 0, "condition": "key_exists", "key": "param"},
                {"tool_index": 1, "condition": "key_value", "key": "status", "value": "success"}
            ]
        }
        """
        steps = []
        current_output = None
        success = True
        final_result = None

        execution_template = composition.execution_template or {}
        conditions = execution_template.get("conditions", [])

        try:
            for i, tool in enumerate(tools):
                # Check condition for this tool
                should_execute = self._evaluate_condition(
                    i, current_output, execution_context, conditions
                )

                if not should_execute:
                    logger.info(f"Skipping tool {tool.name} - condition not met")
                    steps.append(
                        {
                            "success": True,
                            "tool": tool.name,
                            "output": None,
                            "skipped": True,
                        }
                    )
                    continue

                step_result = await self._execute_tool_step(
                    tool,
                    current_output,
                    execution_context,
                    i > 0,
                )
                steps.append(step_result)

                if not step_result["success"]:
                    # Check if we should fail fast or continue
                    fail_fast = execution_template.get("fail_fast", True)
                    if fail_fast:
                        success = False
                        final_result = step_result["error"]
                        break

                current_output = step_result["output"]

            if success:
                final_result = current_output

        except Exception as e:
            logger.error(f"Error executing conditional composition {composition.name}: {e}")
            success = False
            final_result = f"Error: {e!s}"

        return {
            "success": success,
            "result": final_result,
            "composition": composition.to_dict(),
            "steps": steps,
        }

    def _evaluate_condition(
        self,
        tool_index: int,
        current_output: Any,
        execution_context: dict[str, Any],
        conditions: list[dict[str, Any]],
    ) -> bool:
        """
        Evaluate whether a tool should execute based on conditions.
        - always: Always execute (default)
        - key_exists: Check if key exists in context or output
        - key_value: Check if key equals specific value
        - output_not_empty: Check if previous output is not empty
        """
        # Find condition for this tool index
        tool_condition = None
        for cond in conditions:
            if cond.get("tool_index") == tool_index:
                tool_condition = cond
                break
        if not tool_condition:
            return True  # No condition = always execute
        return self._check_condition_type(
            condition_type, tool_condition, current_output, execution_context
        )

    def _check_condition_type(
        self,
        condition_type: str,
        tool_condition: dict[str, Any],
        current_output: Any,
        execution_context: dict[str, Any],
    ) -> bool:
        """Dispatch condition evaluation by type."""
        _EVALUATORS: dict[str, Callable[..., bool]] = {
            "always": lambda: True,
            "key_exists": lambda: self._eval_key_exists(
                tool_condition, current_output, execution_context
            ),
            "key_value": lambda: self._eval_key_value(
                tool_condition, current_output, execution_context
            ),
            "output_not_empty": lambda: current_output is not None and current_output != "",
        }
        evaluator = _EVALUATORS.get(condition_type)
        if evaluator:
            return evaluator()
        logger.warning(f"Unknown condition type: {condition_type}")
        return True

    @staticmethod
    def _eval_key_exists(
        tool_condition: dict[str, Any],
        current_output: Any,
        execution_context: dict[str, Any],
    ) -> bool:
        """Evaluate 'key_exists' condition."""
        key = tool_condition.get("key")
        if not key:
            return True
        return key in execution_context or (
            current_output and isinstance(current_output, dict) and key in current_output
        )

    @staticmethod
    def _eval_key_value(
        tool_condition: dict[str, Any],
        current_output: Any,
        execution_context: dict[str, Any],
    ) -> bool:
        """Evaluate 'key_value' condition."""
        key = tool_condition.get("key")
        expected_value = tool_condition.get("value")
        if not key:
            return True
        actual_value = execution_context.get(key) or (
            current_output.get(key) if isinstance(current_output, dict) else None
        )
        return actual_value == expected_value

    async def _execute_tool_step(
        self,
        tool: AgentToolBase,
        previous_output: Any | None,
        execution_context: dict[str, Any],
        is_chained: bool,
    ) -> dict[str, Any]:
        """Execute a single tool in the composition chain."""
        try:
            # Prepare input for this tool
            if is_chained and previous_output is not None:
                # Transform previous output for this tool's input
                if isinstance(previous_output, str):
                    transformed = tool.compose_output(previous_output, tool)
                else:
                    transformed = {"input": previous_output}

                # Merge with execution context
                input_args = {**execution_context, **transformed}
            else:
                input_args = execution_context

            # Execute the tool
            result = await tool.safe_execute(**input_args)

            return {
                "success": True,
                "tool": tool.name,
                "output": result,
            }

        except Exception as e:
            logger.error(f"Error executing tool {tool.name}: {e}")
            return {
                "success": False,
                "tool": tool.name,
                "error": str(e),
            }

    async def list_compositions(
        self,
        tool_names: list[str] | None = None,
        limit: int = 100,
    ) -> list[ToolComposition]:
        """
        List tool compositions.

        Args:
            tool_names: Optional filter by tool names
            limit: Maximum number of compositions to return

        Returns:
            List of tool compositions
        """
        if tool_names:
            return await self._composition_repository.list_by_tools(tool_names)
        return await self._composition_repository.list_all(limit)

    async def get_composition(self, composition_id: str) -> ToolComposition | None:
        """Get a specific composition by ID."""
        return await self._composition_repository.get_by_id(composition_id)

    async def get_composition_by_name(self, name: str) -> ToolComposition | None:
        """Get a specific composition by name."""
        return await self._composition_repository.get_by_name(name)

    async def delete_composition(self, composition_id: str) -> bool:
        """Delete a composition."""
        return await self._composition_repository.delete(composition_id)
