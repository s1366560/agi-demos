from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers import tenants as tenants_router
from src.infrastructure.adapters.primary.web.routers.tenants import (
    _get_project_memory_stats,
    get_tenant_analytics,
    get_tenant_stats,
)
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


@pytest.mark.unit
async def test_get_tenant_stats_uses_batched_project_memory_stats(
    monkeypatch: pytest.MonkeyPatch,
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_project_db: Project,
    test_user: User,
) -> None:
    empty_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Empty Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    test_db.add(empty_project)
    await test_db.commit()

    captured_batches: list[list[str]] = []

    async def fake_project_memory_stats(
        db: AsyncSession,
        project_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        captured_batches.append(project_ids)
        return {
            test_project_db.id: {
                "storage_bytes": 2048,
                "memory_count": 1,
            }
        }

    monkeypatch.setattr(
        tenants_router,
        "_get_project_memory_stats",
        fake_project_memory_stats,
    )

    stats = await tenants_router.get_tenant_stats(
        test_tenant_db.id,
        current_user=test_user,
        db=test_db,
    )

    assert len(captured_batches) == 1
    assert {test_project_db.id, empty_project.id}.issubset(set(captured_batches[0]))
    projects_by_id = {item["id"]: item for item in stats["projects"]["list"]}
    assert projects_by_id[test_project_db.id]["memory_consumed"] == "2.0 KB"
    assert projects_by_id[empty_project.id]["memory_consumed"] == "0.0 KB"


@pytest.mark.unit
async def test_get_project_memory_stats_batches_totals_by_project(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    test_db.add_all(
        [
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="First memory",
                content="abc",
                author_id=test_user.id,
            ),
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Second memory",
                content="abcdef",
                author_id=test_user.id,
            ),
        ]
    )
    await test_db.commit()

    stats = await _get_project_memory_stats(test_db, [test_project_db.id, "project-without-memory"])

    assert stats == {
        test_project_db.id: {
            "storage_bytes": 9,
            "memory_count": 2,
        }
    }


@pytest.mark.unit
async def test_get_tenant_analytics_uses_batched_project_memory_stats(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_project_db: Project,
    test_user: User,
) -> None:
    empty_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Empty Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    test_db.add(empty_project)
    test_db.add_all(
        [
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Alpha",
                content="alpha",
                author_id=test_user.id,
            ),
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Beta",
                content="betabet",
                author_id=test_user.id,
            ),
        ]
    )
    await test_db.commit()

    analytics = await get_tenant_analytics(
        test_tenant_db.id,
        current_user=test_user,
        db=test_db,
    )

    project_storage = {item["name"]: item for item in analytics["projectStorage"]}
    assert project_storage["Test Project"]["storage_bytes"] == 12
    assert project_storage["Test Project"]["memory_count"] == 2
    assert project_storage["Empty Project"]["storage_bytes"] == 0
    assert project_storage["Empty Project"]["memory_count"] == 0
    assert analytics["summary"]["total_memories"] == 2
    assert analytics["summary"]["total_storage_bytes"] == 12
    assert analytics["summary"]["total_projects"] == 2
