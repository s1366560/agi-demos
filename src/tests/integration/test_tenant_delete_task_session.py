"""Tenant deletion coverage for project-backed task sessions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    TaskSessionCreationReceiptModel,
    Tenant,
    User,
    UserProject,
    UserTenant,
)


@pytest.fixture(autouse=True)
async def _tenants_v2_runtime(test_app):
    await initialize_plugin_runtime_v2(test_app)
    assert "tenants" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


@pytest.mark.integration
@pytest.mark.parametrize("cleanup_succeeds", [True, False])
async def test_delete_tenant_removes_project_task_session_roots(
    authenticated_async_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_succeeds: bool,
) -> None:
    from src.infrastructure.plugins.v2 import sandbox_projection

    # Keep this database deletion test independent of a running Docker adapter.
    purge = AsyncMock(side_effect=None if cleanup_succeeds else RuntimeError("cleanup failed"))
    monkeypatch.setattr(
        sandbox_projection,
        "current_sandbox_application_services_v2",
        lambda: SimpleNamespace(adapter=SimpleNamespace(purge_project_resources=purge)),
    )
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

    assert response.status_code == (204 if cleanup_succeeds else 503)
    purge.assert_awaited_once_with(tenant_id, project_id)
    for model, item_id in [
        (Tenant, tenant_id),
        (Project, project_id),
        (TaskSessionCreationReceiptModel, receipt_id),
    ]:
        result = await db.execute(select(model).where(model.id == item_id))
        assert (result.scalar_one_or_none() is None) is cleanup_succeeds
