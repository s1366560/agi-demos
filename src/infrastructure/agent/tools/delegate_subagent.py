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
import inspect
import json
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


def _supports_on_event_arg(callback: Callable[..., Coroutine[Any, Any, str]]) -> bool:
    """Check whether callback supports on_event kwarg (or **kwargs)."""
    target = callback
    side_effect = getattr(callback, "side_effect", None)
    if callable(side_effect):
        target = side_effect

    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return True

    if "on_event" in signature.parameters:
        return True

    return any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


class DelegateSubAgentTool(AgentTool):
    """Tool that allows the main agent to delegate tasks to specialized SubAgents.

    The main agent sees available SubAgents in the system prompt and can decide
    autonomously when to delegate. This replaces pre-routing keyword matching
    with LLM-driven routing.
    """

    def __init__(
        self,
        subagent_names: list[str],
        subagent_descriptions: dict[str, str],
        execute_callback: Callable[..., Coroutine[Any, Any, str]],
        run_registry: SubAgentRunRegistry | None = None,
        conversation_id: str | None = None,
        delegation_depth: int = 0,
        max_active_runs: int | None = None,
    ) -> None:
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
        self._supports_on_event = _supports_on_event_arg(execute_callback)
        self._pending_events: list[dict[str, Any]] = []
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._delegation_depth = delegation_depth
        self._max_active_runs = max_active_runs if max_active_runs and max_active_runs > 0 else None

    def consume_pending_events(self) -> list[dict[str, Any]]:
        """Consume and return pending streaming events from last execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "subagent_name": {
                    "type": "string",
                    "description": (
                        "Name of the SubAgent to delegate to. Choose the best match for the task."
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

    async def execute(self, subagent_name: str = "", task: str = "", **kwargs: Any) -> str:
        """Execute delegation to a SubAgent."""
        error = self._validate_inputs(subagent_name, task)
        if error:
            return error

        self._pending_events.clear()
        started_at = time.time()

        run_id = self._register_run(subagent_name, task)
        if isinstance(run_id, str) and run_id.startswith("Error:"):
            return run_id

        logger.info(f"[DelegateSubAgentTool] Delegating to '{subagent_name}': {task[:100]}...")

        try:
            result = await self._invoke_callback(subagent_name, task)
            self._finalize_run_success(run_id, result, started_at)
            return result
        except Exception as e:
            logger.error(f"[DelegateSubAgentTool] Execution failed: {e}")
            self._finalize_run_failure(run_id, e, started_at)
            return f"Error: SubAgent '{subagent_name}' execution failed: {e}"

    def _validate_inputs(self, subagent_name: str, task: str) -> str | None:
        if not subagent_name:
            return "Error: subagent_name is required"
        if subagent_name not in self._subagent_names:
            return (
                f"Error: SubAgent '{subagent_name}' not found. "
                f"Available: {', '.join(self._subagent_names)}"
            )
        if not task:
            return "Error: task description is required"
        return None

    def _register_run(self, subagent_name: str, task: str) -> str | None:
        if not (self._run_registry and self._conversation_id):
            return None
        active_runs = self._run_registry.count_active_runs(self._conversation_id)
        if self._max_active_runs is not None and active_runs >= self._max_active_runs:
            return (
                f"Error: active SubAgent run limit reached ({active_runs}/{self._max_active_runs})"
            )
        run = self._run_registry.create_run(
            conversation_id=self._conversation_id,
            subagent_name=subagent_name,
            task=task,
            metadata={"delegation_depth": self._delegation_depth},
        )
        running = self._run_registry.mark_running(self._conversation_id, run.run_id)
        if running:
            self._pending_events.append(
                {"type": "subagent_run_started", "data": running.to_event_data()}
            )
        return run.run_id

    async def _invoke_callback(self, subagent_name: str, task: str) -> str:
        if self._supports_on_event:
            return await self._execute_fn(subagent_name, task, on_event=self._pending_events.append)
        return await self._execute_fn(subagent_name, task)

    def _finalize_run_success(self, run_id: str | None, result: str, started_at: float) -> None:
        if not (self._run_registry and self._conversation_id and run_id):
            return
        elapsed_ms = int((time.time() - started_at) * 1000)
        completed = self._run_registry.mark_completed(
            conversation_id=self._conversation_id,
            run_id=run_id,
            summary=result if isinstance(result, str) else str(result),
            execution_time_ms=elapsed_ms,
        )
        if completed:
            self._pending_events.append(
                {"type": "subagent_run_completed", "data": completed.to_event_data()}
            )

    def _finalize_run_failure(
        self, run_id: str | None, error: Exception, started_at: float
    ) -> None:
        if not (self._run_registry and self._conversation_id and run_id):
            return
        elapsed_ms = int((time.time() - started_at) * 1000)
        failed = self._run_registry.mark_failed(
            conversation_id=self._conversation_id,
            run_id=run_id,
            error=str(error),
            execution_time_ms=elapsed_ms,
        )
        if failed:
            self._pending_events.append(
                {"type": "subagent_run_failed", "data": failed.to_event_data()}
            )


class ParallelDelegateSubAgentTool(AgentTool):
    """Tool for parallel delegation of multiple independent tasks to SubAgents.

    When the LLM identifies multiple independent tasks that can be handled by
    different SubAgents simultaneously, it uses this tool instead of calling
    delegate_to_subagent multiple times sequentially.

    Internal implementation uses asyncio.gather() for true concurrency.
    """

    def __init__(
        self,
        subagent_names: list[str],
        subagent_descriptions: dict[str, str],
        execute_callback: Callable[..., Coroutine[Any, Any, str]],
        max_concurrency: int = 5,
        run_registry: SubAgentRunRegistry | None = None,
        conversation_id: str | None = None,
        delegation_depth: int = 0,
        max_active_runs: int | None = None,
    ) -> None:
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
        self._supports_on_event = _supports_on_event_arg(execute_callback)
        self._max_concurrency = max_concurrency
        self._pending_events: list[dict[str, Any]] = []
        self._run_registry = run_registry
        self._conversation_id = conversation_id
        self._delegation_depth = delegation_depth
        self._max_active_runs = max_active_runs if max_active_runs and max_active_runs > 0 else None

    def consume_pending_events(self) -> list[dict[str, Any]]:
        """Consume and return pending streaming events from last execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
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

    async def execute(self, tasks: Any = None, **kwargs: Any) -> str:
        """Execute parallel delegation to multiple SubAgents."""
        self._pending_events.clear()

        parsed_tasks, error = self._parse_and_validate_tasks(tasks)
        if error:
            return error

        task_count = len(parsed_tasks)
        run_ids_by_index = self._register_parallel_runs(parsed_tasks)
        if isinstance(run_ids_by_index, str):
            return run_ids_by_index

        logger.info(f"[ParallelDelegate] Starting {task_count} parallel SubAgent executions")
        start_time = time.time()

        results = await self._execute_all(parsed_tasks, run_ids_by_index)
        elapsed_ms = (time.time() - start_time) * 1000

        return self._format_parallel_results(results, parsed_tasks, task_count, elapsed_ms)

    def _parse_and_validate_tasks(self, tasks: Any) -> tuple[list[dict[str, Any]], str | None]:
        if isinstance(tasks, str):
            try:
                tasks = json.loads(tasks)
            except json.JSONDecodeError:
                return [], "Error: 'tasks' must be a JSON array of {subagent_name, task} objects"

        if not tasks or not isinstance(tasks, list):
            return [], "Error: 'tasks' must be a non-empty array"

        if len(tasks) < 2:
            return [], "Error: parallel_delegate_subagents requires at least 2 tasks"

        for i, t in enumerate(tasks):
            error = self._validate_single_task(i, t)
            if error:
                return [], error

        return tasks, None

    def _validate_single_task(self, index: int, task: Any) -> str | None:
        if not isinstance(task, dict):
            return f"Error: task[{index}] must be an object with subagent_name and task"
        name = task.get("subagent_name", "")
        if not name or name not in self._subagent_names:
            return (
                f"Error: task[{index}] has invalid subagent_name '{name}'. "
                f"Available: {', '.join(self._subagent_names)}"
            )
        if not task.get("task"):
            return f"Error: task[{index}] is missing 'task' description"
        return None

    def _register_parallel_runs(self, tasks: list[dict[str, Any]]) -> dict[int, str] | str:
        run_ids_by_index: dict[int, str] = {}
        if not (self._run_registry and self._conversation_id):
            return run_ids_by_index

        task_count = len(tasks)
        active_runs = self._run_registry.count_active_runs(self._conversation_id)
        if self._max_active_runs is not None and active_runs + task_count > self._max_active_runs:
            return (
                "Error: active SubAgent run limit reached "
                f"({active_runs + task_count}/{self._max_active_runs})"
            )
        for idx, item in enumerate(tasks):
            run = self._run_registry.create_run(
                conversation_id=self._conversation_id,
                subagent_name=item["subagent_name"],
                task=item["task"],
                metadata={
                    "delegation_depth": self._delegation_depth,
                    "parallel_index": idx,
                    "parallel_total": task_count,
                },
            )
            run_ids_by_index[idx] = run.run_id
            running = self._run_registry.mark_running(self._conversation_id, run.run_id)
            if running:
                self._pending_events.append(
                    {"type": "subagent_run_started", "data": running.to_event_data()}
                )
        return run_ids_by_index

    async def _execute_all(
        self,
        tasks: list[dict[str, Any]],
        run_ids_by_index: dict[int, str],
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run_one(index: int, item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                return await self._execute_single_task(index, item, run_ids_by_index)

        coros = [_run_one(i, t) for i, t in enumerate(tasks)]
        raw_results = await asyncio.gather(*coros, return_exceptions=True)

        processed: list[dict[str, Any]] = []
        for i, r in enumerate(raw_results):
            if isinstance(r, Exception):
                processed.append(
                    {
                        "index": i,
                        "subagent": tasks[i].get("subagent_name", "unknown"),
                        "success": False,
                        "error": str(r),
                    }
                )
            elif isinstance(r, dict):
                processed.append(r)
            else:
                processed.append({"error": str(r), "success": False})
        return processed

    async def _execute_single_task(
        self,
        index: int,
        item: dict[str, Any],
        run_ids_by_index: dict[int, str],
    ) -> dict[str, Any]:
        name = item["subagent_name"]
        task_desc = item["task"]
        subtask_start = time.time()
        try:
            if self._supports_on_event:
                result = await self._execute_fn(
                    name, task_desc, on_event=self._pending_events.append
                )
            else:
                result = await self._execute_fn(name, task_desc)

            self._finalize_single_run_success(index, run_ids_by_index, result, subtask_start)
            return {"index": index, "subagent": name, "success": True, "result": result}
        except Exception as e:
            logger.error(f"[ParallelDelegate] SubAgent '{name}' failed: {e}")
            self._finalize_single_run_failure(index, run_ids_by_index, e, subtask_start)
            return {"index": index, "subagent": name, "success": False, "error": str(e)}

    def _finalize_single_run_success(
        self,
        index: int,
        run_ids_by_index: dict[int, str],
        result: str,
        started_at: float,
    ) -> None:
        run_id = run_ids_by_index.get(index)
        if not (self._run_registry and self._conversation_id and run_id):
            return
        completed = self._run_registry.mark_completed(
            conversation_id=self._conversation_id,
            run_id=run_id,
            summary=result if isinstance(result, str) else str(result),
            execution_time_ms=int((time.time() - started_at) * 1000),
        )
        if completed:
            self._pending_events.append(
                {"type": "subagent_run_completed", "data": completed.to_event_data()}
            )

    def _finalize_single_run_failure(
        self,
        index: int,
        run_ids_by_index: dict[int, str],
        error: Exception,
        started_at: float,
    ) -> None:
        run_id = run_ids_by_index.get(index)
        if not (self._run_registry and self._conversation_id and run_id):
            return
        failed = self._run_registry.mark_failed(
            conversation_id=self._conversation_id,
            run_id=run_id,
            error=str(error),
            execution_time_ms=int((time.time() - started_at) * 1000),
        )
        if failed:
            self._pending_events.append(
                {"type": "subagent_run_failed", "data": failed.to_event_data()}
            )

    @staticmethod
    def _format_parallel_results(
        results: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
        task_count: int,
        elapsed_ms: float,
    ) -> str:
        succeeded = sum(1 for r in results if r.get("success"))
        failed = len(results) - succeeded

        logger.info(
            f"[ParallelDelegate] Completed {task_count} tasks in {elapsed_ms:.0f}ms "
            f"({succeeded} succeeded, {failed} failed)"
        )

        output_lines = [
            f"[Parallel execution completed: {succeeded}/{task_count} succeeded, "
            f"{elapsed_ms:.0f}ms total]",
            "",
        ]
        for r in sorted(results, key=lambda x: x.get("index", 0)):
            name = r.get("subagent", "unknown")
            if r.get("success"):
                output_lines.append(f"--- {name} (success) ---")
                output_lines.append(r.get("result", ""))
            else:
                output_lines.append(f"--- {name} (failed) ---")
                output_lines.append(f"Error: {r.get('error', 'unknown error')}")
            output_lines.append("")

        return "\n".join(output_lines)
