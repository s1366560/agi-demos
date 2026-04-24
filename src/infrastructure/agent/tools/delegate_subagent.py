"""Delegate to SubAgent tool for ReAct agent.

This tool allows the main ReAct agent to autonomously decide when to delegate
tasks to specialized SubAgents. Instead of pre-routing based on keyword matching,
the LLM sees available SubAgents in the system prompt and can call this tool
to delegate tasks.

This implements the "SubAgent-as-Tool" pattern where SubAgents are treated as
tools in the ReAct loop, enabling LLM-driven intelligent routing.

Includes:
- delegate_subagent_tool: Single-task delegation
- parallel_delegate_subagent_tool: Multi-task parallel delegation
"""

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from typing import Any

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

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


# ---------------------------------------------------------------------------
# @tool_define versions (new pattern)
# ---------------------------------------------------------------------------

# Module-level DI references for @tool_define versions
_delegate_execute_callback: Callable[..., Coroutine[Any, Any, str]] | None = None
_delegate_run_registry: SubAgentRunRegistry | None = None
_delegate_conversation_id: str | None = None
_delegate_subagent_names: list[str] = []
_delegate_subagent_descriptions: dict[str, str] = {}
_delegate_delegation_depth: int = 0
_delegate_max_active_runs: int | None = None
_delegate_max_concurrency: int = 5


class _NestedToolRuntimeContext:
    """Runtime context bridge for nested ToolDefinitions.

    The processor calls wrapper ToolDefinitions without ``ctx`` on the legacy
    path, but it still injects runtime context into ``_tool_instance`` when that
    object exposes ``set_runtime_context``.
    """

    def __init__(self, *, conversation_id: str, agent_name: str = "subagent") -> None:
        super().__init__()
        self._conversation_id = conversation_id
        self._agent_name = agent_name
        self._context_var: ContextVar[ToolContext | None] = ContextVar(
            f"{__name__}.nested_tool_context.{id(self)}",
            default=None,
        )

    def set_runtime_context(self, ctx: ToolContext) -> None:
        _ = self._context_var.set(ctx)

    def get_context(self) -> ToolContext:
        ctx = self._context_var.get()
        if ctx is not None:
            return ctx
        return ToolContext(
            session_id=self._conversation_id,
            message_id="nested-tool",
            call_id="nested-tool",
            agent_name=self._agent_name,
            conversation_id=self._conversation_id,
            abort_signal=asyncio.Event(),
            messages=[],
        )


def configure_delegate_subagent(
    execute_callback: Callable[..., Coroutine[Any, Any, str]],
    run_registry: SubAgentRunRegistry,
    *,
    conversation_id: str | None = None,
    subagent_names: list[str] | None = None,
    subagent_descriptions: dict[str, str] | None = None,
    delegation_depth: int = 0,
    max_active_runs: int | None = None,
    max_concurrency: int = 5,
) -> None:
    """Configure dependencies for delegate_subagent_tool and parallel variant.

    Called at agent startup to inject the execution callback and registry.
    """
    global _delegate_execute_callback, _delegate_run_registry
    global _delegate_conversation_id, _delegate_subagent_names
    global _delegate_subagent_descriptions, _delegate_delegation_depth
    global _delegate_max_active_runs, _delegate_max_concurrency
    _delegate_execute_callback = execute_callback
    _delegate_run_registry = run_registry
    _delegate_conversation_id = conversation_id
    _delegate_subagent_names = subagent_names or []
    _delegate_subagent_descriptions = subagent_descriptions or {}
    _delegate_delegation_depth = delegation_depth
    _delegate_max_active_runs = max_active_runs if max_active_runs and max_active_runs > 0 else None
    _delegate_max_concurrency = max_concurrency


