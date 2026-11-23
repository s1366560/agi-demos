"""Real PostgreSQL migration, authorization and storage for the independently versioned package."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import select, text, update

from alembic import command
from plugins.business.billing.backend.invoices import Invoice
from plugins.business.billing.backend.policy import load_policy
from plugins.business.billing.backend.service import BillingApplicationServiceV2, BillingInvoices
from plugins.business.billing.migration import migrate_invoices
from src.domain.ports.services.tenant_entitlement_port import TenantQuotaAccessDenied
from src.infrastructure.adapters.secondary.persistence.models import Tenant, UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_tenant_entitlements import (
    SqlTenantEntitlements,
)
from src.tests.integration.test_knowledge_sync_postgres import (
    pg_sync as _pg_sync,
    pytestmark as pytestmark,
)

pg_sync = _pg_sync


async def test_installed_billing_migration_keeps_invoices_and_rechecks_quota_authority(pg_sync):
    sessions, scope = pg_sync
    await asyncio.gather(migrate_invoices(sessions), migrate_invoices(sessions))
    now = datetime.now(UTC)
    async with sessions() as session, session.begin():
        session.add(
            Invoice(
                id="billing-invoice",
                tenant_id=scope.tenant_id,
                amount=50,
                currency="USD",
                status="paid",
                period_start=now,
                period_end=now,
            )
        )

    def roll_back_package(connection):
        config = Config()
        config.set_main_option(
            "script_location",
            str(Path(__file__).parents[3] / "plugins/business/billing/migrations"),
        )
        config.attributes["connection"] = connection
        command.downgrade(config, "base")

    async with sessions.begin() as session:
        connection = await session.connection()
        await connection.run_sync(roll_back_package)
        assert await session.scalar(select(Invoice.id)) == "billing-invoice"
        assert await session.scalar(text("SELECT count(*) FROM billing_alembic_version")) == 0
    # Re-adopt the pre-existing invoice table after a package schema rollback.
    await migrate_invoices(sessions)
    host = load_policy()
    try:
        async with sessions() as session:
            access = SqlTenantEntitlements(
                session=session, tenant_id=scope.tenant_id, user_id=scope.actor_id
            )
            service = BillingApplicationServiceV2(
                persistence=BillingInvoices(_session=session, tenant_id=scope.tenant_id),
                entitlements=access,
                user_id=scope.actor_id,
                policy=host,
            )
            info = await service.get_billing_info(tenant_id=scope.tenant_id, user_id=scope.actor_id)
            assert [invoice["id"] for invoice in info["invoices"]] == ["billing-invoice"]
            assert await session.scalar(text("SELECT version_num FROM billing_alembic_version"))
            await service.upgrade_plan(
                tenant_id=scope.tenant_id, user_id=scope.actor_id, plan_data={"plan": "pro"}
            )
            await session.commit()
            async with sessions() as other, other.begin():
                await other.execute(
                    update(UserTenant)
                    .where(
                        UserTenant.tenant_id == scope.tenant_id,
                        UserTenant.user_id == scope.actor_id,
                    )
                    .values(role="member")
                )
            with pytest.raises(TenantQuotaAccessDenied):
                await service.upgrade_plan(
                    tenant_id=scope.tenant_id,
                    user_id=scope.actor_id,
                    plan_data={"plan": "enterprise"},
                )
            assert (
                await session.scalar(select(Tenant.max_storage).where(Tenant.id == scope.tenant_id))
                == 100 * 1024**3
            )
    finally:
        host.close()
