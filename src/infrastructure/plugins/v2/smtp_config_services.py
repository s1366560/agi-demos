"""Generation-owned Provider/Consumer seams for tenant SMTP configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.smtp_config_service import SmtpConfigService
from src.domain.model.smtp.smtp_config import SmtpConfig
from src.infrastructure.adapters.secondary.persistence.sql_smtp_config_repository import (
    SqlSmtpConfigRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SMTP_CONFIG_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/smtp-config-provider"
SMTP_CONFIG_PROVIDER_SERVICE_V2 = "service:persistence.smtp-config-provider"
SMTP_CONFIG_APPLICATION_MODULE_V2 = "builtin://memstack/application/smtp-config-services"
SMTP_CONFIG_APPLICATION_SERVICE_V2 = "service:application.smtp-config-services"
SMTP_CONFIG_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class SmtpConfigProtocolV2(Protocol):
    """Tenant-scoped SMTP operations exposed by the persistence Provider."""

    async def get_config(self, tenant_id: str) -> SmtpConfig | None: ...

    async def upsert_config(
        self,
        tenant_id: str,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        from_email: str,
        from_name: str | None,
        use_tls: bool,
    ) -> SmtpConfig: ...

    async def delete_config(self, config_id: str) -> None: ...

    async def test_smtp(self, tenant_id: str, recipient_email: str) -> None: ...


@runtime_checkable
class SmtpConfigFactoryProtocolV2(Protocol):
    """Construct SMTP services without exposing a concrete repository to Consumers."""

    def build(self, operation: OperationContextV2) -> SmtpConfigProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSmtpConfigFactoryV2:
    """Bind the existing SMTP application service to one operation SQL session."""

    def build(self, operation: OperationContextV2) -> SmtpConfigProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "SMTP configuration requires an AsyncSession operation service",
            )
        return SmtpConfigService(repo=SqlSmtpConfigRepository(db))


@dataclass(frozen=True, kw_only=True)
class SmtpConfigApplicationServicesV2:
    """Operation-owned SMTP services consumed by HTTP handlers."""

    smtp: SmtpConfigProtocolV2


@runtime_checkable
class SmtpConfigApplicationResolverProtocolV2(Protocol):
    """Resolve SMTP services through the Provider alias declared by the Profile."""

    def resolve(self, operation: OperationContextV2) -> SmtpConfigApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SmtpConfigApplicationResolverV2:
    """Consumer seam for the explicitly selected SMTP persistence Provider."""

    provider: SmtpConfigFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SmtpConfigApplicationServicesV2:
        return SmtpConfigApplicationServicesV2(smtp=self.provider.build(operation))


def _apply_smtp_config_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("SMTP config provider requires strategy operation-async-session")
    _ = context.provide(
        SMTP_CONFIG_PROVIDER_SERVICE_V2,
        SqlSmtpConfigFactoryV2(),
        label="smtp-config-provider",
    )


def _apply_smtp_config_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("SMTP config resolver requires strategy operation-scoped-provider")
    provider = context.require(SMTP_CONFIG_PROVIDER_INJECT_V2)
    if not isinstance(provider, SmtpConfigFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_smtp_config_provider",
            "SMTP config provider inject does not implement the factory contract",
        )
    _ = context.provide(
        SMTP_CONFIG_APPLICATION_SERVICE_V2,
        SmtpConfigApplicationResolverV2(provider=provider),
        label="smtp-config-application",
    )


def smtp_config_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent SMTP persistence Provider and application Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=SMTP_CONFIG_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SMTP_CONFIG_PROVIDER_MODULE_V2),
            apply=_apply_smtp_config_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SMTP_CONFIG_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SMTP_CONFIG_APPLICATION_MODULE_V2),
            apply=_apply_smtp_config_application_v2,
        ),
    )


__all__ = [
    "SMTP_CONFIG_APPLICATION_MODULE_V2",
    "SMTP_CONFIG_APPLICATION_SERVICE_V2",
    "SMTP_CONFIG_PROVIDER_INJECT_V2",
    "SMTP_CONFIG_PROVIDER_MODULE_V2",
    "SMTP_CONFIG_PROVIDER_SERVICE_V2",
    "SmtpConfigApplicationResolverProtocolV2",
    "SmtpConfigApplicationResolverV2",
    "SmtpConfigApplicationServicesV2",
    "SmtpConfigFactoryProtocolV2",
    "SmtpConfigProtocolV2",
    "SqlSmtpConfigFactoryV2",
    "smtp_config_service_definitions_v2",
]
