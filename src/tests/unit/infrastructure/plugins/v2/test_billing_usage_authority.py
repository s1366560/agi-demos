"""Billing derives tenant-wide usage and quotas from persisted records."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, Tenant, User
from src.infrastructure.plugins.v2.billing_services import (
    BillingApplicationServiceV2,
    SqlBillingPersistenceV2,
)

pytestmark = pytest.mark.unit


async def test_billing_counts_storage_and_members_without_project_membership(
    test_db: AsyncSession, test_tenant_db: Tenant, test_user: User
) -> None:
    tenant = test_tenant_db
    tenant.max_projects = 17
    tenant.max_users = 9
    project = Project(
        id=str(uuid4()), tenant_id=tenant.id, name="Billing scope", owner_id=test_user.id
    )
    test_db.add(project)
    await test_db.flush()
    test_db.add(
        Memory(
            id=str(uuid4()),
            project_id=project.id,
            title="Usage",
            content="Persisted memory content",
            author_id=test_user.id,
        )
    )
    await test_db.flush()

    service = BillingApplicationServiceV2(persistence=SqlBillingPersistenceV2(_session=test_db))
    result = await service.get_billing_info(user_id=test_user.id, tenant_id=tenant.id)

    assert result["usage"] == {
        "projects": 1,
        "memories": 1,
        "users": 1,
        "storage": len("Persisted memory content"),
    }
    assert result["tenant"]["projects_limit"] == 17
    assert result["tenant"]["users_limit"] == 9
