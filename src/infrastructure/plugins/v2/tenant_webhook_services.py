"""Generation-owned Provider/Consumer seams for tenant webhook services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.webhook_service import WebhookService
from src.infrastructure.adapters.secondary.persistence.sql_webhook_repository import (
    SqlWebhookRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

TENANT_WEBHOOK_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/tenant-webhook-provider"
TENANT_WEBHOOK_PROVIDER_SERVICE_V2 = "service:persistence.tenant-webhook-provider"
TENANT_WEBHOOK_APPLICATION_MODULE_V2 = "builtin://memstack/application/tenant-webhook-services"
TENANT_WEBHOOK_APPLICATION_SERVICE_V2 = "service:application.tenant-webhook-services"
TENANT_WEBHOOK_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class TenantWebhookApplicationServicesV2:
    """Operation-owned services used by tenant webhook handlers."""

    webhooks: WebhookService


@runtime_checkable
class TenantWebhookServiceFactoryProtocolV2(Protocol):
    """Build webhook services without exposing SQL implementations to consumers."""

    def build(self, operation: OperationContextV2) -> TenantWebhookApplicationServicesV2: ...


@runtime_checkable
class TenantWebhookApplicationResolverProtocolV2(Protocol):
    """Resolve webhook services through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> TenantWebhookApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlTenantWebhookServiceFactoryV2:
    """Bind webhook persistence to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> TenantWebhookApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "tenant webhook services require an AsyncSession operation service",
            )
        return TenantWebhookApplicationServicesV2(
            webhooks=WebhookService(SqlWebhookRepository(db)),
        )


@dataclass(frozen=True, kw_only=True)
class TenantWebhookApplicationResolverV2:
    """Consumer seam for an explicitly selected tenant webhook Provider."""

    provider: TenantWebhookServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> TenantWebhookApplicationServicesV2:
        return self.provider.build(operation)


def _apply_tenant_webhook_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("tenant webhook provider requires strategy operation-async-session")
    _ = context.provide(
        TENANT_WEBHOOK_PROVIDER_SERVICE_V2,
        SqlTenantWebhookServiceFactoryV2(),
        label="tenant-webhook-provider",
    )


def _apply_tenant_webhook_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("tenant webhook resolver requires strategy operation-scoped-provider")
    provider = context.require(TENANT_WEBHOOK_PROVIDER_INJECT_V2)
    if not isinstance(provider, TenantWebhookServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_tenant_webhook_provider",
            "tenant webhook provider inject does not implement the factory contract",
        )
    _ = context.provide(
        TENANT_WEBHOOK_APPLICATION_SERVICE_V2,
        TenantWebhookApplicationResolverV2(provider=provider),
        label="tenant-webhook-application",
    )


def tenant_webhook_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for tenant webhooks."""
    return (
        PluginDefinitionV2(
            module_ref=TENANT_WEBHOOK_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TENANT_WEBHOOK_PROVIDER_MODULE_V2),
            apply=_apply_tenant_webhook_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=TENANT_WEBHOOK_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(TENANT_WEBHOOK_APPLICATION_MODULE_V2),
            apply=_apply_tenant_webhook_application_v2,
        ),
    )


__all__ = [
    "TENANT_WEBHOOK_APPLICATION_MODULE_V2",
    "TENANT_WEBHOOK_APPLICATION_SERVICE_V2",
    "TENANT_WEBHOOK_PROVIDER_INJECT_V2",
    "TENANT_WEBHOOK_PROVIDER_MODULE_V2",
    "TENANT_WEBHOOK_PROVIDER_SERVICE_V2",
    "SqlTenantWebhookServiceFactoryV2",
    "TenantWebhookApplicationResolverProtocolV2",
    "TenantWebhookApplicationResolverV2",
    "TenantWebhookApplicationServicesV2",
    "TenantWebhookServiceFactoryProtocolV2",
    "tenant_webhook_service_definitions_v2",
]
