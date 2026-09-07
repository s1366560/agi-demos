"""Generation-owned Provider/Consumer seams for instance-template operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.instance_template_service import InstanceTemplateService
from src.infrastructure.adapters.secondary.persistence.sql_instance_template_repository import (
    SqlInstanceTemplateRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INSTANCE_TEMPLATE_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/instance-template-provider"
INSTANCE_TEMPLATE_PROVIDER_SERVICE_V2 = "service:persistence.instance-template-provider"
INSTANCE_TEMPLATE_APPLICATION_MODULE_V2 = (
    "builtin://memstack/application/instance-template-services"
)
INSTANCE_TEMPLATE_APPLICATION_SERVICE_V2 = "service:application.instance-template-services"
INSTANCE_TEMPLATE_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class InstanceTemplateApplicationServicesV2:
    """Request-owned instance-template service set."""

    templates: InstanceTemplateService


@runtime_checkable
class InstanceTemplateServiceFactoryProtocolV2(Protocol):
    """Build request services without exposing SQL implementation classes."""

    def build(self, operation: OperationContextV2) -> InstanceTemplateApplicationServicesV2: ...


@runtime_checkable
class InstanceTemplateApplicationResolverProtocolV2(Protocol):
    """Resolve request services through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> InstanceTemplateApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlInstanceTemplateServiceFactoryV2:
    """Bind the template repository to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> InstanceTemplateApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "instance-template services require an AsyncSession operation service",
            )
        return InstanceTemplateApplicationServicesV2(
            templates=InstanceTemplateService(
                template_repo=SqlInstanceTemplateRepository(db),
            ),
        )


@dataclass(frozen=True, kw_only=True)
class InstanceTemplateApplicationResolverV2:
    """Consumer seam for an explicitly selected instance-template Provider."""

    provider: InstanceTemplateServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> InstanceTemplateApplicationServicesV2:
        return self.provider.build(operation)


def _apply_instance_template_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "request-async-session":
        raise ValueError("instance-template provider requires strategy request-async-session")
    _ = context.provide(
        INSTANCE_TEMPLATE_PROVIDER_SERVICE_V2,
        SqlInstanceTemplateServiceFactoryV2(),
        label="instance-template-provider",
    )


def _apply_instance_template_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "instance-template application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(INSTANCE_TEMPLATE_PROVIDER_INJECT_V2)
    if not isinstance(provider, InstanceTemplateServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_instance_template_provider",
            "instance-template provider inject does not implement the factory contract",
        )
    _ = context.provide(
        INSTANCE_TEMPLATE_APPLICATION_SERVICE_V2,
        InstanceTemplateApplicationResolverV2(provider=provider),
        label="instance-template-application",
    )


def instance_template_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for instance templates."""
    return (
        PluginDefinitionV2(
            module_ref=INSTANCE_TEMPLATE_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_TEMPLATE_PROVIDER_MODULE_V2),
            apply=_apply_instance_template_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=INSTANCE_TEMPLATE_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_TEMPLATE_APPLICATION_MODULE_V2),
            apply=_apply_instance_template_application_v2,
        ),
    )


__all__ = [
    "INSTANCE_TEMPLATE_APPLICATION_MODULE_V2",
    "INSTANCE_TEMPLATE_APPLICATION_SERVICE_V2",
    "INSTANCE_TEMPLATE_PROVIDER_INJECT_V2",
    "INSTANCE_TEMPLATE_PROVIDER_MODULE_V2",
    "INSTANCE_TEMPLATE_PROVIDER_SERVICE_V2",
    "InstanceTemplateApplicationResolverProtocolV2",
    "InstanceTemplateApplicationResolverV2",
    "InstanceTemplateApplicationServicesV2",
    "InstanceTemplateServiceFactoryProtocolV2",
    "SqlInstanceTemplateServiceFactoryV2",
    "instance_template_service_definitions_v2",
]
