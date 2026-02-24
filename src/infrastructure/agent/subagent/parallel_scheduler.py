"""
ParallelScheduler - Manages concurrent SubAgent execution.

Executes multiple SubAgentProcess instances in parallel using asyncio,
respecting dependency ordering and concurrency limits.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient


from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult

from .context_bridge import ContextBridge
from .process import SubAgentProcess
from .task_decomposer import SubTask

logger = logging.getLogger(__name__)

_scheduler_bg_tasks: set[asyncio.Task[Any]] = set()


@dataclass
class ParallelSchedulerConfig:
    """Configuration for parallel SubAgent execution."""

    max_concurrency: int = 3
    subtask_timeout: float = 120.0
    abort_on_first_failure: bool = False


@dataclass
class SubTaskExecution:
    """Tracks execution state of a single sub-task."""

    subtask: SubTask
    subagent: SubAgent
    process: SubAgentProcess | None = None
    result: SubAgentResult | None = None
    started: bool = False
    completed: bool = False
    error: str | None = None


@dataclass
class _RunTaskContext:
    """Shared mutable state passed to each parallel task runner."""

    completed_ids: set[str]
    results: list[SubAgentResult]
    event_queue: asyncio.Queue[dict[str, Any] | None]
    semaphore: asyncio.Semaphore
    abort_signal: asyncio.Event | None
    conversation_context: list[dict[str, str]]
    main_token_budget: int
    project_id: str
    tenant_id: str
    tools: list[Any]
    base_model: str
    base_api_key: str | None
    base_url: str | None
    llm_client: LLMClient | None
    subtask_timeout: float


class ParallelScheduler:
    """Schedules and executes multiple SubAgents concurrently.

    Respects:
    - Dependency ordering (DAG): tasks with dependencies wait for them
    - Concurrency limits: at most max_concurrency tasks run at once
    - Per-task timeouts: individual tasks can time out without affecting others
    - Event streaming: relays events from all running SubAgents

    The scheduler uses asyncio.TaskGroup for structured concurrency.
    """

    def __init__(
        self,
        config: ParallelSchedulerConfig | None = None,
    ) -> None:
        """Initialize ParallelScheduler.

        Args:
            config: Scheduler configuration.
        """
        self._config = config or ParallelSchedulerConfig()

    async def execute(
        self,
        subtasks: list[SubTask],
        subagent_map: dict[str, SubAgent],
        tools: list[Any],
        base_model: str,
        base_api_key: str | None = None,
        base_url: str | None = None,
        llm_client: LLMClient | None = None,
        conversation_context: list[dict[str, str]] | None = None,
        main_token_budget: int = 128000,
        project_id: str = "",
        tenant_id: str = "",
        abort_signal: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute sub-tasks with dependency-aware parallel scheduling.

        Yields SSE events from all SubAgents prefixed with their task ID.

        Args:
            subtasks: List of sub-tasks to execute.
            subagent_map: Mapping of agent name -> SubAgent.
            tools: Tool definitions for SubAgents.
            base_model: Default model name.
            base_api_key: API key.
            base_url: API base URL.
            llm_client: LLM client for SubAgent processes.
            conversation_context: Recent conversation for context.
            main_token_budget: Main agent's token budget.
            project_id: Project ID.
            tenant_id: Tenant ID.
            abort_signal: Signal to abort all execution.

        Yields:
            SSE event dicts with task_id prefix.
        """
        if not subtasks:
            return

        executions = self._build_execution_map(subtasks, subagent_map)
        if not executions:
            return

        yield {
            "type": "parallel_started",
            "data": {
                "task_count": len(executions),
                "task_ids": list(executions.keys()),
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

        ctx = _RunTaskContext(
            completed_ids=set(),
            results=[],
            event_queue=asyncio.Queue(),
            semaphore=asyncio.Semaphore(self._config.max_concurrency),
            abort_signal=abort_signal,
            conversation_context=conversation_context or [],
            main_token_budget=main_token_budget,
            project_id=project_id,
            tenant_id=tenant_id,
            tools=tools,
            base_model=base_model,
            base_api_key=base_api_key,
            base_url=base_url,
            llm_client=llm_client,
            subtask_timeout=self._config.subtask_timeout,
        )

        async for event in self._launch_and_drain_events(executions, ctx):
            yield event

        # Final summary event
        yield {
            "type": "parallel_completed",
            "data": {
                "total_tasks": len(executions),
                "succeeded": sum(1 for e in executions.values() if e.completed and not e.error),
                "failed": sum(1 for e in executions.values() if e.error),
                "results": [r.to_event_data() for r in ctx.results],
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _build_execution_map(
        subtasks: list[SubTask],
        subagent_map: dict[str, SubAgent],
    ) -> dict[str, SubTaskExecution]:
        """Build execution map from subtasks, skipping those without agents."""
        executions: dict[str, SubTaskExecution] = {}
        for st in subtasks:
            agent = ParallelScheduler._resolve_agent(st, subagent_map)
            if not agent:
                logger.warning(f"[ParallelScheduler] No agent for task {st.id}, skipping")
                continue
            executions[st.id] = SubTaskExecution(subtask=st, subagent=agent)
        return executions

    async def _launch_and_drain_events(
        self,
        executions: dict[str, SubTaskExecution],
        ctx: _RunTaskContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Launch all tasks, drain event queue until all complete."""
        tasks = [
            asyncio.create_task(self._run_single_task(task_id, execution, ctx))
            for task_id, execution in executions.items()
        ]

        async def wait_for_all() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)
            await ctx.event_queue.put(None)  # Sentinel

        sentinel_task = asyncio.create_task(wait_for_all())
        _scheduler_bg_tasks.add(sentinel_task)
        sentinel_task.add_done_callback(_scheduler_bg_tasks.discard)

        while True:
            event = await ctx.event_queue.get()
            if event is None:
                break
            yield event

    async def _run_single_task(
        self,
        task_id: str,
        execution: SubTaskExecution,
        ctx: _RunTaskContext,
    ) -> None:
        """Run a single sub-task, waiting for dependencies first."""
        await self._wait_for_dependencies(execution, ctx)
        if ctx.abort_signal and ctx.abort_signal.is_set():
            return

        async with ctx.semaphore:
            execution.started = True
            await ctx.event_queue.put(
                {
                    "type": "subtask_started",
                    "data": {
                        "task_id": task_id,
                        "subagent_name": execution.subagent.display_name,
                        "description": execution.subtask.description[:200],
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

            try:
                await self._execute_subtask_process(task_id, execution, ctx)
            except TimeoutError:
                execution.error = f"Task {task_id} timed out"
                logger.warning(f"[ParallelScheduler] {execution.error}")
            except Exception as e:
                execution.error = str(e)
                logger.error(f"[ParallelScheduler] Task {task_id} failed: {e}")
            finally:
                ctx.completed_ids.add(task_id)
                if execution.result:
                    ctx.results.append(execution.result)

                await ctx.event_queue.put(
                    {
                        "type": "subtask_completed",
                        "data": {
                            "task_id": task_id,
                            "success": execution.completed and not execution.error,
                            "error": execution.error,
                        },
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                )

    @staticmethod
    async def _wait_for_dependencies(
        execution: SubTaskExecution,
        ctx: _RunTaskContext,
    ) -> None:
        """Block until all dependency tasks have completed."""
        while not all(dep in ctx.completed_ids for dep in execution.subtask.dependencies):
            if ctx.abort_signal and ctx.abort_signal.is_set():
                return
            await asyncio.sleep(0.1)

    async def _execute_subtask_process(
        self,
        task_id: str,
        execution: SubTaskExecution,
        ctx: _RunTaskContext,
    ) -> None:
        """Build context, create SubAgentProcess, and relay events."""
        bridge = ContextBridge()
        context = bridge.build_subagent_context(
            user_message=execution.subtask.description,
            subagent_system_prompt=execution.subagent.system_prompt,
            conversation_context=ctx.conversation_context,
            main_token_budget=ctx.main_token_budget,
            project_id=ctx.project_id,
            tenant_id=ctx.tenant_id,
        )

        process = SubAgentProcess(
            subagent=execution.subagent,
            context=context,
            tools=ctx.tools,
            base_model=ctx.base_model,
            base_api_key=ctx.base_api_key,
            base_url=ctx.base_url,
            llm_client=ctx.llm_client,
            abort_signal=ctx.abort_signal,
        )
        execution.process = process

        async def _run_with_timeout() -> None:
            async for event in self._collect_events(process, task_id):
                await ctx.event_queue.put(event)

        await asyncio.wait_for(
            _run_with_timeout(),
            timeout=ctx.subtask_timeout,
        )

        execution.result = process.result
        execution.completed = True

    @staticmethod
    async def _collect_events(
        process: SubAgentProcess, task_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Collect events from a SubAgentProcess, adding task_id context."""
        async for event in process.execute():
            event_data = dict(event)
            if "data" in event_data and isinstance(event_data["data"], dict):
                event_data["data"] = {**event_data["data"], "task_id": task_id}
            else:
                event_data["task_id"] = task_id
            yield event_data

    @staticmethod
    def _resolve_agent(subtask: SubTask, agent_map: dict[str, SubAgent]) -> SubAgent | None:
        """Resolve which SubAgent to use for a sub-task."""
        if subtask.target_subagent and subtask.target_subagent in agent_map:
            return agent_map[subtask.target_subagent]
        # If no target specified, use first available agent
        if agent_map:
            return next(iter(agent_map.values()))
        return None
