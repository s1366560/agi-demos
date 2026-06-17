"""Asyncio-based WorkflowEnginePort implementation.

Replaces TemporalWorkflowEngine with in-process asyncio tasks,
using the existing TaskManager for lifecycle tracking.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from src.domain.ports.services.workflow_engine_port import (
    WorkflowEnginePort,
    WorkflowExecution,
    WorkflowStatus,
)
from src.infrastructure.adapters.secondary.background_tasks import (
    BackgroundTask,
    TaskManager,
    TaskStatus,
    task_manager,
)

logger = logging.getLogger(__name__)

# Map TaskStatus -> WorkflowStatus
_STATUS_MAP = {
    TaskStatus.PENDING: WorkflowStatus.RUNNING,
    TaskStatus.RUNNING: WorkflowStatus.RUNNING,
    TaskStatus.COMPLETED: WorkflowStatus.COMPLETED,
    TaskStatus.FAILED: WorkflowStatus.FAILED,
    TaskStatus.CANCELLED: WorkflowStatus.CANCELLED,
}


def _metadata_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _workflow_tracking_metadata(
    input_data: dict[str, Any],
    metadata: dict[str, str] | None,
) -> tuple[str | None, str | None, dict[str, Any]]:
    task_metadata: dict[str, Any] = dict(metadata or {})
    for key in ("project_id", "group_id", "task_group_id", "user_id", "owner_user_id", "task_id"):
        value = input_data.get(key)
        if key not in task_metadata and value is not None:
            task_metadata[key] = str(value)

    owner_user_id = _metadata_string(
        task_metadata.get("owner_user_id") or task_metadata.get("user_id")
    )
    project_id = _metadata_string(
        task_metadata.get("project_id")
        or task_metadata.get("group_id")
        or task_metadata.get("task_group_id")
    )
    return owner_user_id, project_id, task_metadata


class AsyncioWorkflowEngine(WorkflowEnginePort):
    """In-process asyncio workflow engine.

    Uses asyncio.create_task() for background execution and
    TaskManager for lifecycle tracking. The task_queue parameter
    is accepted for API compatibility but ignored since all tasks
    run in-process.
    """

    def __init__(
        self,
        manager: TaskManager | None = None,
        max_concurrent: int = 50,
    ) -> None:
        self._manager = manager or task_manager
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._workflow_handlers: dict[str, Any] = {}

    def register_handler(self, workflow_name: str, handler: Callable[..., Awaitable[Any]]) -> None:
        """Register an async handler function for a workflow name."""
        self._workflow_handlers[workflow_name] = handler

    async def start_workflow(
        self,
        workflow_name: str,
        workflow_id: str,
        input_data: dict[str, Any],
        task_queue: str,
        timeout_seconds: int = 3600,
        metadata: dict[str, str] | None = None,
    ) -> WorkflowExecution:
        run_id = str(uuid.uuid4())

        async def _execute() -> None:
            async with self._semaphore:
                handler = self._workflow_handlers.get(workflow_name)
                if handler:
                    return await asyncio.wait_for(
                        handler(input_data),
                        timeout=timeout_seconds,
                    )
                logger.warning(
                    f"No handler registered for workflow '{workflow_name}', skipping execution"
                )
                return None

        owner_user_id, project_id, task_metadata = _workflow_tracking_metadata(input_data, metadata)
        bg_task = self._manager.create_task(workflow_name, _execute)
        original_task_id = bg_task.task_id
        bg_task.task_id = workflow_id
        bg_task.owner_user_id = owner_user_id
        bg_task.project_id = project_id
        bg_task.metadata = task_metadata
        _ = self._manager.tasks.pop(original_task_id, None)
        self._manager.tasks[workflow_id] = bg_task
        bg_task._task = asyncio.create_task(bg_task.run())

        logger.info(f"Started workflow '{workflow_name}' id={workflow_id} run={run_id}")
        return WorkflowExecution(
            workflow_id=workflow_id,
            run_id=run_id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

    async def get_workflow_status(self, workflow_id: str) -> WorkflowExecution:
        task = self._manager.get_task(workflow_id)
        if not task:
            return WorkflowExecution(
                workflow_id=workflow_id,
                run_id="",
                status=WorkflowStatus.COMPLETED,
                error_message="Workflow not found (may have been cleaned up)",
            )
        return self._to_execution(workflow_id, task)

    async def get_workflow_result(
        self, workflow_id: str, timeout_seconds: int = 30
    ) -> dict[str, Any]:
        task = self._manager.get_task(workflow_id)
        if not task:
            return {"status": "not_found"}

        if task._task and not task._task.done():
            await asyncio.wait_for(asyncio.shield(task._task), timeout=timeout_seconds)

        return {"result": task.result, "error": task.error}

    async def cancel_workflow(self, workflow_id: str, reason: str | None = None) -> bool:
        return await self._manager.cancel_task(workflow_id)

    async def terminate_workflow(self, workflow_id: str, reason: str | None = None) -> bool:
        return await self._manager.cancel_task(workflow_id)

    async def signal_workflow(
        self, workflow_id: str, signal_name: str, payload: dict[str, Any]
    ) -> bool:
        logger.debug(f"Signal '{signal_name}' to workflow {workflow_id} (no-op in asyncio engine)")
        return True

    async def list_workflows(
        self,
        task_queue: str | None = None,
        status: WorkflowStatus | None = None,
        limit: int = 100,
    ) -> list[WorkflowExecution]:
        results = []
        for wf_id, task in list(self._manager.tasks.items()):
            execution = self._to_execution(wf_id, task)
            if status and execution.status != status:
                continue
            results.append(execution)
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _to_execution(workflow_id: str, task: BackgroundTask) -> WorkflowExecution:
        return WorkflowExecution(
            workflow_id=workflow_id,
            run_id=task.task_id,
            status=_STATUS_MAP.get(task.status, WorkflowStatus.RUNNING),
            result=task.result if task.status == TaskStatus.COMPLETED else None,
            error_message=task.error if task.status == TaskStatus.FAILED else None,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )
