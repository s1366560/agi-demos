"""Generation-owned Provider/Consumer seams for instance-file operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.instance_file_service import InstanceFileService
from src.application.services.instance_service import InstanceService
from src.infrastructure.adapters.secondary.persistence.sql_deploy_record_repository import (
    SqlDeployRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_instance_member_repository import (
    SqlInstanceMemberRepository,
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

INSTANCE_FILE_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/instance-file-provider"
INSTANCE_FILE_PROVIDER_SERVICE_V2 = "service:persistence.instance-file-provider"
INSTANCE_FILE_APPLICATION_MODULE_V2 = "builtin://memstack/application/instance-file-services"
INSTANCE_FILE_APPLICATION_SERVICE_V2 = "service:application.instance-file-services"
INSTANCE_FILE_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@dataclass(frozen=True, kw_only=True)
class InstanceFileApplicationServicesV2:
    """Request-owned instance access and local file services."""

    instance: InstanceService
    files: InstanceFileService


@runtime_checkable
class InstanceFileServiceFactoryProtocolV2(Protocol):
    """Build instance-file services without exposing SQL implementations."""

    def build(self, operation: OperationContextV2) -> InstanceFileApplicationServicesV2: ...


@runtime_checkable
class InstanceFileApplicationResolverProtocolV2(Protocol):
    """Resolve the request-owned service set through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> InstanceFileApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlInstanceFileServiceFactoryV2:
    """Build the exact SQL and filesystem adapters declared by the active generation."""

    base_dir: str

    def build(self, operation: OperationContextV2) -> InstanceFileApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "instance-file services require an AsyncSession operation service",
            )
        return InstanceFileApplicationServicesV2(
            instance=InstanceService(
                instance_repo=SqlInstanceRepository(db),
                instance_member_repo=SqlInstanceMemberRepository(db),
                deploy_record_repo=SqlDeployRecordRepository(db),
            ),
            files=InstanceFileService(base_dir=self.base_dir),
        )


@dataclass(frozen=True, kw_only=True)
class InstanceFileApplicationResolverV2:
    """Consumer seam for an explicitly selected instance-file Provider."""

    provider: InstanceFileServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> InstanceFileApplicationServicesV2:
        return self.provider.build(operation)


def _apply_instance_file_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("instance-file provider requires strategy operation-async-session")
    base_dir = config.get("base_dir")
    if not isinstance(base_dir, str) or not base_dir.strip():
        raise ValueError("instance-file provider requires a non-empty base_dir")
    _ = context.provide(
        INSTANCE_FILE_PROVIDER_SERVICE_V2,
        SqlInstanceFileServiceFactoryV2(base_dir=base_dir),
        label="instance-file-provider",
    )


def _apply_instance_file_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "instance-file application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(INSTANCE_FILE_PROVIDER_INJECT_V2)
    if not isinstance(provider, InstanceFileServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_instance_file_provider",
            "instance-file provider inject does not implement the factory contract",
        )
    _ = context.provide(
        INSTANCE_FILE_APPLICATION_SERVICE_V2,
        InstanceFileApplicationResolverV2(provider=provider),
        label="instance-file-application",
    )


def instance_file_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for instance files."""
    return (
        PluginDefinitionV2(
            module_ref=INSTANCE_FILE_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_FILE_PROVIDER_MODULE_V2),
            apply=_apply_instance_file_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=INSTANCE_FILE_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_FILE_APPLICATION_MODULE_V2),
            apply=_apply_instance_file_application_v2,
        ),
    )


__all__ = [
    "INSTANCE_FILE_APPLICATION_MODULE_V2",
    "INSTANCE_FILE_APPLICATION_SERVICE_V2",
    "INSTANCE_FILE_PROVIDER_INJECT_V2",
    "INSTANCE_FILE_PROVIDER_MODULE_V2",
    "INSTANCE_FILE_PROVIDER_SERVICE_V2",
    "InstanceFileApplicationResolverProtocolV2",
    "InstanceFileApplicationResolverV2",
    "InstanceFileApplicationServicesV2",
    "InstanceFileServiceFactoryProtocolV2",
    "SqlInstanceFileServiceFactoryV2",
    "instance_file_service_definitions_v2",
]
