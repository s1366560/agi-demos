"""Generation-owned persistence and application seams for tenant billing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Invoice,
    Memory,
    Project,
    Tenant,
    UserTenant,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

BILLING_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/billing-provider"
BILLING_PROVIDER_SERVICE_V2 = "service:persistence.billing-provider"
BILLING_APPLICATION_MODULE_V2 = "builtin://memstack/application/billing-services"
BILLING_APPLICATION_SERVICE_V2 = "service:application.billing-services"
BILLING_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

_BILLING_ADMIN_ROLES_V2 = frozenset({"admin", "owner"})
_BILLING_OWNER_ROLES_V2 = frozenset({"owner"})
_DEFAULT_STORAGE_LIMIT_V2 = 10 * 1024 * 1024 * 1024
_PLAN_STORAGE_LIMITS_V2 = {
    "free": 10 * 1024 * 1024 * 1024,
    "pro": 100 * 1024 * 1024 * 1024,
    "enterprise": 1024 * 1024 * 1024 * 1024,
}


class BillingServiceErrorV2(Exception):
    """Base class for typed billing application failures."""


class BillingAdminAccessDeniedV2(BillingServiceErrorV2):
    """The operation identity cannot inspect tenant billing data."""


class BillingOwnerAccessDeniedV2(BillingServiceErrorV2):
    """The operation identity cannot change the tenant plan."""


class BillingTenantNotFoundV2(BillingServiceErrorV2):
    """The requested tenant does not exist."""


class BillingInvalidPlanV2(BillingServiceErrorV2):
    """The requested plan is not a supported billing plan."""


@dataclass(frozen=True, kw_only=True)
class BillingTenantRecordV2:
    """Persistence-neutral tenant fields used by billing responses."""

    id: str
    name: str
    plan: str
    storage_limit: int
    projects_limit: int | None = None
    users_limit: int | None = None


@dataclass(frozen=True, kw_only=True)
class BillingUsageRecordV2:
    """Tenant usage totals calculated inside the persistence boundary."""

    projects: int
    memories: int
    users: int
    storage: int


@dataclass(frozen=True, kw_only=True)
class BillingInvoiceRecordV2:
    """Persistence-neutral invoice fields used by billing responses."""

    id: str
    amount: int
    currency: str
    status: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    paid_at: datetime | None
    invoice_url: str | None


@runtime_checkable
class BillingPersistenceProtocolV2(Protocol):
    """Tenant-scoped SQL operations hidden behind the Provider contract."""

    async def role_for_user(self, *, user_id: str, tenant_id: str) -> str | None: ...

    async def get_tenant(self, *, tenant_id: str) -> BillingTenantRecordV2 | None: ...

    async def get_usage(self, *, tenant_id: str) -> BillingUsageRecordV2: ...

    async def list_invoices(
        self,
        *,
        tenant_id: str,
        limit: int | None,
    ) -> Sequence[BillingInvoiceRecordV2]: ...

    async def update_plan(
        self,
        *,
        tenant_id: str,
        plan: str,
        storage_limit: int,
    ) -> BillingTenantRecordV2 | None: ...


@dataclass(frozen=True, kw_only=True)
class SqlBillingPersistenceV2:
    """SQL billing persistence bound to one operation-owned session."""

    _session: AsyncSession

    async def role_for_user(self, *, user_id: str, tenant_id: str) -> str | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserTenant.role).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
        )
        role = result.scalar_one_or_none()
        return str(role) if role is not None else None

    async def get_tenant(self, *, tenant_id: str) -> BillingTenantRecordV2 | None:
        tenant = await self._tenant_model(tenant_id=tenant_id)
        return _tenant_record_v2(tenant) if tenant is not None else None

    async def get_usage(self, *, tenant_id: str) -> BillingUsageRecordV2:
        projects_result = await self._session.execute(
            refresh_select_statement(select(Project).where(Project.tenant_id == tenant_id))
        )
        projects = projects_result.scalars().all()
        project_ids = [project.id for project in projects]

        memories_result = await self._session.execute(
            refresh_select_statement(
                select(func.count(Memory.id)).where(Memory.project_id.in_(project_ids))
            )
        )
        users_result = await self._session.execute(
            refresh_select_statement(
                select(func.count(UserTenant.id)).where(UserTenant.tenant_id == tenant_id)
            )
        )
        storage_result = await self._session.execute(
            refresh_select_statement(
                select(func.sum(func.length(Memory.content))).where(
                    Memory.project_id.in_(project_ids)
                )
            )
        )
        return BillingUsageRecordV2(
            projects=len(projects),
            memories=int(memories_result.scalar() or 0),
            users=int(users_result.scalar() or 0),
            storage=int(storage_result.scalar() or 0),
        )

    async def list_invoices(
        self,
        *,
        tenant_id: str,
        limit: int | None,
    ) -> Sequence[BillingInvoiceRecordV2]:
        query = (
            select(Invoice)
            .where(Invoice.tenant_id == tenant_id)
            .order_by(Invoice.created_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(refresh_select_statement(query))
        return tuple(_invoice_record_v2(invoice) for invoice in result.scalars().all())

    async def update_plan(
        self,
        *,
        tenant_id: str,
        plan: str,
        storage_limit: int,
    ) -> BillingTenantRecordV2 | None:
        tenant = await self._tenant_model(tenant_id=tenant_id)
        if tenant is None:
            return None
        tenant.plan = plan
        tenant.max_storage = storage_limit
        await self._session.flush()
        return _tenant_record_v2(tenant)

    async def _tenant_model(self, *, tenant_id: str) -> Tenant | None:
        return await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).execution_options(populate_existing=True)
        )


def _tenant_record_v2(tenant: Tenant) -> BillingTenantRecordV2:
    return BillingTenantRecordV2(
        id=tenant.id,
        name=tenant.name,
        plan=getattr(tenant, "plan", "free"),
        storage_limit=getattr(tenant, "max_storage", _DEFAULT_STORAGE_LIMIT_V2),
        projects_limit=tenant.max_projects,
        users_limit=tenant.max_users,
    )


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

    persistence: BillingPersistenceProtocolV2

    async def get_billing_info(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        await self._require_admin(user_id=user_id, tenant_id=tenant_id)
        tenant = await self._tenant_or_error(tenant_id=tenant_id)
        usage = await self.persistence.get_usage(tenant_id=tenant_id)
        invoices = await self.persistence.list_invoices(tenant_id=tenant_id, limit=12)
        return {
            "tenant": _tenant_payload_v2(tenant),
            "usage": {
                "projects": usage.projects,
                "memories": usage.memories,
                "users": usage.users,
                "storage": usage.storage,
            },
            "invoices": [_invoice_payload_v2(invoice) for invoice in invoices],
        }

    async def list_invoices(self, *, user_id: str, tenant_id: str) -> dict[str, Any]:
        await self._require_admin(user_id=user_id, tenant_id=tenant_id)
        _ = await self._tenant_or_error(tenant_id=tenant_id)
        invoices = await self.persistence.list_invoices(tenant_id=tenant_id, limit=None)
        return {"invoices": [_invoice_payload_v2(invoice) for invoice in invoices]}

    async def upgrade_plan(
        self,
        *,
        user_id: str,
        tenant_id: str,
        plan_data: Mapping[str, Any],
    ) -> dict[str, Any]:
        await self._require_owner(user_id=user_id, tenant_id=tenant_id)
        _ = await self._tenant_or_error(tenant_id=tenant_id)
        plan = plan_data.get("plan") or "pro"
        if not isinstance(plan, str) or plan not in _PLAN_STORAGE_LIMITS_V2:
            raise BillingInvalidPlanV2
        tenant = await self.persistence.update_plan(
            tenant_id=tenant_id,
            plan=plan,
            storage_limit=_PLAN_STORAGE_LIMITS_V2[plan],
        )
        if tenant is None:
            raise BillingTenantNotFoundV2
        return _tenant_payload_v2(tenant)

    async def _require_admin(self, *, user_id: str, tenant_id: str) -> None:
        role = await self.persistence.role_for_user(user_id=user_id, tenant_id=tenant_id)
        if role not in _BILLING_ADMIN_ROLES_V2:
            raise BillingAdminAccessDeniedV2

    async def _require_owner(self, *, user_id: str, tenant_id: str) -> None:
        role = await self.persistence.role_for_user(user_id=user_id, tenant_id=tenant_id)
        if role not in _BILLING_OWNER_ROLES_V2:
            raise BillingOwnerAccessDeniedV2

    async def _tenant_or_error(self, *, tenant_id: str) -> BillingTenantRecordV2:
        tenant = await self.persistence.get_tenant(tenant_id=tenant_id)
        if tenant is None:
            raise BillingTenantNotFoundV2
        return tenant


def _tenant_payload_v2(tenant: BillingTenantRecordV2) -> dict[str, Any]:
    return {
        "id": tenant.id,
        "name": tenant.name,
        "plan": tenant.plan,
        "storage_limit": tenant.storage_limit,
        "projects_limit": tenant.projects_limit,
        "users_limit": tenant.users_limit,
    }


def _invoice_payload_v2(invoice: BillingInvoiceRecordV2) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "amount": invoice.amount,
        "currency": invoice.currency,
        "status": invoice.status,
        "period_start": invoice.period_start.isoformat(),
        "period_end": invoice.period_end.isoformat(),
        "created_at": invoice.created_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "invoice_url": invoice.invoice_url,
    }


@dataclass(frozen=True, kw_only=True)
class BillingApplicationServicesV2:
    """Operation-owned Billing application services consumed by HTTP handlers."""

    billing: BillingApplicationServiceV2


@runtime_checkable
class BillingServiceFactoryProtocolV2(Protocol):
    """Build Billing persistence without exposing SQL implementations to Consumers."""

    def build(self, operation: OperationContextV2) -> BillingPersistenceProtocolV2: ...


@runtime_checkable
class BillingApplicationResolverProtocolV2(Protocol):
    """Resolve Billing services through the Provider alias declared by the Profile."""

    def resolve(self, operation: OperationContextV2) -> BillingApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlBillingServiceFactoryV2:
    """Bind Billing persistence to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> BillingPersistenceProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "billing services require an AsyncSession operation service",
            )
        return SqlBillingPersistenceV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class BillingApplicationResolverV2:
    """Consumer seam for the explicitly selected Billing persistence Provider."""

    provider: BillingServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> BillingApplicationServicesV2:
        persistence = self.provider.build(operation)
        return BillingApplicationServicesV2(
            billing=BillingApplicationServiceV2(persistence=persistence)
        )


