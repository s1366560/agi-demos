"""Generation-owned persistence and application seams for tenant event-log queries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.event_log_service import EventLogService
from src.domain.model.tenant.event_log import EventLog
from src.infrastructure.adapters.secondary.persistence.sql_event_log_repository import (
    SqlEventLogRepository,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

EVENT_LOG_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/event-log-query-provider"
EVENT_LOG_PROVIDER_SERVICE_V2 = "service:persistence.event-log-query-provider"
EVENT_LOG_APPLICATION_MODULE_V2 = "builtin://memstack/application/event-log-query-services"
EVENT_LOG_APPLICATION_SERVICE_V2 = "service:application.event-log-query-services"
EVENT_LOG_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


@runtime_checkable
class EventLogQueryProtocolV2(Protocol):
    """Read-only event-log operations exposed to the application Consumer."""

    async def list_events(
        self,
        *,
        tenant_id: str,
        event_type: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[EventLog], int]: ...

    async def get_event_types(self, tenant_id: str) -> list[str]: ...


@runtime_checkable
class EventLogQueryFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete event-log persistence construction."""

    def build(self, operation: OperationContextV2) -> EventLogQueryProtocolV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlEventLogQueryFactoryV2:
    """Build the existing query service from one operation-owned SQL session."""

    strategy: str

    def build(self, operation: OperationContextV2) -> EventLogQueryProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "event-log queries require an AsyncSession operation service",
            )
        return EventLogService(SqlEventLogRepository(db))


@dataclass(frozen=True, kw_only=True)
class EventLogQueryApplicationServicesV2:
    """Tenant-scoped query operations resolved for one HTTP request."""

    query: EventLogQueryProtocolV2

    async def list_events(
        self,
        *,
        tenant_id: str,
        event_type: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[EventLog], int]:
        return await self.query.list_events(
            tenant_id=tenant_id,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )

    async def get_event_types(self, *, tenant_id: str) -> list[str]:
        return await self.query.get_event_types(tenant_id)


@runtime_checkable
class EventLogApplicationResolverProtocolV2(Protocol):
    """Resolve request-owned event-log services through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> EventLogQueryApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class EventLogApplicationResolverV2:
    """Combine the application Consumer with an operation-owned query Provider."""

    provider: EventLogQueryFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> EventLogQueryApplicationServicesV2:
        return EventLogQueryApplicationServicesV2(query=self.provider.build(operation))


def _apply_event_log_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("event-log query provider requires strategy request-async-session")
    _ = context.provide(
        EVENT_LOG_PROVIDER_SERVICE_V2,
        SqlEventLogQueryFactoryV2(strategy=strategy),
        label="event-log-query-provider",
    )


def _apply_event_log_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "event-log application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(EVENT_LOG_PROVIDER_INJECT_V2)
    if not isinstance(provider, EventLogQueryFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_event_log_query_provider",
            "event-log query provider inject does not implement the factory contract",
        )
    _ = context.provide(
        EVENT_LOG_APPLICATION_SERVICE_V2,
        EventLogApplicationResolverV2(provider=provider),
        label="event-log-query-application",
    )


def event_log_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return the event-log persistence Provider and application Consumer."""
    return (
        PluginDefinitionV2(
            module_ref=EVENT_LOG_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(EVENT_LOG_PROVIDER_MODULE_V2),
            apply=_apply_event_log_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=EVENT_LOG_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(EVENT_LOG_APPLICATION_MODULE_V2),
            apply=_apply_event_log_application_v2,
        ),
    )


__all__ = [
    "EVENT_LOG_APPLICATION_MODULE_V2",
    "EVENT_LOG_APPLICATION_SERVICE_V2",
    "EVENT_LOG_PROVIDER_INJECT_V2",
    "EVENT_LOG_PROVIDER_MODULE_V2",
    "EVENT_LOG_PROVIDER_SERVICE_V2",
    "EventLogApplicationResolverProtocolV2",
    "EventLogApplicationResolverV2",
    "EventLogQueryApplicationServicesV2",
    "EventLogQueryFactoryProtocolV2",
    "EventLogQueryProtocolV2",
    "SqlEventLogQueryFactoryV2",
    "event_log_service_definitions_v2",
]
