"""Generation-owned Provider/Consumer seams for invitation services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.invitation_service import InvitationService
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import UserTenant
from src.infrastructure.adapters.secondary.persistence.sql_invitation_repository import (
    SqlInvitationRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

INVITATION_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/invitation-provider"
INVITATION_PROVIDER_SERVICE_V2 = "service:persistence.invitation-provider"
INVITATION_APPLICATION_MODULE_V2 = "builtin://memstack/application/invitation-services"
INVITATION_APPLICATION_SERVICE_V2 = "service:application.invitation-services"
INVITATION_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class InvitationMembershipWriterProtocolV2(Protocol):
    """Persist accepted invitation membership without exposing SQL to handlers."""

    async def ensure_membership(self, *, user_id: str, tenant_id: str, role: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SqlInvitationMembershipWriterV2:
    """Bind invitation membership writes to the operation's exact session."""

    db: AsyncSession

    async def ensure_membership(self, *, user_id: str, tenant_id: str, role: str) -> None:
        existing = await self.db.execute(
            refresh_select_statement(
                select(UserTenant).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        self.db.add(
            UserTenant(
                id=str(uuid4()),
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
            )
        )


@dataclass(frozen=True, kw_only=True)
class InvitationApplicationServicesV2:
    """Operation-owned services used by invitation handlers."""

    invitations: InvitationService
    memberships: InvitationMembershipWriterProtocolV2


@runtime_checkable
class InvitationServiceFactoryProtocolV2(Protocol):
    """Build invitation services without exposing persistence implementations."""

    def build(self, operation: OperationContextV2) -> InvitationApplicationServicesV2: ...


@runtime_checkable
class InvitationApplicationResolverProtocolV2(Protocol):
    """Resolve invitation services through a declared Provider alias."""

    def resolve(self, operation: OperationContextV2) -> InvitationApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlInvitationServiceFactoryV2:
    """Construct invitation services from the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> InvitationApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "invitation services require an AsyncSession operation service",
            )
        return InvitationApplicationServicesV2(
            invitations=InvitationService(SqlInvitationRepository(db)),
            memberships=SqlInvitationMembershipWriterV2(db=db),
        )


@dataclass(frozen=True, kw_only=True)
class InvitationApplicationResolverV2:
    """Consumer seam for an explicitly selected invitation Provider."""

    provider: InvitationServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> InvitationApplicationServicesV2:
        return self.provider.build(operation)


def _apply_invitation_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("invitation provider requires strategy operation-async-session")
    _ = context.provide(
        INVITATION_PROVIDER_SERVICE_V2,
        SqlInvitationServiceFactoryV2(),
        label="invitation-provider",
    )


def _apply_invitation_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("invitation resolver requires strategy operation-scoped-provider")
    provider = context.require(INVITATION_PROVIDER_INJECT_V2)
    if not isinstance(provider, InvitationServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_invitation_provider",
            "invitation provider inject does not implement the factory contract",
        )
    _ = context.provide(
        INVITATION_APPLICATION_SERVICE_V2,
        InvitationApplicationResolverV2(provider=provider),
        label="invitation-application",
    )


def invitation_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for invitations."""
    return (
        PluginDefinitionV2(
            module_ref=INVITATION_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INVITATION_PROVIDER_MODULE_V2),
            apply=_apply_invitation_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=INVITATION_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INVITATION_APPLICATION_MODULE_V2),
            apply=_apply_invitation_application_v2,
        ),
    )


__all__ = [
    "INVITATION_APPLICATION_MODULE_V2",
    "INVITATION_APPLICATION_SERVICE_V2",
    "INVITATION_PROVIDER_INJECT_V2",
    "INVITATION_PROVIDER_MODULE_V2",
    "INVITATION_PROVIDER_SERVICE_V2",
    "InvitationApplicationResolverProtocolV2",
    "InvitationApplicationResolverV2",
    "InvitationApplicationServicesV2",
    "InvitationMembershipWriterProtocolV2",
    "InvitationServiceFactoryProtocolV2",
    "SqlInvitationMembershipWriterV2",
    "SqlInvitationServiceFactoryV2",
    "invitation_service_definitions_v2",
]
