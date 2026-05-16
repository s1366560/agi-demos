from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.primary.web.routers import tasks as tasks_router
from src.infrastructure.adapters.secondary.persistence.models import (
    APIKey as DBAPIKey,
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
            group_id="proj_123",
            task_type="rebuild",
            status="COMPLETED",
            created_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
    )
    await test_db.commit()

    response = await authenticated_async_client.get("/api/v1/tasks/stream-complete/stream")

    assert response.status_code == status.HTTP_200_OK
    assert "event: completed" in response.text
