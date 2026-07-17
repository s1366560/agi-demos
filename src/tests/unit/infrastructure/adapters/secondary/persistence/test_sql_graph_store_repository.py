"""Tests for SQL graph store repository batch lookups."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    GraphStoreModel,
    Tenant,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_graph_store_repository import (
    SqlGraphStoreRepository,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_by_ids_scopes_to_tenant_and_excludes_deleted(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            User(
                id="gs-user-1",
                email="gs-user-1@example.com",
                full_name="GS User",
                hashed_password="hash",
                is_active=True,
            ),
            Tenant(
                id="gs-tenant-1",
                name="GS Tenant",
                slug="gs-tenant",
                description="",
                owner_id="gs-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
            Tenant(
                id="gs-tenant-2",
                name="GS Tenant 2",
                slug="gs-tenant-2",
                description="",
                owner_id="gs-user-1",
                plan="free",
                max_projects=10,
                max_users=10,
                max_storage=1,
            ),
        ]
    )
    db_session.add_all(
        [
            GraphStoreModel(id="gs-store-1", name="store-1", tenant_id="gs-tenant-1"),
            GraphStoreModel(id="gs-store-2", name="store-2", tenant_id="gs-tenant-1"),
            GraphStoreModel(
                id="gs-store-deleted",
                name="store-deleted",
                tenant_id="gs-tenant-1",
                deleted_at=datetime.now(UTC),
            ),
            GraphStoreModel(id="gs-store-other", name="store-other", tenant_id="gs-tenant-2"),
        ]
    )
    await db_session.flush()

    repo = SqlGraphStoreRepository(db_session)
    stores = await repo.find_by_ids(
        "gs-tenant-1",
        ["gs-store-1", "gs-store-2", "gs-store-deleted", "gs-store-other", "gs-store-missing"],
    )

    assert sorted(stores) == ["gs-store-1", "gs-store-2"]
    assert stores["gs-store-1"].name == "store-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_by_ids_empty_input_skips_query(db_session: AsyncSession) -> None:
    repo = SqlGraphStoreRepository(db_session)

    assert await repo.find_by_ids("gs-tenant-1", []) == {}
