"""Delegate to SubAgent tool for ReAct agent.

This tool allows the main ReAct agent to autonomously decide when to delegate
tasks to specialized SubAgents. Instead of pre-routing based on keyword matching,
the LLM sees available SubAgents in the system prompt and can call this tool
to delegate tasks.

This implements the "SubAgent-as-Tool" pattern where SubAgents are treated as
tools in the ReAct loop, enabling LLM-driven intelligent routing.

Includes:
- DelegateSubAgentTool: Single-task delegation
- ParallelDelegateSubAgentTool: Multi-task parallel delegation
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


class DelegateSubAgentTool(AgentTool):
    """Tool that allows the main agent to delegate tasks to specialized SubAgents.

    The main agent sees available SubAgents in the system prompt and can decide
    autonomously when to delegate. This replaces pre-routing keyword matching
    with LLM-driven routing.
    """

    def __init__(
        self,
        subagent_names: List[str],
        subagent_descriptions: Dict[str, str],
        execute_callback: Callable[..., Coroutine[Any, Any, str]],
    ):
        """Initialize delegation tool.

        Args:
            subagent_names: Names of available SubAgents.
            subagent_descriptions: Map of name -> description for the tool description.
            execute_callback: Async callback(subagent_name, task) -> result string.
        """
        desc_parts = [f"{n}: {d}" for n, d in subagent_descriptions.items()]
        descriptions_text = "; ".join(desc_parts) if desc_parts else "none"

        super().__init__(
            name="delegate_to_subagent",
            description=(
                f"Delegate a task to a specialized SubAgent for independent execution. "
                f"Available: {descriptions_text}"
            ),
        )
        self._subagent_names = subagent_names
        self._subagent_descriptions = subagent_descriptions
        self._execute_fn = execute_callback

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "subagent_name": {
                    "type": "string",
                    "description": (
                        "Name of the SubAgent to delegate to. "
                        "Choose the best match for the task."
                    ),
                    "enum": self._subagent_names,
                },
                "task": {
                    "type": "string",
                    "description": (
                        "Clear, specific description of the task to delegate. "
                        "Include all relevant context the SubAgent needs."
                    ),
                },
            },
            "required": ["subagent_name", "task"],
        }

    async def execute(self, subagent_name: str = "", task: str = "", **kwargs) -> str:
        """Execute delegation to a SubAgent.

        Args:
            subagent_name: Name of the target SubAgent.
            task: Task description for the SubAgent.

        Returns:
            SubAgent execution result as a formatted string.
        """
        if not subagent_name:
            return "Error: subagent_name is required"

        if subagent_name not in self._subagent_names:
            return (
                f"Error: SubAgent '{subagent_name}' not found. "
                f"Available: {', '.join(self._subagent_names)}"
            )

        if not task:
            return "Error: task description is required"

        logger.info(
            f"[DelegateSubAgentTool] Delegating to '{subagent_name}': {task[:100]}..."
        )

        try:
            result = await self._execute_fn(subagent_name, task)
            return result
        except Exception as e:
            logger.error(f"[DelegateSubAgentTool] Execution failed: {e}")
            return f"Error: SubAgent '{subagent_name}' execution failed: {e}"


class ParallelDelegateSubAgentTool(AgentTool):
    """Tool for parallel delegation of multiple independent tasks to SubAgents.

    When the LLM identifies multiple independent tasks that can be handled by
    different SubAgents simultaneously, it uses this tool instead of calling
    delegate_to_subagent multiple times sequentially.

    Internal implementation uses asyncio.gather() for true concurrency.
    """

    def __init__(
        self,
        subagent_names: List[str],
        subagent_descriptions: Dict[str, str],
        execute_callback: Callable[..., Coroutine[Any, Any, str]],
        max_concurrency: int = 5,
    ):
        """Initialize parallel delegation tool.

        Args:
            subagent_names: Names of available SubAgents.
            subagent_descriptions: Map of name -> description.
            execute_callback: Async callback(subagent_name, task) -> result string.
            max_concurrency: Maximum number of concurrent SubAgent executions.
        """
        desc_parts = [f"{n}: {d}" for n, d in subagent_descriptions.items()]
        descriptions_text = "; ".join(desc_parts) if desc_parts else "none"

        super().__init__(
            name="parallel_delegate_subagents",
            description=(
                "Delegate multiple independent tasks to SubAgents for parallel "
                "execution. Use when you have 2+ tasks that can run simultaneously. "
                f"Available SubAgents: {descriptions_text}"
            ),
        )
        self._subagent_names = subagent_names
        self._subagent_descriptions = subagent_descriptions
        self._execute_fn = execute_callback
        self._max_concurrency = max_concurrency

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": (
                        "List of independent tasks to delegate in parallel. "
                        "Each task is assigned to a specific SubAgent."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "subagent_name": {
                                "type": "string",
                                "description": "Name of the SubAgent.",
                                "enum": self._subagent_names,
                            },
                            "task": {
                                "type": "string",
                                "description": "Task description for this SubAgent.",
                            },
                        },
                        "required": ["subagent_name", "task"],
                    },
                    "minItems": 2,
                },
            },
            "required": ["tasks"],
        }

    async def execute(self, tasks: Any = None, **kwargs) -> str:
        """Execute parallel delegation to multiple SubAgents.

        Args:
            tasks: List of {subagent_name, task} dicts. May be a JSON string
                   or already-parsed list depending on LLM output parsing.

        Returns:
            JSON-formatted aggregated results from all SubAgents.
        """
        # Handle JSON string input (some LLM parsers pass raw strings)
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except json.JSONDecodeError:
                return "Error: 'tasks' must be a JSON array of {subagent_name, task} objects"

        if not tasks or not isinstance(tasks, list):
            return "Error: 'tasks' must be a non-empty array"

        if len(tasks) < 2:
            return "Error: parallel_delegate_subagents requires at least 2 tasks"

        # Validate all tasks before execution
        for i, t in enumerate(tasks):
            if not isinstance(t, dict):
                return f"Error: task[{i}] must be an object with subagent_name and task"
            name = t.get("subagent_name", "")
            if not name or name not in self._subagent_names:
                return (
                    f"Error: task[{i}] has invalid subagent_name '{name}'. "
                    f"Available: {', '.join(self._subagent_names)}"
                )
            if not t.get("task"):
                return f"Error: task[{i}] is missing 'task' description"

        task_count = len(tasks)
        logger.info(
            f"[ParallelDelegate] Starting {task_count} parallel SubAgent executions"
        )
        start_time = time.time()

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run_one(index: int, item: Dict[str, Any]) -> Dict[str, Any]:
            name = item["subagent_name"]
            task_desc = item["task"]
            async with semaphore:
                try:
                    result = await self._execute_fn(name, task_desc)
                    return {
                        "index": index,
                        "subagent": name,
                        "success": True,
                        "result": result,
                    }
                except Exception as e:
                    logger.error(
                        f"[ParallelDelegate] SubAgent '{name}' failed: {e}"
                    )
                    return {
                        "index": index,
                        "subagent": name,
                        "success": False,
                        "error": str(e),
                    }

        # Execute all tasks concurrently
        coros = [_run_one(i, t) for i, t in enumerate(tasks)]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Process results (handle unexpected exceptions from gather)
        processed = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                processed.append({
                    "index": i,
                    "subagent": tasks[i].get("subagent_name", "unknown"),
                    "success": False,
                    "error": str(r),
                })
            else:
                processed.append(r)

        elapsed_ms = (time.time() - start_time) * 1000
        succeeded = sum(1 for r in processed if r.get("success"))
        failed = len(processed) - succeeded

        logger.info(
            f"[ParallelDelegate] Completed {task_count} tasks in {elapsed_ms:.0f}ms "
            f"({succeeded} succeeded, {failed} failed)"
        )

        # Format output for LLM consumption
        output_lines = [
            f"[Parallel execution completed: {succeeded}/{task_count} succeeded, "
            f"{elapsed_ms:.0f}ms total]",
            "",
        ]
        for r in sorted(processed, key=lambda x: x.get("index", 0)):
            name = r.get("subagent", "unknown")
            if r.get("success"):
                output_lines.append(f"--- {name} (success) ---")
                output_lines.append(r.get("result", ""))
            else:
                output_lines.append(f"--- {name} (failed) ---")
                output_lines.append(f"Error: {r.get('error', 'unknown error')}")
            output_lines.append("")

        return "\n".join(output_lines)
