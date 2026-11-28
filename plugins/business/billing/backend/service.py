"""Tenant billing application and its invoice repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.domain.ports.services.tenant_entitlement_port import (
    TenantEntitlementPort,
    TenantQuota,
    TenantQuotaAccessDenied,
    TenantUsageAccessDenied,
)

from ..invoice_record import BillingInvoiceRecordV2, invoice_payload
from .invoices import Invoice
from .policy import quote

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.plugins.wasm_host import WasmToolHost


@dataclass(frozen=True, kw_only=True)
class BillingInvoices:
    _session: AsyncSession
    tenant_id: str

    async def list_invoices(self, limit: int | None) -> Sequence[BillingInvoiceRecordV2]:
        query = (
            select(Invoice)
            .where(Invoice.tenant_id == self.tenant_id)
            .order_by(Invoice.created_at.desc(), Invoice.id)
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.scalars(query.execution_options(populate_existing=True))
        return tuple(_invoice_record_v2(invoice) for invoice in result)


def _invoice_record_v2(invoice: Invoice) -> BillingInvoiceRecordV2:
    return BillingInvoiceRecordV2(
        id=invoice.id,
        amount=invoice.amount,
        currency=invoice.currency,
        status=invoice.status,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        created_at=invoice.created_at,
        paid_at=invoice.paid_at,
        invoice_url=invoice.invoice_url,
    )


@dataclass(frozen=True, kw_only=True)
class BillingApplicationServiceV2:
    """Tenant billing policy and response composition for one operation."""

    persistence: BillingInvoices
    policy: WasmToolHost
    entitlements: TenantEntitlementPort
    user_id: str

    def _check_identity(self, user_id: str, tenant_id: str, *, owner: bool = False) -> None:
        if self.user_id != user_id or self.persistence.tenant_id != tenant_id:
            if owner:
                raise TenantQuotaAccessDenied
            raise TenantUsageAccessDenied

    async def get_billing_info(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        self._check_identity(user_id, tenant_id)
        tenant = await self.entitlements.read_quota()
        usage = await self.entitlements.read_usage()
        invoices = await self.persistence.list_invoices(limit=12)
        return {
            "tenant": _tenant_payload_v2(tenant),
            "usage": {
                "projects": usage.projects,
                "memories": usage.memories,
                "users": usage.users,
                "storage": usage.storage,
            },
            "invoices": [invoice_payload(invoice) for invoice in invoices],
        }

    async def list_invoices(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        self._check_identity(user_id, tenant_id)
        _ = await self.entitlements.read_quota()
        invoices = await self.persistence.list_invoices(limit=None)
        return {"invoices": [invoice_payload(invoice) for invoice in invoices]}

    async def upgrade_plan(
        self,
        *,
        user_id: str,
        tenant_id: str,
        plan_data: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._check_identity(user_id, tenant_id, owner=True)
        await self.entitlements.authorize_quota_change()
        plan = plan_data.get("plan") or "pro"
        storage_limit = await quote(self.policy, plan, tenant_id)
        tenant = await self.entitlements.update_quota(
            plan=plan,
            storage_limit=storage_limit,
        )
        return _tenant_payload_v2(tenant)


def _tenant_payload_v2(tenant: TenantQuota) -> dict[str, Any]:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "plan": tenant.plan,
        "storage_limit": tenant.storage_limit,
        "projects_limit": tenant.projects_limit,
        "users_limit": tenant.users_limit,
    }
