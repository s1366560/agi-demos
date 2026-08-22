"""Generation-owned persistence and application seams for user notifications."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable
from uuid import uuid4

from sqlalchemy import and_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import Notification

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

NOTIFICATION_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/notification-provider"
NOTIFICATION_PROVIDER_SERVICE_V2 = "service:persistence.notification-provider"
NOTIFICATION_APPLICATION_MODULE_V2 = "builtin://memstack/application/notification-services"
NOTIFICATION_APPLICATION_SERVICE_V2 = "service:application.notification-services"
NOTIFICATION_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"


class NotificationServiceErrorV2(Exception):
    """Base class for typed notification application failures."""


class NotificationNotFoundV2(NotificationServiceErrorV2):
    """The requested notification does not belong to the operation identity."""


class NotificationAccessDeniedV2(NotificationServiceErrorV2):
    """The operation identity cannot create a notification for the target user."""


class NotificationInvalidExpirationV2(NotificationServiceErrorV2):
    """The requested expiration value is not a valid timestamp."""


@dataclass(frozen=True, kw_only=True)
class NotificationCreateRecordV2:
    """Validated persistence payload for a new notification."""

    user_id: str
    notification_type: str
    title: str
    message: str
    data: object
    action_url: str | None
    expires_at: datetime | None


@runtime_checkable
class NotificationPersistenceProtocolV2(Protocol):
    """Persistence operations hidden behind the exact notification Provider contract."""

    async def list_notifications(
        self,
        *,
        user_id: str,
        unread_only: bool,
        limit: int,
    ) -> Sequence[Notification]: ...

    async def mark_notification_read(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> None: ...

    async def mark_all_read(self, *, user_id: str) -> int: ...

    async def delete_notification(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> None: ...

    async def create_notification(
        self,
        *,
        record: NotificationCreateRecordV2,
    ) -> Notification: ...


@dataclass(frozen=True, kw_only=True)
class SqlNotificationPersistenceV2:
    """SQL implementation bound to one operation-owned session."""

    _session: AsyncSession

    async def list_notifications(
        self,
        *,
        user_id: str,
        unread_only: bool,
        limit: int,
    ) -> Sequence[Notification]:
        query = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        query = query.order_by(Notification.created_at.desc()).limit(limit)
        result = await self._session.execute(refresh_select_statement(query))
        return result.scalars().all()

    async def mark_notification_read(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> None:
        notification = await self._owned_notification(
            user_id=user_id,
            notification_id=notification_id,
        )
        notification.is_read = True
        await self._session.commit()

    async def mark_all_read(self, *, user_id: str) -> int:
        result = await self._session.execute(
            update(Notification)
            .where(and_(Notification.user_id == user_id, Notification.is_read.is_(False)))
            .values(is_read=True)
            .execution_options(synchronize_session=False)
        )
        await self._session.commit()
        return int(cast(CursorResult[Any], result).rowcount or 0)

    async def delete_notification(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> None:
        notification = await self._owned_notification(
            user_id=user_id,
            notification_id=notification_id,
        )
        await self._session.delete(notification)
        await self._session.commit()

    async def create_notification(
        self,
        *,
        record: NotificationCreateRecordV2,
    ) -> Notification:
        notification = Notification(
            id=str(uuid4()),
            user_id=record.user_id,
            type=record.notification_type,
            title=record.title,
            message=record.message,
            data=record.data,
            action_url=record.action_url,
            expires_at=record.expires_at,
        )
        self._session.add(notification)
        await self._session.commit()
        return notification

    async def _owned_notification(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> Notification:
        result = await self._session.execute(
            refresh_select_statement(
                select(Notification).where(
                    and_(
                        Notification.id == notification_id,
                        Notification.user_id == user_id,
                    )
                )
            )
        )
        notification = cast(Notification | None, result.scalar_one_or_none())
        if notification is None:
            raise NotificationNotFoundV2
        return notification


@dataclass(frozen=True, kw_only=True)
class NotificationApplicationServicesV2:
    """Identity-scoped notification operations resolved for one request."""

    persistence: NotificationPersistenceProtocolV2

    async def list_notifications(
        self,
        *,
        user_id: str,
        unread_only: bool,
        limit: int,
    ) -> Sequence[Notification]:
        notifications = await self.persistence.list_notifications(
            user_id=user_id,
            unread_only=unread_only,
            limit=limit,
        )
        now_utc = datetime.now(UTC)
        return tuple(
            notification
            for notification in notifications
            if _notification_is_live_v2(notification, now_utc=now_utc)
        )

    async def mark_notification_read(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> None:
        await self.persistence.mark_notification_read(
            user_id=user_id,
            notification_id=notification_id,
        )

    async def mark_all_read(self, *, user_id: str) -> int:
        return await self.persistence.mark_all_read(user_id=user_id)

    async def delete_notification(
        self,
        *,
        user_id: str,
        notification_id: str,
    ) -> None:
        await self.persistence.delete_notification(
            user_id=user_id,
            notification_id=notification_id,
        )

    async def create_notification(
        self,
        *,
        user_id: str,
        is_superuser: bool,
        data: Mapping[str, Any],
    ) -> Notification:
        target_user_id = str(data.get("user_id") or user_id)
        if target_user_id != user_id and not is_superuser:
            raise NotificationAccessDeniedV2
        return await self.persistence.create_notification(
            record=NotificationCreateRecordV2(
                user_id=target_user_id,
                notification_type=str(data.get("type", "general")),
                title=str(data.get("title", "Notification")),
                message=str(data.get("message", "")),
                data=data.get("data", {}),
                action_url=_optional_string_v2(data.get("action_url")),
                expires_at=_parse_expiration_v2(data.get("expires_at")),
            )
        )


def _notification_is_live_v2(notification: Notification, *, now_utc: datetime) -> bool:
    expires_at = notification.expires_at
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > now_utc


def _parse_expiration_v2(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise NotificationInvalidExpirationV2 from error
    raise NotificationInvalidExpirationV2


def _optional_string_v2(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


@runtime_checkable
class NotificationServiceFactoryProtocolV2(Protocol):
    """Provider contract hiding concrete persistence implementations."""

    def build(self, operation: OperationContextV2) -> NotificationPersistenceProtocolV2: ...


@runtime_checkable
class NotificationApplicationResolverProtocolV2(Protocol):
    """Application resolver injected through a declared service alias."""

    def resolve(self, operation: OperationContextV2) -> NotificationApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlNotificationServiceFactoryV2:
    """Build notification persistence from the operation's exact AsyncSession."""

    strategy: str

    def build(self, operation: OperationContextV2) -> NotificationPersistenceProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "notification services require an AsyncSession operation service",
            )
        return SqlNotificationPersistenceV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class NotificationApplicationResolverV2:
    """Resolve operation-owned application services without exposing the Provider."""

    provider: NotificationServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> NotificationApplicationServicesV2:
        return NotificationApplicationServicesV2(persistence=self.provider.build(operation))


