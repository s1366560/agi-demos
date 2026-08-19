"""Tenant deletion coverage for project-backed task sessions."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    TaskSessionCreationReceiptModel,
    Tenant,
    User,
    UserProject,
    UserTenant,
)


@pytest.mark.integration
async def test_delete_tenant_removes_project_task_session_roots(
    authenticated_async_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    tenant_id = str(uuid4())
    project_id = str(uuid4())
    receipt_id = str(uuid4())
    tenant = Tenant(
        id=tenant_id,
        name="Tenant with Task Session",
        slug=f"tenant-task-session-{tenant_id}",
        owner_id=test_user.id,
    )
    membership = UserTenant(
        id=str(uuid4()),
        user_id=test_user.id,
        tenant_id=tenant_id,
        role="owner",
        permissions={"admin": True},
    )
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        name="Task Session Project",
        owner_id=test_user.id,
        memory_rules={},
        graph_config={},
    )
    project_membership = UserProject(
        id=str(uuid4()),
        user_id=test_user.id,
        project_id=project_id,
        role="owner",
        permissions={"admin": True},
    )
    # Workspace rows are Core-owned since c84f19b55; the receipt keeps the
    # workspace linkage as a plain string.
    receipt = TaskSessionCreationReceiptModel(
        id=receipt_id,
        actor_user_id=test_user.id,
        tenant_id=tenant_id,
        project_id=project_id,
        idempotency_key="delete-tenant-task-session",
        payload_hash="b" * 64,
        workspace_id=str(uuid4()),
        response_json={"tombstone": True},
    )
    db.add_all(
        [
            tenant,
            membership,
            project,
            project_membership,
            receipt,
        ]
    )
    await db.commit()

    response = await authenticated_async_client.delete(f"/api/v1/tenants/{tenant_id}")

    assert response.status_code == 204
    for model, item_id in [
        (Tenant, tenant_id),
        (Project, project_id),
        (TaskSessionCreationReceiptModel, receipt_id),
    ]:
        result = await db.execute(select(model).where(model.id == item_id))
        assert result.scalar_one_or_none() is None