def _apply_billing_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("billing provider requires strategy operation-async-session")
    _ = context.provide(
        BILLING_PROVIDER_SERVICE_V2,
        SqlBillingServiceFactoryV2(),
        label="billing-provider",
    )


def _apply_billing_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("billing resolver requires strategy operation-scoped-provider")
    provider = context.require(BILLING_PROVIDER_INJECT_V2)
    if not isinstance(provider, BillingServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_billing_provider",
            "billing provider inject does not implement the factory contract",
        )
    _ = context.provide(
        BILLING_APPLICATION_SERVICE_V2,
        BillingApplicationResolverV2(provider=provider),
        label="billing-application",
    )


def billing_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Billing persistence Provider and application Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=BILLING_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BILLING_PROVIDER_MODULE_V2),
            apply=_apply_billing_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=BILLING_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BILLING_APPLICATION_MODULE_V2),
            apply=_apply_billing_application_v2,
        ),
    )


__all__ = [
    "BILLING_APPLICATION_MODULE_V2",
    "BILLING_APPLICATION_SERVICE_V2",
    "BILLING_PROVIDER_INJECT_V2",
    "BILLING_PROVIDER_MODULE_V2",
    "BILLING_PROVIDER_SERVICE_V2",
    "BillingAdminAccessDeniedV2",
    "BillingApplicationResolverProtocolV2",
    "BillingApplicationResolverV2",
    "BillingApplicationServiceV2",
    "BillingApplicationServicesV2",
    "BillingInvalidPlanV2",
    "BillingOwnerAccessDeniedV2",
    "BillingPersistenceProtocolV2",
    "BillingServiceFactoryProtocolV2",
    "BillingTenantNotFoundV2",
    "SqlBillingPersistenceV2",
    "SqlBillingServiceFactoryV2",
    "billing_service_definitions_v2",
]
