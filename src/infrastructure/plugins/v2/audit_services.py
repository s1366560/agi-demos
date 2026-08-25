"""Generation-owned Provider/Consumer seams for audit query services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.audit_query_service import AuditQueryService
from src.domain.model.audit.audit_entry import AuditEntry
from src.infrastructure.adapters.secondary.persistence.sql_audit_repository import (
    SqlAuditRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AUDIT_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/audit-query-provider"
AUDIT_PROVIDER_SERVICE_V2 = "service:persistence.audit-query-provider"
AUDIT_APPLICATION_MODULE_V2 = "builtin://memstack/application/audit-query-services"
AUDIT_APPLICATION_SERVICE_V2 = "service:application.audit-query-services"
AUDIT_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class AuditQueryProtocolV2(Protocol):
    """Tenant-scoped audit operations exposed by the persistence Provider."""

    async def list_entries(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]: ...

    async def list_entries_filtered(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        action_prefix: str | None = None,
        resource_type: str | None = None,
        actor: str | None = None,
        detail_filters: dict[str, str] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]: ...

    async def list_runtime_hook_entries(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        hook_name: str | None = None,
        executor_kind: str | None = None,
        hook_family: str | None = None,
        isolation_mode: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEntry], int]: ...

    async def summarize_runtime_hook_entries(
        self,
        tenant_id: str,
        *,
        action: str | None = None,
        hook_name: str | None = None,
        executor_kind: str | None = None,
        hook_family: str | None = None,
        isolation_mode: str | None = None,
    ) -> dict[str, object]: ...


@runtime_checkable
class AuditQueryFactoryProtocolV2(Protocol):
    """Construct audit queries without exposing a concrete repository to Consumers."""

    def build(self, operation: OperationContextV2) -> AuditQueryProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlAuditQueryFactoryV2:
    """Bind the existing query service to one operation-owned SQL session."""

    def build(self, operation: OperationContextV2) -> AuditQueryProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "audit queries require an AsyncSession operation service",
            )
        return AuditQueryService(audit_repo=SqlAuditRepository(db))


@dataclass(frozen=True, kw_only=True)
class AuditQueryApplicationServicesV2:
    """Operation-owned audit query services consumed by HTTP handlers."""

    query: AuditQueryProtocolV2


@runtime_checkable
class AuditApplicationResolverProtocolV2(Protocol):
    """Resolve audit services through the Provider alias declared by the Profile."""

    def resolve(self, operation: OperationContextV2) -> AuditQueryApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class AuditApplicationResolverV2:
    """Consumer seam for the explicitly selected audit query Provider."""

    provider: AuditQueryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> AuditQueryApplicationServicesV2:
        return AuditQueryApplicationServicesV2(query=self.provider.build(operation))


def _apply_audit_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("audit query provider requires strategy operation-async-session")
    _ = context.provide(
        AUDIT_PROVIDER_SERVICE_V2,
        SqlAuditQueryFactoryV2(),
        label="audit-query-provider",
    )


def _apply_audit_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("audit query resolver requires strategy operation-scoped-provider")
    provider = context.require(AUDIT_PROVIDER_INJECT_V2)
    if not isinstance(provider, AuditQueryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_audit_query_provider",
            "audit query provider inject does not implement the factory contract",
        )
    _ = context.provide(
        AUDIT_APPLICATION_SERVICE_V2,
        AuditApplicationResolverV2(provider=provider),
        label="audit-query-application",
    )


def audit_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent audit persistence Provider and application Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=AUDIT_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AUDIT_PROVIDER_MODULE_V2),
            apply=_apply_audit_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=AUDIT_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(AUDIT_APPLICATION_MODULE_V2),
            apply=_apply_audit_application_v2,
        ),
    )


__all__ = [
    "AUDIT_APPLICATION_MODULE_V2",
    "AUDIT_APPLICATION_SERVICE_V2",
    "AUDIT_PROVIDER_INJECT_V2",
    "AUDIT_PROVIDER_MODULE_V2",
    "AUDIT_PROVIDER_SERVICE_V2",
    "AuditApplicationResolverProtocolV2",
    "AuditApplicationResolverV2",
    "AuditQueryApplicationServicesV2",
    "AuditQueryFactoryProtocolV2",
    "AuditQueryProtocolV2",
    "SqlAuditQueryFactoryV2",
    "audit_service_definitions_v2",
]
