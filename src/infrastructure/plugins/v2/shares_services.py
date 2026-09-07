"""Generation-owned persistence and application seams for memory shares."""

from __future__ import annotations

import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast, runtime_checkable
from uuid import uuid4

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserProject,
)

from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

SHARES_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/shares-provider"
SHARES_PROVIDER_SERVICE_V2 = "service:persistence.shares-provider"
SHARES_APPLICATION_MODULE_V2 = "builtin://memstack/application/shares-services"
SHARES_APPLICATION_SERVICE_V2 = "service:application.shares-services"
SHARES_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

_PROJECT_ADMIN_ROLES_V2 = frozenset({"admin", "owner"})


class SharesServiceErrorV2(Exception):
    """Base class for typed memory-share application failures."""


class SharesMemoryNotFoundV2(SharesServiceErrorV2):
    """The requested memory does not exist."""


class SharesAccessDeniedV2(SharesServiceErrorV2):
    """The caller cannot perform the requested share operation."""


class SharesInvalidTargetTypeV2(SharesServiceErrorV2):
    """The explicit target type is unsupported."""


class SharesInvalidPermissionLevelV2(SharesServiceErrorV2):
    """The explicit target permission is unsupported."""


class SharesTargetIdRequiredV2(SharesServiceErrorV2):
    """An explicit target is missing its identifier."""


class SharesTargetUserNotFoundV2(SharesServiceErrorV2):
    """The explicit user target does not exist."""


class SharesTargetProjectNotFoundV2(SharesServiceErrorV2):
    """The explicit project target does not exist."""


class SharesDuplicateTargetV2(SharesServiceErrorV2):
    """The memory already has a share for the explicit target."""


class SharesInvalidExpirationV2(SharesServiceErrorV2):
    """The absolute expiration value cannot be parsed."""


class SharesShareNotFoundV2(SharesServiceErrorV2):
    """The requested share record does not exist."""


class SharesWrongMemoryV2(SharesServiceErrorV2):
    """The share belongs to a different memory."""


class SharesLinkNotFoundV2(SharesServiceErrorV2):
    """The public bearer link does not exist."""


class SharesLinkExpiredV2(SharesServiceErrorV2):
    """The public bearer link has expired."""


class SharesViewDeniedV2(SharesServiceErrorV2):
    """The public bearer link does not explicitly grant view access."""


@dataclass(frozen=True, kw_only=True)
class SharesMemoryRecordV2:
    """Persistence-neutral memory fields exposed by share operations."""

    id: str
    project_id: str
    title: str
    content: str
    tags: tuple[str, ...]
    author_id: str
    created_at: datetime
    updated_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class SharesRecordV2:
    """Persistence-neutral memory-share fields."""

    id: str
    memory_id: str
    share_token: str | None
    shared_with_user_id: str | None
    shared_with_project_id: str | None
    permissions: object
    expires_at: datetime | None
    created_at: datetime
    access_count: int


@dataclass(frozen=True, kw_only=True)
class SharedMemoryAccessV2:
    """Public payload plus non-secret identifiers required for audit logging."""

    payload: dict[str, Any]
    memory_id: str
    share_id: str


