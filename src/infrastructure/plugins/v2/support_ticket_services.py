"""Generation-owned persistence and application seams for support tickets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import SupportTicket, UserTenant

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SUPPORT_TICKET_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/support-ticket-provider"
SUPPORT_TICKET_PROVIDER_SERVICE_V2 = "service:persistence.support-ticket-provider"
SUPPORT_TICKET_APPLICATION_MODULE_V2 = "builtin://memstack/application/support-ticket-services"
SUPPORT_TICKET_APPLICATION_SERVICE_V2 = "service:application.support-ticket-services"
SUPPORT_TICKET_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class SupportTicketServiceErrorV2(Exception):
    """Base class for typed support-ticket application failures."""


class SupportTicketNotFoundV2(SupportTicketServiceErrorV2):
    """The requested ticket does not belong to the operation identity."""


class SupportTenantAccessDeniedV2(SupportTicketServiceErrorV2):
    """The operation identity is not a member of the requested tenant."""


@dataclass(frozen=True, kw_only=True)
class SupportTicketSnapshotV2:
    """Immutable support-ticket state returned across the Provider seam."""

    id: str
    tenant_id: str | None
    user_id: str
    subject: str
    message: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class SupportTicketCreateRecordV2:
    """Persistence payload assembled by the application Consumer."""

    id: str
    tenant_id: str | None
    user_id: str
    subject: Any
    message: Any
    priority: Any


@dataclass(frozen=True, kw_only=True)
class SupportTicketQueryResultV2:
    """Provider result before request pagination metadata is attached."""

    tickets: tuple[SupportTicketSnapshotV2, ...]
    total: int


@dataclass(frozen=True, kw_only=True)
class SupportTicketPageV2:
    """Application result preserving the public pagination contract."""

    tickets: tuple[SupportTicketSnapshotV2, ...]
    total: int
    limit: int
    offset: int


@runtime_checkable
class SupportTicketPersistenceProtocolV2(Protocol):
    """Exact persistence operations hidden behind the support Provider."""

    async def has_tenant_membership(self, *, user_id: str, tenant_id: str) -> bool: ...

    async def create_ticket(
        self,
        *,
        record: SupportTicketCreateRecordV2,
    ) -> SupportTicketSnapshotV2: ...

    async def list_tickets(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> SupportTicketQueryResultV2: ...

    async def get_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
    ) -> SupportTicketSnapshotV2: ...

    async def update_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
        updates: Mapping[str, Any],
    ) -> SupportTicketSnapshotV2: ...

    async def close_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
        resolved_at: datetime,
    ) -> SupportTicketSnapshotV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSupportTicketPersistenceV2:
    """SQL implementation bound to exactly one operation-owned session."""

    _session: AsyncSession

    async def has_tenant_membership(self, *, user_id: str, tenant_id: str) -> bool:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserTenant.id).where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_ticket(
        self,
        *,
        record: SupportTicketCreateRecordV2,
    ) -> SupportTicketSnapshotV2:
        ticket = SupportTicket(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            subject=record.subject,
            message=record.message,
            priority=record.priority,
            status="open",
        )
        self._session.add(ticket)
        await self._session.commit()
        await self._session.refresh(ticket)
        return _support_ticket_snapshot_v2(ticket)

    async def list_tickets(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> SupportTicketQueryResultV2:
        filters = [SupportTicket.user_id == user_id]
        if tenant_id:
            filters.append(SupportTicket.tenant_id == tenant_id)
        if status:
            filters.append(SupportTicket.status == status)

        total_result = await self._session.execute(
            refresh_select_statement(
                select(func.count()).select_from(SupportTicket).where(*filters)
            )
        )
        total = int(total_result.scalar_one())
        result = await self._session.execute(
            refresh_select_statement(
                select(SupportTicket)
                .where(*filters)
                .order_by(SupportTicket.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        return SupportTicketQueryResultV2(
            tickets=tuple(_support_ticket_snapshot_v2(ticket) for ticket in result.scalars().all()),
            total=total,
        )

    async def get_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
    ) -> SupportTicketSnapshotV2:
        return _support_ticket_snapshot_v2(
            await self._owned_ticket(user_id=user_id, ticket_id=ticket_id)
        )

    async def update_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
        updates: Mapping[str, Any],
    ) -> SupportTicketSnapshotV2:
        ticket = await self._owned_ticket(user_id=user_id, ticket_id=ticket_id)
        if "subject" in updates:
            ticket.subject = updates["subject"]
        if "message" in updates:
            ticket.message = updates["message"]
        if "priority" in updates:
            ticket.priority = updates["priority"]
        await self._session.commit()
        await self._session.refresh(ticket)
        return _support_ticket_snapshot_v2(ticket)

    async def close_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
        resolved_at: datetime,
    ) -> SupportTicketSnapshotV2:
        ticket = await self._owned_ticket(user_id=user_id, ticket_id=ticket_id)
        ticket.status = "closed"
        ticket.resolved_at = resolved_at
        await self._session.commit()
        await self._session.refresh(ticket)
        return _support_ticket_snapshot_v2(ticket)

    async def _owned_ticket(self, *, user_id: str, ticket_id: str) -> SupportTicket:
        result = await self._session.execute(
            refresh_select_statement(
                select(SupportTicket).where(
                    SupportTicket.id == ticket_id,
                    SupportTicket.user_id == user_id,
                )
            )
        )
        ticket = result.scalar_one_or_none()
        if ticket is None:
            raise SupportTicketNotFoundV2
        return ticket


@dataclass(frozen=True, kw_only=True)
class SupportTicketApplicationServicesV2:
    """Identity-scoped support-ticket operations for one request."""

    persistence: SupportTicketPersistenceProtocolV2

    async def create_ticket(
        self,
        *,
        user_id: str,
        is_superuser: bool,
        data: Mapping[str, Any],
    ) -> SupportTicketSnapshotV2:
        tenant_id_raw = data.get("tenant_id")
        tenant_id = tenant_id_raw if isinstance(tenant_id_raw, str) else None
        await self._require_tenant_access(
            user_id=user_id,
            is_superuser=is_superuser,
            tenant_id=tenant_id,
        )
        return await self.persistence.create_ticket(
            record=SupportTicketCreateRecordV2(
                id=str(uuid4()),
                tenant_id=tenant_id,
                user_id=user_id,
                subject=data.get("subject"),
                message=data.get("message"),
                priority=data.get("priority", "medium"),
            )
        )

    async def list_tickets(
        self,
        *,
        user_id: str,
        is_superuser: bool,
        tenant_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> SupportTicketPageV2:
        await self._require_tenant_access(
            user_id=user_id,
            is_superuser=is_superuser,
            tenant_id=tenant_id,
        )
        result = await self.persistence.list_tickets(
            user_id=user_id,
            tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return SupportTicketPageV2(
            tickets=result.tickets,
            total=result.total,
            limit=limit,
            offset=offset,
        )

    async def get_ticket(self, *, user_id: str, ticket_id: str) -> SupportTicketSnapshotV2:
        return await self.persistence.get_ticket(user_id=user_id, ticket_id=ticket_id)

    async def update_ticket(
        self,
        *,
        user_id: str,
        ticket_id: str,
        data: Mapping[str, Any],
    ) -> SupportTicketSnapshotV2:
        updates = {
            field: data[field] for field in ("subject", "message", "priority") if field in data
        }
        return await self.persistence.update_ticket(
            user_id=user_id,
            ticket_id=ticket_id,
            updates=updates,
        )

    async def close_ticket(self, *, user_id: str, ticket_id: str) -> SupportTicketSnapshotV2:
        return await self.persistence.close_ticket(
            user_id=user_id,
            ticket_id=ticket_id,
            resolved_at=datetime.now(UTC),
        )

    async def _require_tenant_access(
        self,
        *,
        user_id: str,
        is_superuser: bool,
        tenant_id: str | None,
    ) -> None:
        if not tenant_id or is_superuser:
            return
        if not await self.persistence.has_tenant_membership(
            user_id=user_id,
            tenant_id=tenant_id,
        ):
            raise SupportTenantAccessDeniedV2


@runtime_checkable
class SupportTicketServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete support persistence construction."""

    def build(self, operation: OperationContextV2) -> SupportTicketPersistenceProtocolV2: ...