@tool_define(
    name="delegate_to_subagent",
    description=(
        "Delegate a task to a specialized SubAgent for independent execution. "
        "The SubAgent will handle the task autonomously and return results."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subagent_name": {
                "type": "string",
                "description": (
                    "Name of the SubAgent to delegate to. Choose the best match for the task."
                ),
            },
            "task": {
                "type": "string",
                "description": (
                    "Clear, specific description of the task to delegate. "
                    "Include all relevant context the SubAgent needs."
                ),
            },
            "workspace_task_id": {
                "type": "string",
                "description": (
                    "Optional explicit workspace execution task ID. "
                    "Use when delegating a specific workspace child task."
                ),
            },
        },
        "required": ["subagent_name", "task"],
    },
    permission="delegate",
    category="agent",
    tags=frozenset({"subagent", "delegation"}),
)
async def delegate_subagent_tool(
    ctx: ToolContext,
    *,
    subagent_name: str = "",
    task: str = "",
    workspace_task_id: str | None = None,
) -> ToolResult:
    """Delegate a task to a specialized SubAgent."""
    if _delegate_execute_callback is None:
        return ToolResult(
            output="Error: delegate_subagent is not configured. No execute callback.",
            is_error=True,
        )

    error = _validate_delegate_inputs(subagent_name, task)
    if error:
        return ToolResult(output=error, is_error=True)
    workspace_guardrail_error = _validate_workspace_delegation_guardrail(
        ctx,
        workspace_task_id=workspace_task_id,
    )
    if workspace_guardrail_error:
        return ToolResult(output=workspace_guardrail_error, is_error=True)

    started_at = time.time()
    run_id = await _register_single_run(ctx, subagent_name, task)
    if isinstance(run_id, str) and run_id.startswith("Error:"):
        return ToolResult(output=run_id, is_error=True)

    logger.info("[delegate_subagent_tool] Delegating to '%s': %s...", subagent_name, task[:100])

    # Capture callback in local to satisfy type narrowing
    callback = _delegate_execute_callback
    buffered_events: list[dict[str, Any]] = []

    try:
        if _supports_on_event_arg(callback):
            callback_kwargs: dict[str, Any] = {"on_event": buffered_events.append}
            if workspace_task_id:
                callback_kwargs["workspace_task_id"] = workspace_task_id
            result = await callback(subagent_name, task, **callback_kwargs)
        else:
            callback_kwargs = {"workspace_task_id": workspace_task_id} if workspace_task_id else {}
            result = await callback(subagent_name, task, **callback_kwargs)
        for ev in buffered_events:
            await ctx.emit(ev)
        await _finalize_success(ctx, run_id, result, started_at)
        return ToolResult(output=result, title=f"SubAgent: {subagent_name}")
    except Exception as exc:
        logger.error("[delegate_subagent_tool] Execution failed: %s", exc)
        for ev in buffered_events:
            await ctx.emit(ev)
        await _finalize_failure(ctx, run_id, exc, started_at)
        return ToolResult(
            output=f"Error: SubAgent '{subagent_name}' execution failed: {exc}",
            is_error=True,
        )


@tool_define(
    name="parallel_delegate_subagents",
    description=(
        "Delegate multiple independent tasks to SubAgents for parallel execution. "
        "Use when you have 2+ tasks that can run simultaneously."
    ),
    parameters={
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
                        },
                        "task": {
                            "type": "string",
                            "description": "Task description for this SubAgent.",
                        },
                        "workspace_task_id": {
                            "type": "string",
                            "description": "Optional explicit workspace execution task ID.",
                        },
                    },
                    "required": ["subagent_name", "task"],
                },
                "minItems": 2,
            },
        },
        "required": ["tasks"],
    },
    permission="delegate",
    category="agent",
    tags=frozenset({"subagent", "delegation", "parallel"}),
)
async def parallel_delegate_subagent_tool(
    ctx: ToolContext,
    *,
    tasks: Any = None,
) -> ToolResult:
    """Delegate multiple independent tasks to SubAgents in parallel."""
    if _delegate_execute_callback is None:
        return ToolResult(
            output="Error: delegate_subagent is not configured. No execute callback.",
            is_error=True,
        )

    parsed_tasks, error = _parse_tasks(tasks)
    if error:
        return ToolResult(output=error, is_error=True)
    for item in parsed_tasks:
        workspace_guardrail_error = _validate_workspace_delegation_guardrail(
            ctx,
            workspace_task_id=item.get("workspace_task_id"),
        )
        if workspace_guardrail_error:
            return ToolResult(output=workspace_guardrail_error, is_error=True)

    run_ids = await _register_parallel_runs_new(ctx, parsed_tasks)
    if isinstance(run_ids, str):
        return ToolResult(output=run_ids, is_error=True)

    task_count = len(parsed_tasks)
    logger.info("[parallel_delegate_tool] Starting %d parallel SubAgent executions", task_count)
    start_time = time.time()

    # Capture callback in local to satisfy type narrowing
    callback = _delegate_execute_callback
    results = await _execute_all_new(ctx, callback, parsed_tasks, run_ids)
    elapsed_ms = (time.time() - start_time) * 1000

    output = _format_results(results, task_count, elapsed_ms)
    return ToolResult(output=output, title=f"Parallel delegation: {task_count} tasks")


