"""Unit tests for local workflow startup handlers."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.infrastructure.adapters.primary.web.startup.workflow as workflow_module
from src.infrastructure.adapters.primary.web.startup.workflow import (
    _run_episode_processing_workflow,
    initialize_workflow_engine,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, TaskLog, User


def _task(task_id: str, project_id: str, payload: dict[str, object]) -> TaskLog:
    return TaskLog(
        id=task_id,
        group_id=project_id,
        task_type="add_episode",
        status="PENDING",
        payload=payload,
        entity_type="episode",
        created_at=datetime.now(UTC),
    )


def _memory(memory_id: str, project: Project, user: User) -> Memory:
    return Memory(
        id=memory_id,
        project_id=project.id,
        title="Workflow memory",
        content="Alice from OpenAI met Bob at Microsoft.",
        content_type="text",
        tags=[],
        entities=[],
        relationships=[],
        version=1,
        author_id=user.id,
        collaborators=[],
        is_public=False,
        status="ENABLED",
        processing_status="PENDING",
        meta={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_workflow_engine_registers_episode_handler() -> None:
    graph_service = SimpleNamespace(process_episode=AsyncMock())

    engine = await initialize_workflow_engine(graph_service)

    assert engine is not None
    assert "episode_processing" in engine._workflow_handlers


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episode_processing_workflow_updates_task_and_memory(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)

    memory_id = str(uuid4())
    task_id = str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "uuid": memory_id,
        "content": memory.content,
        "project_id": test_project_db.id,
        "tenant_id": test_project_db.tenant_id,
        "user_id": test_user.id,
    }
    task = _task(task_id, test_project_db.id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    graph_service = SimpleNamespace(
        process_episode=AsyncMock(
            return_value=SimpleNamespace(
                nodes=[object(), object()],
                edges=[object()],
                episodic_edges=[object(), object()],
            )
        )
    )

    result = await _run_episode_processing_workflow(payload, graph_service)

    assert result == {
        "episode_uuid": memory_id,
        "entities": 2,
        "relationships": 1,
        "mentions": 2,
    }
    graph_service.process_episode.assert_awaited_once_with(
        episode_uuid=memory_id,
        content=memory.content,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
        excluded_entity_types=None,
    )
    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "COMPLETED"
    assert task.progress == 100
    assert task.message == "Graph processing complete"
    assert task.result == result
    assert memory.processing_status == "COMPLETED"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_episode_processing_workflow_marks_failures(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(
        test_db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(workflow_module, "async_session_factory", session_factory)

    memory_id = str(uuid4())
    task_id = str(uuid4())
    memory = _memory(memory_id, test_project_db, test_user)
    payload = {
        "task_id": task_id,
        "memory_id": memory_id,
        "uuid": memory_id,
        "content": memory.content,
        "project_id": test_project_db.id,
        "tenant_id": test_project_db.tenant_id,
        "user_id": test_user.id,
    }
    task = _task(task_id, test_project_db.id, payload)
    test_db.add_all([memory, task])
    await test_db.commit()

    graph_service = SimpleNamespace(process_episode=AsyncMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        await _run_episode_processing_workflow(payload, graph_service)

    await test_db.refresh(task)
    await test_db.refresh(memory)
    assert task.status == "FAILED"
    assert task.progress == 100
    assert task.message == "Graph processing failed"
    assert task.error_message == "boom"
    assert memory.processing_status == "FAILED"