@runtime_checkable
class SupportTicketApplicationResolverProtocolV2(Protocol):
    """Resolve operation-owned support services through a declared alias."""

    def resolve(self, operation: OperationContextV2) -> SupportTicketApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSupportTicketServiceFactoryV2:
    """Build support persistence from the operation's exact AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> SupportTicketPersistenceProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "support ticket services require an AsyncSession operation service",
            )
        return SqlSupportTicketPersistenceV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class SupportTicketApplicationResolverV2:
    """Resolve operation-owned application services without exposing the Provider."""

    provider: SupportTicketServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SupportTicketApplicationServicesV2:
        return SupportTicketApplicationServicesV2(persistence=self.provider.build(operation))


def _apply_support_ticket_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("support ticket provider requires strategy request-async-session")
    _ = context.provide(
        SUPPORT_TICKET_PROVIDER_SERVICE_V2,
        SqlSupportTicketServiceFactoryV2(strategy=strategy),
        label="support-ticket-provider",
    )


def _apply_support_ticket_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "support ticket application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(SUPPORT_TICKET_PROVIDER_INJECT_V2)
    if not isinstance(provider, SupportTicketServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_support_ticket_provider",
            "support ticket provider inject does not implement the factory contract",
        )
    _ = context.provide(
        SUPPORT_TICKET_APPLICATION_SERVICE_V2,
        SupportTicketApplicationResolverV2(provider=provider),
        label="support-ticket-application",
    )


def support_ticket_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the support-ticket persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=SUPPORT_TICKET_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUPPORT_TICKET_PROVIDER_MODULE_V2),
            apply=_apply_support_ticket_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SUPPORT_TICKET_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SUPPORT_TICKET_APPLICATION_MODULE_V2),
            apply=_apply_support_ticket_application_v2,
        ),
    )


def _support_ticket_snapshot_v2(ticket: SupportTicket) -> SupportTicketSnapshotV2:
    return SupportTicketSnapshotV2(
        id=ticket.id,
        tenant_id=ticket.tenant_id,
        user_id=ticket.user_id,
        subject=ticket.subject,
        message=ticket.message,
        priority=ticket.priority,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
    )


__all__ = [
    "SUPPORT_TICKET_APPLICATION_MODULE_V2",
    "SUPPORT_TICKET_APPLICATION_SERVICE_V2",
    "SUPPORT_TICKET_PROVIDER_INJECT_V2",
    "SUPPORT_TICKET_PROVIDER_MODULE_V2",
    "SUPPORT_TICKET_PROVIDER_SERVICE_V2",
    "SqlSupportTicketPersistenceV2",
    "SqlSupportTicketServiceFactoryV2",
    "SupportTenantAccessDeniedV2",
    "SupportTicketApplicationResolverProtocolV2",
    "SupportTicketApplicationResolverV2",
    "SupportTicketApplicationServicesV2",
    "SupportTicketCreateRecordV2",
    "SupportTicketNotFoundV2",
    "SupportTicketPageV2",
    "SupportTicketPersistenceProtocolV2",
    "SupportTicketQueryResultV2",
    "SupportTicketServiceErrorV2",
    "SupportTicketServiceFactoryProtocolV2",
    "SupportTicketSnapshotV2",
    "support_ticket_service_definitions_v2",
]
