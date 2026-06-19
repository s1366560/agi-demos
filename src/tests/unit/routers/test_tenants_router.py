from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.tenants import (
    get_tenant_analytics,
    get_tenant_stats,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)


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
    assert stats["projects"]["list"][0]["status"] == "active"

    yesterday = next(
        point for point in history if point["date"] == (now.date() - timedelta(days=1)).isoformat()
    )
    assert yesterday["used"] == 13
    assert yesterday["daily_added"] == 3
    assert yesterday["memory_count"] == 1


@pytest.mark.unit
async def test_get_tenant_stats_returns_top_projects_by_memory_usage(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_project_db: Project,
    test_user: User,
) -> None:
    busy_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Busy Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    empty_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Empty Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    test_db.add_all(
        [
            busy_project,
            empty_project,
            UserProject(
                id=str(uuid4()),
                user_id=test_user.id,
                project_id=busy_project.id,
                role="owner",
                permissions={"admin": True, "read": True, "write": True},
            ),
            UserProject(
                id=str(uuid4()),
                user_id=test_user.id,
                project_id=empty_project.id,
                role="owner",
                permissions={"admin": True, "read": True, "write": True},
            ),
            Memory(
                id=str(uuid4()),
                project_id=busy_project.id,
                title="Busy memory",
                content="x" * 4096,
                author_id=test_user.id,
            ),
            Memory(
                id=str(uuid4()),
                project_id=test_project_db.id,
                title="Regular memory",
                content="x" * 2048,
                author_id=test_user.id,
            ),
        ]
    )
    await test_db.commit()

    stats = await get_tenant_stats(
        test_tenant_db.id,
        current_user=test_user,
        db=test_db,
    )

    assert stats["projects"]["active"] == 3
    project_ids = [item["id"] for item in stats["projects"]["list"]]
    assert project_ids[:3] == [busy_project.id, test_project_db.id, empty_project.id]
    projects_by_id = {item["id"]: item for item in stats["projects"]["list"]}
    assert projects_by_id[busy_project.id]["memory_consumed"] == "4.0 KB"
    assert projects_by_id[test_project_db.id]["memory_consumed"] == "2.0 KB"
    assert projects_by_id[empty_project.id]["memory_consumed"] == "0.0 KB"
    assert all(item["status"] == "active" for item in stats["projects"]["list"])


@pytest.mark.unit
async def test_get_tenant_stats_does_not_treat_owner_id_without_membership_as_project_access(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_project_db: Project,
    test_user: User,
) -> None:
    orphan_owned_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Orphan Owned Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    test_db.add_all(
        [
            orphan_owned_project,
            Memory(
                id=str(uuid4()),
                project_id=orphan_owned_project.id,
                title="Hidden orphan memory",
                content="x" * 4096,
                author_id=test_user.id,
            ),
        ]
    )
    await test_db.commit()

    stats = await get_tenant_stats(test_tenant_db.id, current_user=test_user, db=test_db)

    project_ids = [item["id"] for item in stats["projects"]["list"]]
    assert test_project_db.id in project_ids
    assert orphan_owned_project.id not in project_ids


@pytest.mark.unit
async def test_get_tenant_stats_scopes_member_project_list_to_accessible_projects(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    another_user: User,
    test_user: User,
) -> None:
    member_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Member Project",
        owner_id=another_user.id,
        memory_rules={},
        graph_config={},
    )
    inaccessible_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Inaccessible Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    test_db.add_all(
        [
            UserTenant(
                id=str(uuid4()),
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="member",
                permissions={"read": True},
            ),
            member_project,
            inaccessible_project,
            UserProject(
                id=str(uuid4()),
                user_id=another_user.id,
                project_id=member_project.id,
                role="member",
                permissions={"read": True},
            ),
            Memory(
                id=str(uuid4()),
                project_id=member_project.id,
                title="Member memory",
                content="x" * 1024,
                author_id=another_user.id,
            ),
            Memory(
                id=str(uuid4()),
                project_id=inaccessible_project.id,
                title="Hidden memory",
                content="x" * 4096,
                author_id=test_user.id,
            ),
        ]
    )
    await test_db.commit()

    stats = await get_tenant_stats(test_tenant_db.id, current_user=another_user, db=test_db)

    assert stats["projects"]["active"] == 1
    assert stats["storage"]["used"] == 1024
    assert [item["id"] for item in stats["projects"]["list"]] == [member_project.id]
    assert stats["projects"]["list"][0]["name"] == "Member Project"


@pytest.mark.unit
async def test_get_tenant_stats_does_not_treat_tenant_admin_role_as_project_access(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    another_user: User,
    test_user: User,
) -> None:
    accessible_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Admin Joined Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    inaccessible_project = Project(
        id=str(uuid4()),
        tenant_id=test_tenant_db.id,
        name="Admin Hidden Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    test_db.add_all(
        [
            UserTenant(
                id=str(uuid4()),
                user_id=another_user.id,
                tenant_id=test_tenant_db.id,
                role="admin",
                permissions={"read": True, "manage_users": True},
            ),
            accessible_project,
            inaccessible_project,
            UserProject(
                id=str(uuid4()),
                user_id=another_user.id,
                project_id=accessible_project.id,
                role="admin",
                permissions={"read": True, "write": True},
            ),
            Memory(
                id=str(uuid4()),
                project_id=accessible_project.id,
                title="Visible memory",
                content="x" * 512,
                author_id=another_user.id,
            ),
            Memory(
                id=str(uuid4()),
                project_id=inaccessible_project.id,
                title="Hidden memory",
                content="x" * 2048,
                author_id=test_user.id,
            ),
        ]
    )
    await test_db.commit()

    stats = await get_tenant_stats(test_tenant_db.id, current_user=another_user, db=test_db)

    assert stats["projects"]["active"] == 1
    assert stats["storage"]["used"] == 512
    assert [item["id"] for item in stats["projects"]["list"]] == [accessible_project.id]
    assert stats["projects"]["list"][0]["name"] == "Admin Joined Project"


@pytest.mark.unit
async def test_get_tenant_analytics_returns_project_storage_and_summary(
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


@pytest.mark.unit
async def test_get_tenant_analytics_limits_project_storage_without_truncating_summary(
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
        project_storage_limit=1,
        current_user=test_user,
        db=test_db,
    )

    assert analytics["projectStorage"] == [
        {
            "name": "Test Project",
            "storage_bytes": 12,
            "memory_count": 2,
        }
    ]
    assert analytics["summary"]["total_memories"] == 2
    assert analytics["summary"]["total_storage_bytes"] == 12
    assert analytics["summary"]["total_projects"] == 2
