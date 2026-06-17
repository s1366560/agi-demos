from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.primary.web.routers import tasks as tasks_router
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey as DBAPIKey,
    Memory,
    Project,
    TaskLog as DBTaskLog,
)

app = create_app()


@pytest.mark.asyncio
async def test_tasks_endpoints(authenticated_async_client, test_db: AsyncSession):
    client: AsyncClient = authenticated_async_client

    now = datetime.now(UTC)
    # Seed some task logs
    tasks = [
        DBTaskLog(
            id="t1",
            group_id="proj_123",
            task_type="rebuild",
            status="COMPLETED",
            created_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
        ),
        DBTaskLog(
            id="t2",
            group_id="proj_123",
            task_type="rebuild",
            status="FAILED",
            created_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=10),
            error_message="err",
        ),
        DBTaskLog(
            id="t3",
            group_id="proj_123",
            task_type="ingest",
            status="PENDING",
            created_at=now - timedelta(minutes=5),
        ),
        DBTaskLog(
            id="t4",
            group_id="proj_123",
            task_type="ingest",
            status="PROCESSING",
            created_at=now - timedelta(minutes=3),
            started_at=now - timedelta(minutes=2),
        ),
    ]
    for t in tasks:
        test_db.add(t)
    await test_db.commit()

    # Stats
    stats_resp = await client.get(
        "/api/v1/tasks/stats",
    )
    assert stats_resp.status_code == status.HTTP_200_OK
    stats = stats_resp.json()
    assert "total" in stats and "failed" in stats and "pending" in stats
    assert stats["total"] >= 4
    assert stats["pending"] >= 1

    # Queue depth
    depth_resp = await client.get(
        "/api/v1/tasks/queue-depth",
    )
    assert depth_resp.status_code == status.HTTP_200_OK
    assert isinstance(depth_resp.json(), list)

    # Recent
    recent_resp = await client.get(
        "/api/v1/tasks/recent",
    )
    assert recent_resp.status_code == status.HTTP_200_OK
    assert isinstance(recent_resp.json(), list)