@runtime_checkable
class SharesPersistenceProtocolV2(Protocol):
    """Share persistence hidden behind the generation-owned Provider."""

    async def get_memory(self, *, memory_id: str) -> SharesMemoryRecordV2 | None: ...

    async def has_project_admin_access(self, *, user_id: str, project_id: str) -> bool: ...

    async def user_exists(self, *, user_id: str) -> bool: ...

    async def project_exists(self, *, project_id: str) -> bool: ...

    async def find_target_share(
        self,
        *,
        memory_id: str,
        target_type: str,
        target_id: str,
    ) -> SharesRecordV2 | None: ...

    async def create_share(
        self,
        *,
        memory_id: str,
        shared_with_user_id: str | None,
        shared_with_project_id: str | None,
        share_token: str,
        shared_by: str,
        permissions: object,
        expires_at: datetime | None,
    ) -> SharesRecordV2: ...

    async def list_shares(self, *, memory_id: str) -> Sequence[SharesRecordV2]: ...

    async def get_share(self, *, share_id: str) -> SharesRecordV2 | None: ...

    async def delete_share(self, *, share_id: str) -> None: ...

    async def get_share_by_token(self, *, share_token: str) -> SharesRecordV2 | None: ...

    async def increment_access_count(self, *, share_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class SqlSharesPersistenceV2:
    """SQL share persistence bound to one operation-owned session."""

    _session: AsyncSession

    async def get_memory(self, *, memory_id: str) -> SharesMemoryRecordV2 | None:
        result = await self._session.execute(
            refresh_select_statement(select(Memory).where(Memory.id == memory_id))
        )
        memory = result.scalar_one_or_none()
        return _memory_record_v2(memory) if memory is not None else None

    async def has_project_admin_access(self, *, user_id: str, project_id: str) -> bool:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject.id).where(
                    and_(
                        UserProject.user_id == user_id,
                        UserProject.project_id == project_id,
                        UserProject.role.in_(_PROJECT_ADMIN_ROLES_V2),
                    )
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def user_exists(self, *, user_id: str) -> bool:
        result = await self._session.execute(
            refresh_select_statement(select(User.id).where(User.id == user_id))
        )
        return result.scalar_one_or_none() is not None

    async def project_exists(self, *, project_id: str) -> bool:
        result = await self._session.execute(
            refresh_select_statement(select(Project.id).where(Project.id == project_id))
        )
        return result.scalar_one_or_none() is not None

    async def find_target_share(
        self,
        *,
        memory_id: str,
        target_type: str,
        target_id: str,
    ) -> SharesRecordV2 | None:
        target_column = (
            MemoryShare.shared_with_user_id
            if target_type == "user"
            else MemoryShare.shared_with_project_id
        )
        result = await self._session.execute(
            refresh_select_statement(
                select(MemoryShare).where(
                    MemoryShare.memory_id == memory_id,
                    target_column == target_id,
                )
            )
        )
        share = result.scalar_one_or_none()
        return _share_record_v2(share) if share is not None else None

    async def create_share(
        self,
        *,
        memory_id: str,
        shared_with_user_id: str | None,
        shared_with_project_id: str | None,
        share_token: str,
        shared_by: str,
        permissions: object,
        expires_at: datetime | None,
    ) -> SharesRecordV2:
        share = MemoryShare(
            id=str(uuid4()),
            memory_id=memory_id,
            shared_with_user_id=shared_with_user_id,
            shared_with_project_id=shared_with_project_id,
            share_token=share_token,
            shared_by=shared_by,
            permissions=cast("dict[str, Any]", permissions),
            expires_at=expires_at,
            access_count=0,
        )
        self._session.add(share)
        await self._session.flush()
        return _share_record_v2(share)

    async def list_shares(self, *, memory_id: str) -> Sequence[SharesRecordV2]:
        result = await self._session.execute(
            refresh_select_statement(
                select(MemoryShare)
                .where(MemoryShare.memory_id == memory_id)
                .order_by(MemoryShare.created_at.desc())
            )
        )
        return tuple(_share_record_v2(share) for share in result.scalars().all())

    async def get_share(self, *, share_id: str) -> SharesRecordV2 | None:
        result = await self._session.execute(
            refresh_select_statement(select(MemoryShare).where(MemoryShare.id == share_id))
        )
        share = result.scalar_one_or_none()
        return _share_record_v2(share) if share is not None else None

    async def delete_share(self, *, share_id: str) -> None:
        share = await self._session.get(MemoryShare, share_id)
        if share is not None:
            await self._session.delete(share)
            await self._session.flush()

    async def get_share_by_token(self, *, share_token: str) -> SharesRecordV2 | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(MemoryShare).where(MemoryShare.share_token == share_token)
            )
        )
        share = result.scalar_one_or_none()
        return _share_record_v2(share) if share is not None else None

    async def increment_access_count(self, *, share_id: str) -> None:
        share = await self._session.get(MemoryShare, share_id)
        if share is None:
            raise SharesShareNotFoundV2
        share.access_count += 1
        await self._session.flush()


