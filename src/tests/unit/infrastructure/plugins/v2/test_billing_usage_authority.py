"""Billing derives tenant-wide usage and quotas from persisted records."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from plugins.business.billing.backend.policy import load_policy
from plugins.business.billing.backend.service import BillingInvoices
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, Tenant, User
from src.infrastructure.adapters.secondary.persistence.sql_tenant_entitlements import (
    SqlTenantEntitlements,
)
from src.infrastructure.plugins.v2.billing_services import (
    BillingApplicationServiceV2,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def policy():
    host = load_policy()
    try:
        yield host
    finally:
        host.close()


async def test_billing_counts_storage_and_members_without_project_membership(
    test_db: AsyncSession, test_tenant_db: Tenant, test_user: User, policy
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

    service = BillingApplicationServiceV2(
        policy=policy,
        persistence=BillingInvoices(_session=test_db, tenant_id=tenant.id),
        entitlements=SqlTenantEntitlements(
            session=test_db, user_id=test_user.id, tenant_id=tenant.id
        ),
        user_id=test_user.id,
    )
    result = await service.get_billing_info(user_id=test_user.id, tenant_id=tenant.id)

    assert result["usage"] == {
        "projects": 1,
        "memories": 1,
        "users": 1,
        "storage": len("Persisted memory content"),
    }
    assert result["tenant"]["projects_limit"] == 17
    assert result["tenant"]["users_limit"] == 9


async def test_quota_update_checks_scope_request_identity_and_current_membership(
    test_db: AsyncSession, test_tenant_db: Tenant, test_user: User, policy
) -> None:
    from sqlalchemy import update

    from src.domain.ports.services.tenant_entitlement_port import (
        TenantQuotaAccessDenied,
        TenantUsageAccessDenied,
    )
    from src.infrastructure.adapters.secondary.persistence.models import UserTenant

    tenant = test_tenant_db
    access = SqlTenantEntitlements(session=test_db, user_id=test_user.id, tenant_id=tenant.id)
    service = BillingApplicationServiceV2(
        policy=policy,
        persistence=BillingInvoices(_session=test_db, tenant_id=tenant.id),
        entitlements=access,
        user_id=test_user.id,
    )
    with pytest.raises(TenantUsageAccessDenied):
        await service.list_invoices(user_id=test_user.id, tenant_id="different")
    with pytest.raises(TenantQuotaAccessDenied):
        await service.upgrade_plan(
            user_id="impersonated", tenant_id=tenant.id, plan_data={"plan": "pro"}
        )
    await test_db.execute(
        update(UserTenant)
        .where(UserTenant.tenant_id == tenant.id, UserTenant.user_id == test_user.id)
        .values(role="admin")
    )
    await test_db.commit()
    with pytest.raises(TenantQuotaAccessDenied):
        await access.update_quota(plan="pro", storage_limit=99)
    assert (await service.get_billing_info(user_id=test_user.id, tenant_id=tenant.id))["tenant"][
        "plan"
    ] == "free"


async def test_package_migration_creates_and_adopts_invoices_without_resetting_them(
    tmp_path,
) -> None:
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from plugins.business.billing.migration import migrate_invoices

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'billing.sqlite'}")
    sessions = async_sessionmaker(engine)
    try:
        # The tenancy domain is installed before billing; the package owns its own revision.
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE tenants(id VARCHAR PRIMARY KEY)"))
        await migrate_invoices(sessions)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO invoices (id,tenant_id,amount,currency,status,period_start,period_end) "
                    "VALUES ('i1','t1',50,'USD','paid',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            # Existing deployments already contain invoices when the new package first stages.
            await conn.execute(text("DROP TABLE billing_alembic_version"))
        await migrate_invoices(sessions)
        await migrate_invoices(sessions)
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT amount FROM invoices WHERE id='i1'")) == 50
            assert await conn.scalar(text("SELECT version_num FROM billing_alembic_version"))
            indexes = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("invoices")
            )
            assert any(index["name"] == "ix_billing_invoice_tenant_created" for index in indexes)
    finally:
        await engine.dispose()