# ---------------------------------------------------------------------------
# Shared helpers for @tool_define versions
# ---------------------------------------------------------------------------


def _validate_delegate_inputs(subagent_name: str, task: str) -> str | None:
    """Validate inputs for single delegation."""
    if not subagent_name:
        return "Error: subagent_name is required"
    if subagent_name not in _delegate_subagent_names:
        avail = ", ".join(_delegate_subagent_names)
        return f"Error: SubAgent '{subagent_name}' not found. Available: {avail}"
    if not task:
        return "Error: task description is required"
    return None


def _validate_workspace_delegation_guardrail(
    ctx: ToolContext,
    *,
    workspace_task_id: str | None = None,
) -> str | None:
    runtime_context = ctx.runtime_context if isinstance(ctx.runtime_context, dict) else {}
    if runtime_context.get("task_authority") != "workspace":
        return None
    if isinstance(workspace_task_id, str) and workspace_task_id.strip():
        return None
    return (
        "Error: workspace-authority delegation requires workspace_task_id. "
        "Call todoread first, select the target child task's workspace_task_id, "
        "then retry delegate_to_subagent."
    )


async def _register_single_run(
    ctx: ToolContext,
    subagent_name: str,
    task: str,
) -> str | None:
    """Register a single run in the registry and emit started event."""
    registry = _delegate_run_registry
    conv_id = _delegate_conversation_id or ctx.conversation_id
    if not (registry and conv_id):
        return None
    active = registry.count_active_runs(conv_id)
    if _delegate_max_active_runs is not None and active >= _delegate_max_active_runs:
        return f"Error: active SubAgent run limit reached ({active}/{_delegate_max_active_runs})"
    run = registry.create_run(
        conversation_id=conv_id,
        subagent_name=subagent_name,
        task=task,
        metadata={"delegation_depth": _delegate_delegation_depth},
    )
    running = registry.mark_running(conv_id, run.run_id)
    if running:
        await ctx.emit({"type": "subagent_started", "data": running.to_event_data()})
    return run.run_id


async def _finalize_success(
    ctx: ToolContext,
    run_id: str | None,
    result: str,
    started_at: float,
) -> None:
    """Mark a run as completed and emit event."""
    registry = _delegate_run_registry
    conv_id = _delegate_conversation_id or ctx.conversation_id
    if not (registry and conv_id and run_id):
        return
    elapsed_ms = int((time.time() - started_at) * 1000)
    completed = registry.mark_completed(
        conversation_id=conv_id,
        run_id=run_id,
        summary=result,
        execution_time_ms=elapsed_ms,
    )
    if completed:
        await ctx.emit({"type": "subagent_completed", "data": completed.to_event_data()})


async def _finalize_failure(
    ctx: ToolContext,
    run_id: str | None,
    error: Exception,
    started_at: float,
) -> None:
    """Mark a run as failed and emit event."""
    registry = _delegate_run_registry
    conv_id = _delegate_conversation_id or ctx.conversation_id
    if not (registry and conv_id and run_id):
        return
    elapsed_ms = int((time.time() - started_at) * 1000)
    failed = registry.mark_failed(
        conversation_id=conv_id,
        run_id=run_id,
        error=str(error),
        execution_time_ms=elapsed_ms,
    )
    if failed:
        await ctx.emit({"type": "subagent_failed", "data": failed.to_event_data()})


