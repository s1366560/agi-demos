"""Reprocessing HTTP outcomes with real PostgreSQL enrollment transaction fences."""

import pytest
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import Memory, TaskLog
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.tests.integration.test_memory_online_http_postgres import (  # noqa: F401
    http_memory,
    pg_sync,
)


@pytest.mark.parametrize("outcome", ["success", "workflow_failure", "enrolled"])
async def test_reprocess_memory_http_outcome_is_persisted(http_memory, outcome):  # noqa: F811
    client, sessions, scope, graph, workflow = http_memory
    async with sessions() as db:
        db.add(
            Memory(
                id="reprocess-memory",
                project_id=scope.project_id,
                author_id=scope.actor_id,
                title="Reprocess source",
                content="The original content is retained after a workflow start failure.",
                version=1,
                status="ENABLED",
                processing_status="COMPLETED",
            )
        )
        await db.commit()
        if outcome == "enrolled":
            await SqlKnowledgeSyncEnrollment(db).bootstrap(scope)
            await db.commit()
    if outcome == "workflow_failure":
        workflow.start_workflow.side_effect = RuntimeError("workflow unavailable")

    response = await client.post("/api/v1/memories/reprocess-memory/reprocess")

    async with sessions() as db:
        memory = await db.get(Memory, "reprocess-memory")
        tasks = list((await db.scalars(select(TaskLog))).all())
        assert memory.version == 1
        assert memory.content == "The original content is retained after a workflow start failure."
        if outcome == "enrolled":
            assert response.status_code == 422, response.text
            assert "knowledge_sync_write_context_required" in response.text
            assert memory.processing_status == "COMPLETED"
            assert memory.task_id is None
            assert tasks == []
            graph.delete_episode_by_memory_id.assert_not_awaited()
            workflow.start_workflow.assert_not_awaited()
            return
        assert len(tasks) == 1
        assert tasks[0].id == memory.task_id
        graph.delete_episode_by_memory_id.assert_awaited_once_with(memory.id)
        workflow.start_workflow.assert_awaited_once()
        if outcome == "workflow_failure":
            assert response.status_code == 500, response.text
            assert memory.processing_status == "FAILED"
            assert tasks[0].status == "FAILED"
            assert "workflow unavailable" in tasks[0].error_message
        else:
            assert response.status_code == 200, response.text
            assert response.json()["processing_status"] == "PENDING"
            assert response.json()["task_id"] == memory.task_id
            assert memory.processing_status == "PENDING"
            assert tasks[0].status == "PENDING"
