from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import ClusterModel, Project, User
from src.infrastructure.adapters.secondary.persistence.sql_cluster_repository import (
    SqlClusterRepository,
)


def _cluster(
    *,
    cluster_id: str,
    tenant_id: str,
    created_by: str,
    deleted_at: datetime | None = None,
) -> ClusterModel:
    return ClusterModel(
        id=cluster_id,
        name=cluster_id,
        tenant_id=tenant_id,
        compute_provider="docker",
        status="disconnected",
        created_by=created_by,
        provider_config={},
        deleted_at=deleted_at,
    )


@pytest.mark.unit
async def test_cluster_repository_lists_and_counts_only_active_rows(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    deleted_at = datetime.now(UTC)
    test_db.add_all(
        [
            _cluster(
                cluster_id="active-cluster",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
            ),
            _cluster(
                cluster_id="deleted-cluster",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                deleted_at=deleted_at,
            ),
            _cluster(
                cluster_id="second-active-cluster",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
            ),
        ]
    )
    await test_db.flush()

    repo = SqlClusterRepository(test_db)

    listed = await repo.find_by_tenant(test_project_db.tenant_id, limit=1, offset=0)
    total = await repo.count_by_tenant(test_project_db.tenant_id)
    deleted_detail = await repo.find_by_id("deleted-cluster")
    deleted_by_name = await repo.find_by_name(test_project_db.tenant_id, "deleted-cluster")

    assert len(listed) == 1
    assert listed[0].id in {"active-cluster", "second-active-cluster"}
    assert total == 2
    assert deleted_detail is None
    assert deleted_by_name is None