def _parse_tasks(tasks: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Parse and validate the tasks parameter for parallel delegation."""
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
        err = _validate_single_task_item(i, t)
        if err:
            return [], err

    return tasks, None


def _validate_single_task_item(index: int, task: Any) -> str | None:
    """Validate a single task item in the parallel tasks list."""
    if not isinstance(task, dict):
        return f"Error: task[{index}] must be an object with subagent_name and task"
    name = task.get("subagent_name", "")
    if not name or name not in _delegate_subagent_names:
        avail = ", ".join(_delegate_subagent_names)
        return f"Error: task[{index}] has invalid subagent_name '{name}'. Available: {avail}"
    if not task.get("task"):
        return f"Error: task[{index}] is missing 'task' description"
    return None


async def _register_parallel_runs_new(
    ctx: ToolContext,
    tasks: list[dict[str, Any]],
) -> dict[int, str] | str:
    """Register parallel runs in the registry."""
    run_ids: dict[int, str] = {}
    registry = _delegate_run_registry
    conv_id = _delegate_conversation_id or ctx.conversation_id
    if not (registry and conv_id):
        return run_ids

    task_count = len(tasks)
    active = registry.count_active_runs(conv_id)
    if _delegate_max_active_runs is not None and active + task_count > _delegate_max_active_runs:
        return (
            f"Error: active SubAgent run limit reached "
            f"({active + task_count}/{_delegate_max_active_runs})"
        )
    for idx, item in enumerate(tasks):
        run = registry.create_run(
            conversation_id=conv_id,
            subagent_name=item["subagent_name"],
            task=item["task"],
            metadata={
                "delegation_depth": _delegate_delegation_depth,
                "parallel_index": idx,
                "parallel_total": task_count,
            },
        )
        run_ids[idx] = run.run_id
        running = registry.mark_running(conv_id, run.run_id)
        if running:
            await ctx.emit({"type": "subagent_started", "data": running.to_event_data()})
    return run_ids


async def _execute_all_new(
    ctx: ToolContext,
    callback: Callable[..., Coroutine[Any, Any, str]],
    tasks: list[dict[str, Any]],
    run_ids: dict[int, str],
) -> list[dict[str, Any]]:
    """Execute all parallel tasks with concurrency limit."""
    semaphore = asyncio.Semaphore(_delegate_max_concurrency)
    supports_event = _supports_on_event_arg(callback)

    async def run_one(index: int, item: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await _run_single_parallel_task(
                ctx, callback, supports_event, index, item, run_ids
            )

    coros = [run_one(i, t) for i, t in enumerate(tasks)]
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


async def _run_single_parallel_task(
    ctx: ToolContext,
    callback: Callable[..., Coroutine[Any, Any, str]],
    supports_event: bool,
    index: int,
    item: dict[str, Any],
    run_ids: dict[int, str],
) -> dict[str, Any]:
    """Execute a single task within parallel delegation."""
    name = item["subagent_name"]
    task_desc = item["task"]
    subtask_start = time.time()
    buffered_events: list[dict[str, Any]] = []
    try:
        if supports_event:
            callback_kwargs: dict[str, Any] = {"on_event": buffered_events.append}
            workspace_task_id = item.get("workspace_task_id")
            if workspace_task_id:
                callback_kwargs["workspace_task_id"] = workspace_task_id
            result = await callback(name, task_desc, **callback_kwargs)
        else:
            workspace_task_id = item.get("workspace_task_id")
            callback_kwargs = {"workspace_task_id": workspace_task_id} if workspace_task_id else {}
            result = await callback(name, task_desc, **callback_kwargs)
        for ev in buffered_events:
            await ctx.emit(ev)
        await _finalize_success(ctx, run_ids.get(index), result, subtask_start)
        return {"index": index, "subagent": name, "success": True, "result": result}
    except Exception as exc:
        logger.error("[parallel_delegate_tool] SubAgent '%s' failed: %s", name, exc)
        for ev in buffered_events:
            await ctx.emit(ev)
        await _finalize_failure(ctx, run_ids.get(index), exc, subtask_start)
        return {"index": index, "subagent": name, "success": False, "error": str(exc)}


def _format_results(
    results: list[dict[str, Any]],
    task_count: int,
    elapsed_ms: float,
) -> str:
    """Format parallel execution results into a readable string."""
    succeeded = sum(1 for r in results if r.get("success"))
    failed_count = len(results) - succeeded

    logger.info(
        "[parallel_delegate_tool] Completed %d tasks in %.0fms (%d succeeded, %d failed)",
        task_count,
        elapsed_ms,
        succeeded,
        failed_count,
    )

    header = (
        f"[Parallel execution completed: {succeeded}/{task_count} succeeded, "
        f"{elapsed_ms:.0f}ms total]"
    )
    output_lines: list[str] = [header, ""]
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


# ---------------------------------------------------------------------------
# Factory for nested delegate ToolDefinitions
# ---------------------------------------------------------------------------


def make_nested_delegate_tool_defs(
    *,
    subagent_names: list[str],
    subagent_descriptions: dict[str, str],
    execute_callback: Callable[..., Coroutine[Any, Any, str]],
    run_registry: SubAgentRunRegistry,
    conversation_id: str,
    delegation_depth: int,
    max_active_runs: int,
    include_parallel: bool = False,
    max_concurrency: int = 5,
) -> list[Any]:
    """Build nested delegate ToolDefinitions for use inside SubAgent scopes.

    Returns a list of ``ToolDefinition`` objects for the delegate tools
    (single + optional parallel).

    Because the ``@tool_define`` functions read from module-level globals, each
    closure produced here snapshots the current globals, re-configures them for
    the nested scope, delegates to the ``@tool_define`` execute, and restores
    the originals in a ``finally`` block.
    """
    from src.infrastructure.agent.processor.processor import ToolDefinition

    # References to the @tool_define ToolInfo objects (module-level singletons)
    single_info = delegate_subagent_tool
    parallel_info = parallel_delegate_subagent_tool
    single_runtime = _NestedToolRuntimeContext(conversation_id=conversation_id)
    parallel_runtime = _NestedToolRuntimeContext(conversation_id=conversation_id)

    # -- helpers to snapshot / restore module globals -----------------------

    _delegate_global_names = [
        "_delegate_execute_callback",
        "_delegate_run_registry",
        "_delegate_conversation_id",
        "_delegate_subagent_names",
        "_delegate_subagent_descriptions",
        "_delegate_delegation_depth",
        "_delegate_max_active_runs",
        "_delegate_max_concurrency",
    ]

    _mod = __import__(__name__)
    # Resolve to actual submodule via dotted path
    for part in __name__.split(".")[1:]:
        _mod = getattr(_mod, part)

    def _snapshot(names: list[str]) -> dict[str, Any]:
        return {n: getattr(_mod, n) for n in names}

    def _restore(snap: dict[str, Any]) -> None:
        for n, v in snap.items():
            setattr(_mod, n, v)

    # -- closures that configure + execute + restore -----------------------

    def _make_delegate_tool(
        tool_info: Any,
        runtime_context: _NestedToolRuntimeContext,
    ) -> Callable[..., Any]:
        """Wrap a delegate @tool_define for nested scope."""

        async def _execute(ctx: ToolContext | None = None, **kwargs: Any) -> Any:
            active_ctx = ctx if ctx is not None else runtime_context.get_context()
            snap = _snapshot(_delegate_global_names)
            try:
                configure_delegate_subagent(
                    execute_callback=execute_callback,
                    run_registry=run_registry,
                    conversation_id=conversation_id,
                    subagent_names=subagent_names,
                    subagent_descriptions=subagent_descriptions,
                    delegation_depth=delegation_depth,
                    max_active_runs=max_active_runs,
                    max_concurrency=max_concurrency,
                )
                return await tool_info.execute(active_ctx, **kwargs)
            finally:
                _restore(snap)

        return _execute

    # -- assemble ToolDefinition list --------------------------------------

    result: list[ToolDefinition] = []
    result.append(
        ToolDefinition(
            name=single_info.name,
            description=single_info.description,
            parameters=single_info.parameters,
            execute=_make_delegate_tool(single_info, single_runtime),
            _tool_instance=single_runtime,
        )
    )

    if include_parallel:
        result.append(
            ToolDefinition(
                name=parallel_info.name,
                description=parallel_info.description,
                parameters=parallel_info.parameters,
                execute=_make_delegate_tool(parallel_info, parallel_runtime),
                _tool_instance=parallel_runtime,
            )
        )

    return result
