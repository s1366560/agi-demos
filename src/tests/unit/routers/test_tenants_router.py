from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.tenants import get_tenant_stats
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, Tenant, User


@pytest.mark.unit
async def test_get_tenant_stats_returns_real_cumulative_memory_history(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_project_db: Project,
    test_user: User,
) -> None:
    now = datetime.now(UTC)
    test_tenant_db.max_storage = 100
    test_db.add_all(
        [
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Old memory",
                content="oldmemory0",
                author_id=test_user.id,
                created_at=now - timedelta(days=40),
            ),
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Yesterday memory",
                content="abc",
                author_id=test_user.id,
                created_at=now - timedelta(days=1),
            ),
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Today memory",
                content="abcd",
                author_id=test_user.id,
                created_at=now,
            ),
        ]
    )
    await test_db.commit()

    stats = await get_tenant_stats(test_tenant_db.id, current_user=test_user, db=test_db)

    history = stats["memory_history"]
    assert len(history) == 30
    assert history[-1]["date"] == now.date().isoformat()
    assert history[-1]["used"] == 17
    assert history[-1]["daily_added"] == 4
    assert history[-1]["memory_count"] == 1
    assert history[-1]["percentage"] == 17.0
    assert stats["tenant_info"]["region"] is None
    assert stats["tenant_info"]["next_billing_date"] is None
    assert stats["projects"]["list"][0]["status"] is None

    yesterday = next(
        point for point in history if point["date"] == (now.date() - timedelta(days=1)).isoformat()
    )
    assert yesterday["used"] == 13
    assert yesterday["daily_added"] == 3
    assert yesterday["memory_count"] == 1
