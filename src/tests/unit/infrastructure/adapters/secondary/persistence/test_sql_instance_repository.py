from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import InstanceModel, Project, User
from src.infrastructure.adapters.secondary.persistence.sql_instance_repository import (
    SqlInstanceRepository,
)


def _instance(
    *,
    instance_id: str,
    tenant_id: str,
    created_by: str,
    workspace_id: str | None = None,
    cluster_id: str | None = None,
    deleted_at: datetime | None = None,
) -> InstanceModel:
    return InstanceModel(
        id=instance_id,
        name=instance_id,
        slug=instance_id,
        tenant_id=tenant_id,
        service_type="ClusterIP",
        status="running",
        created_by=created_by,
        workspace_id=workspace_id,
        cluster_id=cluster_id,
        deleted_at=deleted_at,
    )


@pytest.mark.unit
async def test_instance_repository_lists_and_counts_only_active_rows(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    deleted_at = datetime.now(UTC)
    test_db.add_all(
        [
            _instance(
                instance_id="active-instance",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                workspace_id="workspace-1",
                cluster_id="cluster-1",
            ),
            _instance(
                instance_id="deleted-instance",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                workspace_id="workspace-1",
                cluster_id="cluster-1",
                deleted_at=deleted_at,
            ),
            _instance(
                instance_id="other-workspace-instance",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                workspace_id="workspace-2",
                cluster_id="cluster-2",
            ),
        ]
    )
    await test_db.flush()

    repo = SqlInstanceRepository(test_db)

    tenant_instances = await repo.find_by_tenant(test_project_db.tenant_id, limit=10, offset=0)
    workspace_instances = await repo.find_by_workspace("workspace-1")
    cluster_instances = await repo.find_by_cluster("cluster-1")
    tenant_count = await repo.count_by_tenant(test_project_db.tenant_id)

    assert {instance.id for instance in tenant_instances} == {
        "active-instance",
        "other-workspace-instance",
    }
    assert [instance.id for instance in workspace_instances] == ["active-instance"]
    assert [instance.id for instance in cluster_instances] == ["active-instance"]
    assert tenant_count == 2