def _apply_notification_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    strategy = config.get("strategy")
    if strategy != "request-async-session":
        raise ValueError("notification provider requires strategy request-async-session")
    _ = context.provide(
        NOTIFICATION_PROVIDER_SERVICE_V2,
        SqlNotificationServiceFactoryV2(strategy=strategy),
        label="notification-provider",
    )


def _apply_notification_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    strategy = config.get("strategy")
    if strategy != "operation-scoped-provider":
        raise ValueError(
            "notification application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(NOTIFICATION_PROVIDER_INJECT_V2)
    if not isinstance(provider, NotificationServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_notification_provider",
            "notification provider inject does not implement the factory contract",
        )
    _ = context.provide(
        NOTIFICATION_APPLICATION_SERVICE_V2,
        NotificationApplicationResolverV2(provider=provider),
        label="notification-application",
    )


def notification_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    return (
        PluginDefinitionV2(
            module_ref=NOTIFICATION_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(NOTIFICATION_PROVIDER_MODULE_V2),
            apply=_apply_notification_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=NOTIFICATION_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(NOTIFICATION_APPLICATION_MODULE_V2),
            apply=_apply_notification_application_v2,
        ),
    )


__all__ = [
    "NOTIFICATION_APPLICATION_MODULE_V2",
    "NOTIFICATION_APPLICATION_SERVICE_V2",
    "NOTIFICATION_PROVIDER_INJECT_V2",
    "NOTIFICATION_PROVIDER_MODULE_V2",
    "NOTIFICATION_PROVIDER_SERVICE_V2",
    "NotificationAccessDeniedV2",
    "NotificationApplicationResolverProtocolV2",
    "NotificationApplicationResolverV2",
    "NotificationApplicationServicesV2",
    "NotificationCreateRecordV2",
    "NotificationInvalidExpirationV2",
    "NotificationNotFoundV2",
    "NotificationPersistenceProtocolV2",
    "NotificationServiceErrorV2",
    "NotificationServiceFactoryProtocolV2",
    "SqlNotificationPersistenceV2",
    "SqlNotificationServiceFactoryV2",
    "notification_service_definitions_v2",
]
