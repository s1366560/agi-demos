from typing import Any

import pytest

from plugins.business.automation.workflow.engine import (
    AsyncioWorkflowEngine,
)
from plugins.business.automation.workflow.tasks import TaskManager


def test_constructor_requires_explicit_task_manager() -> None:
    with pytest.raises(TypeError, match="manager"):
        _ = AsyncioWorkflowEngine()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_start_workflow_tracks_owner_project_and_uses_workflow_id_key() -> None:
    manager = TaskManager()
    engine = AsyncioWorkflowEngine(manager=manager)

    async def _handler(input_data: dict[str, Any]) -> dict[str, Any]:
        return {"task_id": input_data["task_id"]}

    engine.register_handler("episode_processing", _handler)

    await engine.start_workflow(
        workflow_name="episode_processing",
        workflow_id="workflow-1",
        input_data={
            "project_id": "project-1",
            "user_id": "user-1",
            "task_id": "task-log-1",
        },
        task_queue="default",
    )

    assert set(manager.tasks) == {"workflow-1"}
    task = manager.get_task("workflow-1")
    assert task is not None
    run_task = task._task
    assert run_task is not None
    await run_task

    assert task.owner_user_id == "user-1"
    assert task.project_id == "project-1"
    assert task.metadata["task_id"] == "task-log-1"
    assert task.result == {"task_id": "task-log-1"}


async def test_unimplemented_workflow_rejects_dispatch_without_creating_a_successful_job():
    from fastapi import HTTPException

    from plugins.business.automation.workflow.contract import (
        UnsupportedWorkflowError,
        WorkflowStatus,
    )
    from src.infrastructure.adapters.primary.web.routers.maintenance import (
        _require_maintenance_workflow,
    )

    manager = TaskManager()
    engine = AsyncioWorkflowEngine(manager=manager)
    with pytest.raises(HTTPException) as unavailable:
        _require_maintenance_workflow(engine, "deduplicate_entities")
    assert unavailable.value.status_code == 501
    with pytest.raises(UnsupportedWorkflowError):
        await engine.start_workflow("deduplicate_entities", "unsupported", {}, "default")
    assert not manager.tasks
    assert (await engine.get_workflow_status("unsupported")).status == WorkflowStatus.FAILED
