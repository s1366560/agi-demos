"""Processing jobs persist the source version instead of recovering a later one."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa

from src.infrastructure.adapters.primary.web.routers.memories import (
    _add_memory_reprocessing_task,
    _mark_memory_reprocessing_task_failed,
)
from src.infrastructure.adapters.primary.web.routers.tasks import _task_payload_for_memory
from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog

pytestmark = pytest.mark.unit


async def make_memory(db, project, user):
    memory = Memory(
        id=str(uuid4()),
        project_id=project.id,
        author_id=user.id,
        title="Original",
        content="Original",
        version=6,
        processing_status="COMPLETED",
    )
    db.add(memory)
    await db.commit()
    return memory


async def test_new_processing_task_persists_original_revision_and_task_identity(
    test_db, test_project_db, test_user
):
    memory = await make_memory(test_db, test_project_db, test_user)
    task_id, _, payload = _add_memory_reprocessing_task(
        db=test_db,
        memory=memory,
        project=test_project_db,
        current_user=test_user,
        source_description="Reprocess",
    )
    await test_db.commit()
    task = await test_db.get(TaskLog, task_id)
    assert task.payload["source_revision"] == payload["source_revision"] == 6
    assert task.payload["task_id"] == memory.task_id == task_id
    retry = _task_payload_for_memory(memory, test_project_db, "retry-task")
    assert retry["source_revision"] == 6
    assert retry["task_id"] == "retry-task"


@pytest.mark.parametrize(
    "later_change", ["none", "edit", "delete", "replace_task", "legacy_payload"]
)
async def test_workflow_start_failure_uses_persisted_source_not_current_memory(
    test_db, test_project_db, test_user, later_change
):
    memory = await make_memory(test_db, test_project_db, test_user)
    task_id, _, _ = _add_memory_reprocessing_task(
        db=test_db,
        memory=memory,
        project=test_project_db,
        current_user=test_user,
        source_description="Reprocess",
    )
    await test_db.commit()
    memory_id = memory.id
    if later_change == "edit":
        await test_db.execute(
            sa.update(Memory)
            .where(Memory.id == memory_id)
            .values(version=7, content="New", processing_status="COMPLETED")
        )
    elif later_change == "delete":
        await test_db.execute(sa.delete(Memory).where(Memory.id == memory_id))
    elif later_change == "replace_task":
        await test_db.execute(
            sa.update(Memory)
            .where(Memory.id == memory_id)
            .values(task_id="new-task", processing_status="COMPLETED")
        )
    elif later_change == "legacy_payload":
        task = await test_db.get(TaskLog, task_id)
        task.payload = {
            key: value for key, value in task.payload.items() if key != "source_revision"
        }
    await test_db.commit()

    await _mark_memory_reprocessing_task_failed(
        db=test_db,
        memory=memory if later_change == "none" else SimpleNamespace(id=memory_id),
        task_id=task_id,
        error=RuntimeError("Late start failure"),
    )
    test_db.expire_all()
    task = await test_db.get(TaskLog, task_id)
    current = await test_db.get(Memory, memory_id)
    assert task.status == "FAILED"
    if later_change == "delete":
        assert current is None
    else:
        assert (
            current.processing_status
            == {
                "none": "FAILED",
                "edit": "COMPLETED",
                "replace_task": "COMPLETED",
                "legacy_payload": "PENDING",
            }[later_change]
        )
