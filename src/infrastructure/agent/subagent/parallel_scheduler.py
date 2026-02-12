"""
ParallelScheduler - Manages concurrent SubAgent execution.

Executes multiple SubAgentProcess instances in parallel using asyncio,
respecting dependency ordering and concurrency limits.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from src.domain.model.agent.subagent import SubAgent
from src.domain.model.agent.subagent_result import SubAgentResult

from .context_bridge import ContextBridge, SubAgentContext
from .process import SubAgentProcess
from .task_decomposer import SubTask

logger = logging.getLogger(__name__)


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
    process: Optional[SubAgentProcess] = None
    result: Optional[SubAgentResult] = None
    started: bool = False
    completed: bool = False
    error: Optional[str] = None


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
        config: Optional[ParallelSchedulerConfig] = None,
    ):
        """Initialize ParallelScheduler.

        Args:
            config: Scheduler configuration.
        """
        self._config = config or ParallelSchedulerConfig()

    async def execute(
        self,
        subtasks: List[SubTask],
        subagent_map: Dict[str, SubAgent],
        tools: List[Any],
        base_model: str,
        base_api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_client: Optional[Any] = None,
        conversation_context: Optional[List[Dict[str, str]]] = None,
        main_token_budget: int = 128000,
        project_id: str = "",
        tenant_id: str = "",
        abort_signal: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
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

        # Build execution map
        executions: Dict[str, SubTaskExecution] = {}
        for st in subtasks:
            agent = self._resolve_agent(st, subagent_map)
            if not agent:
                logger.warning(f"[ParallelScheduler] No agent for task {st.id}, skipping")
                continue
            executions[st.id] = SubTaskExecution(subtask=st, subagent=agent)

        if not executions:
            return

        yield {
            "type": "parallel_started",
            "data": {
                "task_count": len(executions),
                "task_ids": list(executions.keys()),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Track completed task IDs for dependency resolution
        completed_ids: Set[str] = set()
        results: List[SubAgentResult] = []

        # Event queue for collecting events from parallel tasks
        event_queue: asyncio.Queue = asyncio.Queue()
        semaphore = asyncio.Semaphore(self._config.max_concurrency)

        async def run_task(task_id: str, execution: SubTaskExecution) -> None:
            """Run a single sub-task, waiting for dependencies first."""
            # Wait for dependencies
            while not all(dep in completed_ids for dep in execution.subtask.dependencies):
                if abort_signal and abort_signal.is_set():
                    return
                await asyncio.sleep(0.1)

            async with semaphore:
                execution.started = True
                await event_queue.put({
                    "type": "subtask_started",
                    "data": {
                        "task_id": task_id,
                        "subagent_name": execution.subagent.display_name,
                        "description": execution.subtask.description[:200],
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                try:
                    # Build context for this sub-task
                    bridge = ContextBridge()
                    context = bridge.build_subagent_context(
                        user_message=execution.subtask.description,
                        subagent_system_prompt=execution.subagent.system_prompt,
                        conversation_context=conversation_context or [],
                        main_token_budget=main_token_budget,
                        project_id=project_id,
                        tenant_id=tenant_id,
                    )

                    process = SubAgentProcess(
                        subagent=execution.subagent,
                        context=context,
                        tools=tools,
                        base_model=base_model,
                        base_api_key=base_api_key,
                        base_url=base_url,
                        llm_client=llm_client,
                        abort_signal=abort_signal,
                    )
                    execution.process = process

                    # Execute and relay events with task_id prefix
                    async for event in asyncio.wait_for(
                        self._collect_events(process, task_id),
                        timeout=self._config.subtask_timeout,
                    ):
                        await event_queue.put(event)

                    execution.result = process.result
                    execution.completed = True

                except asyncio.TimeoutError:
                    execution.error = f"Task {task_id} timed out"
                    logger.warning(f"[ParallelScheduler] {execution.error}")
                except Exception as e:
                    execution.error = str(e)
                    logger.error(f"[ParallelScheduler] Task {task_id} failed: {e}")
                finally:
                    completed_ids.add(task_id)
                    if execution.result:
                        results.append(execution.result)

                    await event_queue.put({
                        "type": "subtask_completed",
                        "data": {
                            "task_id": task_id,
                            "success": execution.completed and not execution.error,
                            "error": execution.error,
                        },
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

        # Launch all tasks concurrently
        tasks = []
        for task_id, execution in executions.items():
            tasks.append(asyncio.create_task(run_task(task_id, execution)))

        # Also launch a sentinel to detect when all tasks are done
        all_done = asyncio.Event()

        async def wait_for_all():
            await asyncio.gather(*tasks, return_exceptions=True)
            all_done.set()
            await event_queue.put(None)  # Sentinel

        asyncio.create_task(wait_for_all())

        # Yield events as they arrive
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield event

        # Final summary event
        yield {
            "type": "parallel_completed",
            "data": {
                "total_tasks": len(executions),
                "succeeded": sum(1 for e in executions.values() if e.completed and not e.error),
                "failed": sum(1 for e in executions.values() if e.error),
                "results": [r.to_event_data() for r in results],
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    async def _collect_events(
        process: SubAgentProcess, task_id: str
    ) -> AsyncIterator[Dict[str, Any]]:
        """Collect events from a SubAgentProcess, adding task_id context."""
        async for event in process.execute():
            event_data = dict(event)
            if "data" in event_data and isinstance(event_data["data"], dict):
                event_data["data"] = {**event_data["data"], "task_id": task_id}
            else:
                event_data["task_id"] = task_id
            yield event_data

    @staticmethod
    def _resolve_agent(
        subtask: SubTask, agent_map: Dict[str, SubAgent]
    ) -> Optional[SubAgent]:
        """Resolve which SubAgent to use for a sub-task."""
        if subtask.target_subagent and subtask.target_subagent in agent_map:
            return agent_map[subtask.target_subagent]
        # If no target specified, use first available agent
        if agent_map:
            return next(iter(agent_map.values()))
        return None
