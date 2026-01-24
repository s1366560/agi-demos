from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.secondary.persistence.models import TaskLog as DBTaskLog

app = create_app()


@pytest.mark.asyncio
async def test_tasks_endpoints(authenticated_async_client, test_db: AsyncSession):
    client: AsyncClient = authenticated_async_client

    now = datetime.now(timezone.utc)
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
