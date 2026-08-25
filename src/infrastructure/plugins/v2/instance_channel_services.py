"""Generation-owned Provider/Consumer seams for instance-channel operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.instance_channel_service import InstanceChannelService
from src.domain.ports.repositories.instance_repository import InstanceRepository
from src.infrastructure.adapters.secondary.persistence.sql_instance_channel_repository import (
    SqlInstanceChannelRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_repository import (
    SqlInstanceRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INSTANCE_CHANNEL_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/instance-channel-provider"
INSTANCE_CHANNEL_PROVIDER_SERVICE_V2 = "service:persistence.instance-channel-provider"
INSTANCE_CHANNEL_APPLICATION_MODULE_V2 = "builtin://memstack/application/instance-channel-services"
INSTANCE_CHANNEL_APPLICATION_SERVICE_V2 = "service:application.instance-channel-services"
INSTANCE_CHANNEL_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class InstanceChannelAccessServiceV2:
    """Resolve an instance's tenant without exposing the SQL repository to routes."""

    instance_repository: InstanceRepository

    async def tenant_id_for_instance(self, instance_id: str) -> str | None:
        instance = await self.instance_repository.find_by_id(instance_id)
        if instance is None:
            return None
        return str(instance.tenant_id)


@dataclass(frozen=True, kw_only=True)
class InstanceChannelApplicationServicesV2:
    """Request-owned instance-channel service set."""

    channels: InstanceChannelService
    access: InstanceChannelAccessServiceV2


@runtime_checkable
class InstanceChannelServiceFactoryProtocolV2(Protocol):
    """Build request services without exposing SQL implementation classes."""

    def build(self, operation: OperationContextV2) -> InstanceChannelApplicationServicesV2: ...


@runtime_checkable
class InstanceChannelApplicationResolverProtocolV2(Protocol):
    """Resolve request services through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> InstanceChannelApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlInstanceChannelServiceFactoryV2:
    """Bind instance-channel repositories to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> InstanceChannelApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "instance-channel services require an AsyncSession operation service",
            )
        return InstanceChannelApplicationServicesV2(
            channels=InstanceChannelService(
                channel_repo=SqlInstanceChannelRepository(db),
            ),
            access=InstanceChannelAccessServiceV2(
                instance_repository=SqlInstanceRepository(db),
            ),
        )


@dataclass(frozen=True, kw_only=True)
class InstanceChannelApplicationResolverV2:
    """Consumer seam for an explicitly selected instance-channel Provider."""

    provider: InstanceChannelServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> InstanceChannelApplicationServicesV2:
        return self.provider.build(operation)


def _apply_instance_channel_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "request-async-session":
        raise ValueError("instance-channel provider requires strategy request-async-session")
    _ = context.provide(
        INSTANCE_CHANNEL_PROVIDER_SERVICE_V2,
        SqlInstanceChannelServiceFactoryV2(),
        label="instance-channel-provider",
    )


def _apply_instance_channel_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "instance-channel application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(INSTANCE_CHANNEL_PROVIDER_INJECT_V2)
    if not isinstance(provider, InstanceChannelServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_instance_channel_provider",
            "instance-channel provider inject does not implement the factory contract",
        )
    _ = context.provide(
        INSTANCE_CHANNEL_APPLICATION_SERVICE_V2,
        InstanceChannelApplicationResolverV2(provider=provider),
        label="instance-channel-application",
    )


def instance_channel_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for instance channels."""
    return (
        PluginDefinitionV2(
            module_ref=INSTANCE_CHANNEL_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_CHANNEL_PROVIDER_MODULE_V2),
            apply=_apply_instance_channel_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=INSTANCE_CHANNEL_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_CHANNEL_APPLICATION_MODULE_V2),
            apply=_apply_instance_channel_application_v2,
        ),
    )


__all__ = [
    "INSTANCE_CHANNEL_APPLICATION_MODULE_V2",
    "INSTANCE_CHANNEL_APPLICATION_SERVICE_V2",
    "INSTANCE_CHANNEL_PROVIDER_INJECT_V2",
    "INSTANCE_CHANNEL_PROVIDER_MODULE_V2",
    "INSTANCE_CHANNEL_PROVIDER_SERVICE_V2",
    "InstanceChannelAccessServiceV2",
    "InstanceChannelApplicationResolverProtocolV2",
    "InstanceChannelApplicationResolverV2",
    "InstanceChannelApplicationServicesV2",
    "InstanceChannelServiceFactoryProtocolV2",
    "SqlInstanceChannelServiceFactoryV2",
    "instance_channel_service_definitions_v2",
]
