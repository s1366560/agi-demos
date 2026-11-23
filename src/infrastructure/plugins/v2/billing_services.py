"""Bind billing to the verified operation identity and tenant-owned quota capability."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from plugins.business.billing.backend.policy import BillingInvalidPlanV2, load_policy
from plugins.business.billing.backend.service import (
    BillingApplicationServiceV2,
    BillingInvoices,
)
from plugins.business.billing.migration import migrate_invoices
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.domain.ports.services.tenant_entitlement_port import (
    TenantEntitlementsNotFound as BillingTenantNotFoundV2,
    TenantQuotaAccessDenied as BillingOwnerAccessDeniedV2,
    TenantUsageAccessDenied as BillingAdminAccessDeniedV2,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_entitlements import (
    SqlTenantEntitlements,
)
from src.infrastructure.plugins.wasm_host import WasmToolHost

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


@dataclass(frozen=True, kw_only=True)
class BillingApplicationServicesV2:
    """Operation-owned Billing application services consumed by HTTP handlers."""

    billing: BillingApplicationServiceV2


@runtime_checkable
class BillingServiceFactoryProtocolV2(Protocol):
    """Build Billing persistence without exposing SQL implementations to Consumers."""

    def build(self, operation: OperationContextV2) -> BillingApplicationServiceV2: ...


@runtime_checkable
class BillingApplicationResolverProtocolV2(Protocol):
    """Resolve Billing services through the Provider alias declared by the Profile."""

    def resolve(self, operation: OperationContextV2) -> BillingApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlBillingServiceFactoryV2:
    """Bind Billing persistence to the operation's exact AsyncSession."""

    policy: WasmToolHost

    def build(self, operation: OperationContextV2) -> BillingApplicationServiceV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "billing services require an AsyncSession operation service",
            )
        scope = operation.context.scope
        identity = operation.require("service:operation.identity")
        if (
            scope.kind != ScopeKindV2.TENANT
            or not scope.tenant_id
            or not isinstance(identity, Mapping)
            or identity.get("tenant_id") != scope.tenant_id
            or not isinstance(user_id := identity.get("user_id"), str)
            or not user_id
        ):
            raise RuntimeV2Error(
                "invalid_billing_identity", "billing requires a bound tenant member"
            )
        return BillingApplicationServiceV2(
            policy=self.policy,
            persistence=BillingInvoices(_session=db, tenant_id=scope.tenant_id),
            entitlements=SqlTenantEntitlements(
                session=db, tenant_id=scope.tenant_id, user_id=user_id
            ),
            user_id=user_id,
        )


@dataclass(frozen=True, kw_only=True)
class BillingApplicationResolverV2:
    """Consumer seam for the explicitly selected Billing persistence Provider."""

    provider: BillingServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> BillingApplicationServicesV2:
        return BillingApplicationServicesV2(billing=self.provider.build(operation))


async def _apply_billing_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("billing provider requires strategy operation-async-session")

    async def prepare() -> Callable[[], Awaitable[None]]:
        host = await asyncio.to_thread(load_policy, config.get("policy_archive_digest"))

        async def dispose() -> None:
            await asyncio.to_thread(host.close)

        try:
            _ = context.provide(
                BILLING_PROVIDER_SERVICE_V2,
                SqlBillingServiceFactoryV2(policy=host),
                label="billing-provider",
            )
        except BaseException:
            await dispose()
            raise
        return dispose

    await context.effect(prepare, label="billing-policy")


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


def billing_service_definitions_v2(
    sessions: Callable[[], AsyncSession] | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return independent Billing persistence Provider and application Consumer definitions."""

    async def apply_provider(context: ContextV2, config: Mapping[str, Any]) -> None:
        if sessions is not None:
            await migrate_invoices(sessions)
        await _apply_billing_provider_v2(context, config)

    return (
        PluginDefinitionV2(
            module_ref=BILLING_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(BILLING_PROVIDER_MODULE_V2),
            apply=apply_provider,
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
    "BillingServiceFactoryProtocolV2",
    "BillingTenantNotFoundV2",
    "SqlBillingServiceFactoryV2",
    "billing_service_definitions_v2",
]