def _memory_record_v2(memory: Memory) -> SharesMemoryRecordV2:
    return SharesMemoryRecordV2(
        id=memory.id,
        project_id=memory.project_id,
        title=memory.title,
        content=memory.content,
        tags=tuple(memory.tags),
        author_id=memory.author_id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _share_record_v2(share: MemoryShare) -> SharesRecordV2:
    return SharesRecordV2(
        id=share.id,
        memory_id=share.memory_id,
        share_token=share.share_token,
        shared_with_user_id=share.shared_with_user_id,
        shared_with_project_id=share.shared_with_project_id,
        permissions=share.permissions,
        expires_at=share.expires_at,
        created_at=share.created_at,
        access_count=share.access_count,
    )


@dataclass(frozen=True, kw_only=True)
class SharesApplicationServiceV2:
    """Memory-share policy and response composition for one operation."""

    persistence: SharesPersistenceProtocolV2

    async def create_share(
        self,
        *,
        memory_id: str,
        user_id: str,
        share_data: Mapping[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        memory = await self._memory_or_error(memory_id=memory_id)
        if memory.author_id != user_id:
            raise SharesAccessDeniedV2

        target_type = share_data.get("target_type")
        permission_level = share_data.get("permission_level")
        target_id = share_data.get("target_id")
        validated_target_id: str | None = None
        if target_type:
            if target_type not in {"user", "project"}:
                raise SharesInvalidTargetTypeV2
            if permission_level not in {"view", "edit"}:
                raise SharesInvalidPermissionLevelV2
            if not isinstance(target_id, str) or not target_id.strip():
                raise SharesTargetIdRequiredV2
            validated_target_id = target_id.strip()
            await self._authorize_target(
                user_id=user_id,
                target_type=cast("str", target_type),
                target_id=validated_target_id,
            )
            existing = await self.persistence.find_target_share(
                memory_id=memory_id,
                target_type=cast("str", target_type),
                target_id=validated_target_id,
            )
            if existing is not None:
                raise SharesDuplicateTargetV2

        effective_now = now or datetime.now(UTC)
        expires_at = _parse_share_expiration_v2(share_data, now=effective_now)
        default_permissions = {
            "view": True,
            "edit": permission_level == "edit" if permission_level else False,
        }
        permissions = share_data.get("permissions", default_permissions)
        share = await self.persistence.create_share(
            memory_id=memory_id,
            shared_with_user_id=validated_target_id if target_type == "user" else None,
            shared_with_project_id=validated_target_id if target_type == "project" else None,
            share_token=secrets.token_urlsafe(32),
            shared_by=user_id,
            permissions=permissions,
            expires_at=expires_at,
        )
        return _created_share_payload_v2(share)

    async def list_shares(self, *, memory_id: str, user_id: str) -> dict[str, Any]:
        memory = await self._memory_or_error(memory_id=memory_id)
        await self._require_memory_management_access(memory=memory, user_id=user_id)
        shares = await self.persistence.list_shares(memory_id=memory_id)
        return {"shares": [_listed_share_payload_v2(share) for share in shares]}

    async def delete_share(self, *, memory_id: str, share_id: str, user_id: str) -> None:
        memory = await self._memory_or_error(memory_id=memory_id)
        await self._require_memory_management_access(memory=memory, user_id=user_id)
        share = await self.persistence.get_share(share_id=share_id)
        if share is None:
            raise SharesShareNotFoundV2
        if share.memory_id != memory_id:
            raise SharesWrongMemoryV2
        await self.persistence.delete_share(share_id=share_id)

    async def get_shared_memory(
        self,
        *,
        share_token: str,
        now: datetime | None = None,
    ) -> SharedMemoryAccessV2:
        share = await self.persistence.get_share_by_token(share_token=share_token)
        if share is None:
            raise SharesLinkNotFoundV2
        effective_now = now or datetime.now(UTC)
        if share.expires_at is not None and _as_utc_v2(share.expires_at) < effective_now:
            raise SharesLinkExpiredV2
        if not _share_can_view_v2(share.permissions):
            raise SharesViewDeniedV2
        memory = await self._memory_or_error(memory_id=share.memory_id)
        await self.persistence.increment_access_count(share_id=share.id)
        return SharedMemoryAccessV2(
            payload={
                "memory": {
                    "id": memory.id,
                    "title": memory.title,
                    "content": memory.content,
                    "tags": list(memory.tags),
                    "created_at": memory.created_at.isoformat(),
                    "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
                },
                "share": {
                    "permissions": share.permissions,
                    "expires_at": share.expires_at.isoformat() if share.expires_at else None,
                },
            },
            memory_id=memory.id,
            share_id=share.id,
        )

    async def _memory_or_error(self, *, memory_id: str) -> SharesMemoryRecordV2:
        memory = await self.persistence.get_memory(memory_id=memory_id)
        if memory is None:
            raise SharesMemoryNotFoundV2
        return memory

    async def _authorize_target(
        self,
        *,
        user_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        if target_type == "user":
            if not await self.persistence.user_exists(user_id=target_id):
                raise SharesTargetUserNotFoundV2
            return
        if not await self.persistence.project_exists(project_id=target_id):
            raise SharesTargetProjectNotFoundV2
        if not await self.persistence.has_project_admin_access(
            user_id=user_id,
            project_id=target_id,
        ):
            raise SharesAccessDeniedV2

    async def _require_memory_management_access(
        self,
        *,
        memory: SharesMemoryRecordV2,
        user_id: str,
    ) -> None:
        if memory.author_id == user_id:
            return
        if not await self.persistence.has_project_admin_access(
            user_id=user_id,
            project_id=memory.project_id,
        ):
            raise SharesAccessDeniedV2


def _parse_share_expiration_v2(
    share_data: Mapping[str, Any],
    *,
    now: datetime,
) -> datetime | None:
    if share_data.get("expires_at"):
        try:
            return datetime.fromisoformat(share_data["expires_at"])
        except (TypeError, ValueError):
            raise SharesInvalidExpirationV2 from None
    if "expires_in_days" in share_data:
        days = share_data["expires_in_days"]
        if isinstance(days, int) and days > 0:
            return now + timedelta(days=days)
    return None


def _as_utc_v2(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _share_can_view_v2(permissions: object) -> bool:
    if not isinstance(permissions, Mapping):
        return False
    return cast("Mapping[str, object]", permissions).get("view") is True


def _created_share_payload_v2(share: SharesRecordV2) -> dict[str, Any]:
    return {
        "id": share.id,
        "share_token": share.share_token,
        "memory_id": share.memory_id,
        "shared_with_user_id": share.shared_with_user_id,
        "shared_with_project_id": share.shared_with_project_id,
        "permissions": share.permissions,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "created_at": share.created_at.isoformat(),
        "access_count": share.access_count,
    }


def _listed_share_payload_v2(share: SharesRecordV2) -> dict[str, Any]:
    return {
        "id": share.id,
        "share_token": share.share_token,
        "permissions": share.permissions,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "created_at": share.created_at.isoformat(),
        "access_count": share.access_count,
    }


@dataclass(frozen=True, kw_only=True)
class SharesApplicationServicesV2:
    """Operation-owned share application services consumed by HTTP handlers."""

    shares: SharesApplicationServiceV2


@runtime_checkable
class SharesServiceFactoryProtocolV2(Protocol):
    """Build share persistence without exposing SQL implementations to Consumers."""

    def build(self, operation: OperationContextV2) -> SharesPersistenceProtocolV2: ...


@runtime_checkable
class SharesApplicationResolverProtocolV2(Protocol):
    """Resolve share services through the Provider alias declared by the Profile."""

    def resolve(self, operation: OperationContextV2) -> SharesApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlSharesServiceFactoryV2:
    """Bind share persistence to the operation's exact AsyncSession."""

    def build(self, operation: OperationContextV2) -> SharesPersistenceProtocolV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "shares services require an AsyncSession operation service",
            )
        return SqlSharesPersistenceV2(_session=db)


@dataclass(frozen=True, kw_only=True)
class SharesApplicationResolverV2:
    """Consumer seam for the explicitly selected share persistence Provider."""

    provider: SharesServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> SharesApplicationServicesV2:
        persistence = self.provider.build(operation)
        return SharesApplicationServicesV2(
            shares=SharesApplicationServiceV2(persistence=persistence)
        )


def _apply_shares_provider_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("shares provider requires strategy operation-async-session")
    _ = context.provide(
        SHARES_PROVIDER_SERVICE_V2,
        SqlSharesServiceFactoryV2(),
        label="shares-provider",
    )


def _apply_shares_application_v2(context: ContextV2, config: Mapping[str, Any]) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError("shares resolver requires strategy operation-scoped-provider")
    provider = context.require(SHARES_PROVIDER_INJECT_V2)
    if not isinstance(provider, SharesServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_shares_provider",
            "shares provider inject does not implement the factory contract",
        )
    _ = context.provide(
        SHARES_APPLICATION_SERVICE_V2,
        SharesApplicationResolverV2(provider=provider),
        label="shares-application",
    )


def shares_service_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return independent share persistence Provider and application Consumer definitions."""
    return (
        PluginDefinitionV2(
            module_ref=SHARES_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SHARES_PROVIDER_MODULE_V2),
            apply=_apply_shares_provider_v2,
        ),
        PluginDefinitionV2(
            module_ref=SHARES_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(SHARES_APPLICATION_MODULE_V2),
            apply=_apply_shares_application_v2,
        ),
    )


__all__ = [
    "SHARES_APPLICATION_MODULE_V2",
    "SHARES_APPLICATION_SERVICE_V2",
    "SHARES_PROVIDER_INJECT_V2",
    "SHARES_PROVIDER_MODULE_V2",
    "SHARES_PROVIDER_SERVICE_V2",
    "SharedMemoryAccessV2",
    "SharesAccessDeniedV2",
    "SharesApplicationResolverProtocolV2",
    "SharesApplicationResolverV2",
    "SharesApplicationServiceV2",
    "SharesApplicationServicesV2",
    "SharesDuplicateTargetV2",
    "SharesInvalidExpirationV2",
    "SharesInvalidPermissionLevelV2",
    "SharesInvalidTargetTypeV2",
    "SharesLinkExpiredV2",
    "SharesLinkNotFoundV2",
    "SharesMemoryNotFoundV2",
    "SharesPersistenceProtocolV2",
    "SharesServiceErrorV2",
    "SharesServiceFactoryProtocolV2",
    "SharesShareNotFoundV2",
    "SharesTargetIdRequiredV2",
    "SharesTargetProjectNotFoundV2",
    "SharesTargetUserNotFoundV2",
    "SharesViewDeniedV2",
    "SharesWrongMemoryV2",
    "SqlSharesPersistenceV2",
    "SqlSharesServiceFactoryV2",
    "shares_service_definitions_v2",
]