@pytest.mark.asyncio
async def test_task_stream_requires_authorization(async_client: AsyncClient):
    response = await async_client.get("/api/v1/tasks/t1/stream")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_task_stream_accepts_authorized_header(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_engine,
    test_user,
    test_project_db,
    monkeypatch: pytest.MonkeyPatch,
):
    stream_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(tasks_router, "async_session_factory", stream_session_factory)

    token = "ms_sk_test_token_123456789"
    test_db.add(
        DBAPIKey(
            id="task-stream-key",
            key_hash=AuthService.hash_api_key(token),
            name="Task stream test key",
            user_id=test_user.id,
            permissions=["read"],
            is_active=True,
        )
    )
    test_db.add(
        DBTaskLog(
            id="stream-complete",
            group_id=test_project_db.id,
            task_type="rebuild",
            status="COMPLETED",
            payload={"project_id": test_project_db.id},
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
    )
    await test_db.commit()

    response = await authenticated_async_client.get("/api/v1/tasks/stream-complete/stream")

    assert response.status_code == status.HTTP_200_OK
    assert "event: completed" in response.text


@pytest.mark.asyncio
async def test_task_stats_requires_authentication(test_app):
    original_override = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/tasks/stats")
    finally:
        if original_override is not None:
            test_app.dependency_overrides[get_current_user] = original_override

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_recent_tasks_filters_to_current_user_projects(
    test_db: AsyncSession,
    test_project_db,
    test_user,
    another_user,
):
    foreign_project = Project(
        id="foreign-task-project",
        tenant_id=test_project_db.tenant_id,
        name="Foreign Task Project",
        owner_id=another_user.id,
    )
    allowed_task = DBTaskLog(
        id="allowed-task",
        group_id=test_project_db.id,
        task_type="add_episode",
        status="PENDING",
        payload={"project_id": test_project_db.id},
        created_at=datetime.now(UTC),
    )
    foreign_task = DBTaskLog(
        id="foreign-task",
        group_id=foreign_project.id,
        task_type="add_episode",
        status="PENDING",
        payload={"project_id": foreign_project.id},
        created_at=datetime.now(UTC),
    )
    test_db.add_all([foreign_project, allowed_task, foreign_task])
    await test_db.commit()

    response = await tasks_router.get_recent_tasks(
        limit=10,
        offset=0,
        current_user=test_user,
        db=test_db,
    )

    assert [task.id for task in response] == ["allowed-task"]


@pytest.mark.asyncio
async def test_get_task_status_rejects_unowned_project_task(
    test_db: AsyncSession,
    test_project_db,
    test_user,
    another_user,
):
    foreign_project = Project(
        id="foreign-status-project",
        tenant_id=test_project_db.tenant_id,
        name="Foreign Status Project",
        owner_id=another_user.id,
    )
    task = DBTaskLog(
        id="foreign-status-task",
        group_id=foreign_project.id,
        task_type="add_episode",
        status="PENDING",
        payload={"project_id": foreign_project.id},
        created_at=datetime.now(UTC),
    )
    test_db.add_all([foreign_project, task])
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await tasks_router.get_task_status(
            "foreign-status-task",
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_task_stream_rejects_unowned_project_task(
    authenticated_async_client: AsyncClient,
    test_db: AsyncSession,
    test_engine,
    test_user,
    test_project_db,
    another_user,
    monkeypatch: pytest.MonkeyPatch,
):
    stream_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(tasks_router, "async_session_factory", stream_session_factory)

    token = "ms_sk_test_token_123456789"
    foreign_project = Project(
        id="foreign-stream-project",
        tenant_id=test_project_db.tenant_id,
        name="Foreign Stream Project",
        owner_id=another_user.id,
    )
    test_db.add_all(
        [
            DBAPIKey(
                id="task-stream-foreign-key",
                key_hash=AuthService.hash_api_key(token),
                name="Task stream foreign key",
                user_id=test_user.id,
                permissions=["read"],
                is_active=True,
            ),
            foreign_project,
            DBTaskLog(
                id="foreign-stream-task",
                group_id=foreign_project.id,
                task_type="add_episode",
                status="COMPLETED",
                payload={"project_id": foreign_project.id},
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            ),
        ]
    )
    await test_db.commit()

    response = await authenticated_async_client.get("/api/v1/tasks/foreign-stream-task/stream")

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_retry_task_endpoint_restarts_pending_add_episode_task(
    test_db: AsyncSession,
    test_project_db,
    test_user,
):
    task = DBTaskLog(
        id="pending-add-episode",
        group_id=test_project_db.id,
        task_type="add_episode",
        status="PENDING",
        payload={
            "uuid": "memory-1",
            "content": "Ada Lovelace wrote notes about Charles Babbage.",
            "project_id": test_project_db.id,
            "memory_id": "memory-1",
        },
        progress=35,
        message="stale",
        created_at=datetime.now(UTC),
    )
    test_db.add(task)
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_task_endpoint(
        "pending-add-episode",
        current_user=test_user,
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(task)
    assert response == {"message": "Task retry submitted", "task_id": "pending-add-episode"}
    assert task.status == "PENDING"
    assert task.retry_count == 1
    assert task.progress == 0
    assert task.payload["task_id"] == "pending-add-episode"
    workflow_engine.start_workflow.assert_awaited_once()
    call_kwargs = workflow_engine.start_workflow.await_args.kwargs
    assert call_kwargs["workflow_name"] == "episode_processing"
    assert call_kwargs["input_data"]["task_id"] == "pending-add-episode"


@pytest.mark.asyncio
async def test_retry_task_endpoint_restarts_pending_maintenance_task(
    test_db: AsyncSession,
    test_project_db,
    test_user,
):
    task = DBTaskLog(
        id="pending-rebuild",
        group_id=test_project_db.id,
        task_type="rebuild_communities",
        status="PENDING",
        payload={"task_group_id": test_project_db.id},
        progress=0,
        created_at=datetime.now(UTC),
    )
    test_db.add(task)
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_task_endpoint(
        "pending-rebuild",
        current_user=test_user,
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(task)
    assert response == {"message": "Task retry submitted", "task_id": "pending-rebuild"}
    assert task.payload["project_id"] == test_project_db.id
    workflow_engine.start_workflow.assert_awaited_once()
    call_kwargs = workflow_engine.start_workflow.await_args.kwargs
    assert call_kwargs["workflow_name"] == "rebuild_communities"
    assert call_kwargs["input_data"]["task_id"] == "pending-rebuild"


@pytest.mark.asyncio
async def test_retry_pending_tasks_endpoint_batches_retryable_pending_tasks(
    test_db: AsyncSession,
    test_project_db,
    test_user,
):
    retryable = DBTaskLog(
        id="pending-refresh",
        group_id=test_project_db.id,
        task_type="incremental_refresh",
        status="PENDING",
        payload={"group_id": test_project_db.id},
        created_at=datetime.now(UTC),
    )
    unsupported = DBTaskLog(
        id="pending-unsupported",
        group_id="project-1",
        task_type="unknown",
        status="PENDING",
        payload={},
        created_at=datetime.now(UTC),
    )
    test_db.add_all([retryable, unsupported])
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_pending_tasks_endpoint(
        limit=10,
        task_type=None,
        current_user=test_user,
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(retryable)
    await test_db.refresh(unsupported)
    assert response.submitted == 1
    assert response.skipped == 0
    assert response.task_ids == ["pending-refresh"]
    assert retryable.retry_count == 1
    assert retryable.payload["task_id"] == "pending-refresh"
    assert unsupported.retry_count == 0
    workflow_engine.start_workflow.assert_awaited_once()
    assert (
        workflow_engine.start_workflow.await_args.kwargs["workflow_name"] == "incremental_refresh"
    )


@pytest.mark.asyncio
async def test_retry_pending_tasks_endpoint_can_include_failed_tasks(
    test_db: AsyncSession,
    test_project_db,
    test_user,
):
    failed_task = DBTaskLog(
        id="failed-add-episode",
        group_id=test_project_db.id,
        task_type="add_episode",
        status="FAILED",
        payload={
            "uuid": "memory-2",
            "content": "Grace Hopper worked on compiler systems.",
            "project_id": test_project_db.id,
            "memory_id": "memory-2",
        },
        error_message="transient schema conflict",
        progress=100,
        created_at=datetime.now(UTC),
    )
    test_db.add(failed_task)
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_pending_tasks_endpoint(
        limit=10,
        task_type="add_episode",
        include_failed=True,
        current_user=test_user,
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(failed_task)
    assert response.submitted == 1
    assert response.task_ids == ["failed-add-episode"]
    assert failed_task.status == "PENDING"
    assert failed_task.error_message is None
    assert failed_task.retry_count == 1
    workflow_engine.start_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_pending_tasks_endpoint_skips_missing_project(test_db: AsyncSession):
    missing_project_id = "00000000-0000-0000-0000-000000000000"
    failed_task = DBTaskLog(
        id="failed-missing-project",
        group_id=missing_project_id,
        task_type="add_episode",
        status="FAILED",
        payload={
            "uuid": "memory-missing-project",
            "content": "This historical task references a deleted project.",
            "project_id": missing_project_id,
            "memory_id": "memory-missing-project",
        },
        error_message="previous failure",
        progress=100,
        created_at=datetime.now(UTC),
    )
    test_db.add(failed_task)
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_pending_tasks_endpoint(
        limit=10,
        task_type="add_episode",
        include_failed=True,
        current_user=SimpleNamespace(id="system-admin", is_superuser=True),
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(failed_task)
    assert response.submitted == 0
    assert response.skipped == 1
    assert failed_task.status == "FAILED"
    assert failed_task.message == tasks_router._UNRETRYABLE_RETRY_MESSAGE
    assert "no longer exists" in (failed_task.error_message or "")
    workflow_engine.start_workflow.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_pending_tasks_endpoint_can_include_stale_processing_tasks(
    test_db: AsyncSession,
    test_project_db,
    test_user,
):
    stale_task = DBTaskLog(
        id="stale-processing-refresh",
        group_id=test_project_db.id,
        task_type="incremental_refresh",
        status="PROCESSING",
        payload={"group_id": test_project_db.id},
        progress=10,
        message="stale processing",
        started_at=datetime.now(UTC) - timedelta(hours=1),
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    fresh_task = DBTaskLog(
        id="fresh-processing-refresh",
        group_id=test_project_db.id,
        task_type="incremental_refresh",
        status="PROCESSING",
        payload={"group_id": test_project_db.id},
        progress=10,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    test_db.add_all([stale_task, fresh_task])
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_pending_tasks_endpoint(
        limit=10,
        task_type="incremental_refresh",
        include_stale_processing=True,
        stale_after_minutes=15,
        current_user=test_user,
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(stale_task)
    await test_db.refresh(fresh_task)
    assert response.submitted == 1
    assert response.task_ids == ["stale-processing-refresh"]
    assert stale_task.status == "PENDING"
    assert stale_task.started_at is None
    assert stale_task.retry_count == 1
    assert fresh_task.status == "PROCESSING"
    assert fresh_task.retry_count == 0
    workflow_engine.start_workflow.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_pending_tasks_endpoint_creates_tasks_for_orphan_pending_memories(
    test_db: AsyncSession,
    test_project_db,
    test_user,
):
    memory = Memory(
        id="orphan-memory",
        project_id=test_project_db.id,
        title="Orphan historical memory",
        content="Ada Lovelace and Charles Babbage collaborated on analytical engines.",
        author_id=test_user.id,
        processing_status="PENDING",
        task_id=None,
        created_at=datetime.now(UTC),
    )
    test_db.add(memory)
    await test_db.commit()
    workflow_engine = SimpleNamespace(start_workflow=AsyncMock())

    response = await tasks_router.retry_pending_tasks_endpoint(
        limit=1,
        task_type="add_episode",
        current_user=test_user,
        db=test_db,
        workflow_engine=workflow_engine,
    )

    await test_db.refresh(memory)
    assert response.submitted == 1
    assert response.skipped == 0
    assert memory.task_id is not None
    assert response.task_ids == [memory.task_id]

    task = await test_db.get(DBTaskLog, memory.task_id)
    assert task is not None
    assert task.task_type == "add_episode"
    assert task.payload["memory_id"] == "orphan-memory"
    assert task.payload["tenant_id"] == test_project_db.tenant_id
    assert task.payload["task_id"] == memory.task_id
    workflow_engine.start_workflow.assert_awaited_once()
    call_kwargs = workflow_engine.start_workflow.await_args.kwargs
    assert call_kwargs["workflow_name"] == "episode_processing"
    assert call_kwargs["input_data"]["memory_id"] == "orphan-memory"


@pytest.mark.asyncio
async def test_retry_task_endpoint_checks_status_before_mutating_task(test_db: AsyncSession):
    task = DBTaskLog(
        id="processing-add-episode",
        group_id="project-1",
        task_type="add_episode",
        status="PROCESSING",
        payload={"uuid": "memory-1", "content": "Ada"},
        progress=40,
        created_at=datetime.now(UTC),
    )
    test_db.add(task)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await tasks_router.retry_task_endpoint(
            "processing-add-episode",
            current_user=SimpleNamespace(id="system-admin", is_superuser=True),
            db=test_db,
            workflow_engine=SimpleNamespace(start_workflow=AsyncMock()),
        )

    await test_db.refresh(task)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert task.status == "PROCESSING"
    assert task.progress == 40
