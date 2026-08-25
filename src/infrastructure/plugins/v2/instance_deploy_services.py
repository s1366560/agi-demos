"""Generation-owned Provider/Consumer seams for instance and deploy operations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.deploy_service import DeployService
from src.application.services.instance_service import InstanceService
from src.domain.model.deploy.deploy_record import DeployRecord
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    DeployRecordModel,
    InstanceModel,
    User,
    UserTenant,
)
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

if TYPE_CHECKING:
    from redis.asyncio import Redis

INSTANCE_DEPLOY_PROVIDER_MODULE_V2 = "builtin://memstack/persistence/instance-deploy-provider"
INSTANCE_DEPLOY_PROVIDER_SERVICE_V2 = "service:persistence.instance-deploy-provider"
INSTANCE_DEPLOY_APPLICATION_MODULE_V2 = "builtin://memstack/application/instance-deploy-services"
INSTANCE_DEPLOY_APPLICATION_SERVICE_V2 = "service:application.instance-deploy-services"
INSTANCE_DEPLOY_PROVIDER_INJECT_V2 = "provider"
_OPERATION_DB_SESSION_SERVICE_V2 = "service:operation.db-session"

DisconnectCheckV2 = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, kw_only=True)
class InstanceMemberDirectoryV2:
    """Tenant-scoped user lookup seam used by instance membership routes."""

    _db: AsyncSession

    async def get_user(self, *, user_id: str, tenant_id: str) -> User | None:
        result = await self._db.execute(
            refresh_select_statement(
                select(User)
                .join(UserTenant, UserTenant.user_id == User.id)
                .where(
                    User.id == user_id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_users(
        self,
        *,
        user_ids: Sequence[str],
        tenant_id: str,
    ) -> dict[str, User]:
        if not user_ids:
            return {}
        result = await self._db.execute(
            refresh_select_statement(
                select(User)
                .join(UserTenant, UserTenant.user_id == User.id)
                .where(
                    User.id.in_(tuple(user_ids)),
                    UserTenant.tenant_id == tenant_id,
                )
            )
        )
        return {user.id: user for user in result.scalars().all()}

    async def search_users(
        self,
        *,
        tenant_id: str,
        query_text: str,
        limit: int,
    ) -> list[User]:
        tenant_user_ids = select(UserTenant.user_id).where(UserTenant.tenant_id == tenant_id)
        statement = select(User).where(
            User.is_active.is_(True),
            User.id.in_(tenant_user_ids),
        )
        if query_text:
            pattern = f"%{query_text}%"
            statement = statement.where(User.email.ilike(pattern) | User.full_name.ilike(pattern))
        statement = statement.order_by(User.full_name.asc(), User.email.asc()).limit(limit)
        result = await self._db.execute(refresh_select_statement(statement))
        return list(result.scalars().all())


@dataclass(frozen=True, kw_only=True)
class InstanceDeployAccessV2:
    """Structural tenant ownership and membership lookup for deploy resources."""

    _db: AsyncSession

    async def find_instance_tenant_id(self, instance_id: str) -> str | None:
        tenant_id = (
            await self._db.execute(
                refresh_select_statement(
                    select(InstanceModel.tenant_id).where(
                        InstanceModel.id == instance_id,
                        InstanceModel.deleted_at.is_(None),
                    )
                )
            )
        ).scalar_one_or_none()
        return str(tenant_id) if tenant_id is not None else None

    async def find_deploy_tenant_id(self, deploy_id: str) -> str | None:
        tenant_id = (
            await self._db.execute(
                refresh_select_statement(
                    select(InstanceModel.tenant_id)
                    .join(DeployRecordModel, DeployRecordModel.instance_id == InstanceModel.id)
                    .where(
                        DeployRecordModel.id == deploy_id,
                        DeployRecordModel.deleted_at.is_(None),
                        InstanceModel.deleted_at.is_(None),
                    )
                )
            )
        ).scalar_one_or_none()
        return str(tenant_id) if tenant_id is not None else None

    async def can_access_tenant(self, user: User, tenant_id: str) -> bool:
        if user.is_superuser:
            return True
        result = await self._db.execute(
            refresh_select_statement(
                select(UserTenant.id).where(
                    UserTenant.user_id == user.id,
                    UserTenant.tenant_id == tenant_id,
                )
            )
        )
        return result.scalar_one_or_none() is not None


@dataclass(frozen=True, kw_only=True)
class DeployProgressStreamV2:
    """Redis-backed deploy progress stream hidden behind the application seam."""

    _redis_client: object | None

    async def stream(
        self,
        *,
        record: DeployRecord,
        is_disconnected: DisconnectCheckV2 | None,
    ) -> AsyncIterator[str]:
        deploy_id = record.id
        status = record.status.value
        yield f"data: {json.dumps({'type': 'status', 'status': status, 'deploy_id': deploy_id})}\n\n"

        if record.is_terminal():
            yield f"data: {json.dumps({'type': 'done', 'status': status})}\n\n"
            return
        if self._redis_client is None:
            raise RuntimeV2Error(
                "deploy_progress_unavailable",
                "deploy progress requires the generation Redis provider",
            )

        redis_client = cast("Redis", self._redis_client)
        pubsub = redis_client.pubsub()
        channel_name = f"deploy:progress:{deploy_id}"
        await pubsub.subscribe(channel_name)
        try:
            while True:
                if is_disconnected is not None and await is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    raw_data: object = message["data"]
                    if isinstance(raw_data, bytes):
                        data = raw_data.decode("utf-8")
                    elif isinstance(raw_data, str):
                        data = raw_data
                    else:
                        continue
                    yield f"data: {data}\n\n"
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict) and parsed.get("type") == "done":
                            break
                    except (json.JSONDecodeError, TypeError):
                        pass
                else:
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.5)
        finally:
            await pubsub.unsubscribe(channel_name)
            await pubsub.aclose()


@dataclass(frozen=True, kw_only=True)
class InstanceDeployApplicationServicesV2:
    """Operation-owned instance, deploy, directory, access, and progress services."""

    instances: InstanceService
    deploys: DeployService
    directory: InstanceMemberDirectoryV2
    access: InstanceDeployAccessV2
    progress: DeployProgressStreamV2


@runtime_checkable
class InstanceDeployServiceFactoryProtocolV2(Protocol):
    """Build operation services without exposing persistence implementations."""

    def build(self, operation: OperationContextV2) -> InstanceDeployApplicationServicesV2: ...


@runtime_checkable
class InstanceDeployApplicationResolverProtocolV2(Protocol):
    """Resolve operation services through the Profile-selected Provider alias."""

    def resolve(self, operation: OperationContextV2) -> InstanceDeployApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class SqlInstanceDeployServiceFactoryV2:
    """Bind SQL and Redis adapters to one operation and pinned generation."""

    redis_client: object | None = None

    def build(self, operation: OperationContextV2) -> InstanceDeployApplicationServicesV2:
        db = operation.require(_OPERATION_DB_SESSION_SERVICE_V2)
        if not isinstance(db, AsyncSession):
            raise RuntimeV2Error(
                "invalid_operation_db_session",
                "instance/deploy services require an AsyncSession operation service",
            )
        instance_repository = SqlInstanceRepository(db)
        member_repository = SqlInstanceMemberRepository(db)
        deploy_repository = SqlDeployRecordRepository(db)
        return InstanceDeployApplicationServicesV2(
            instances=InstanceService(
                instance_repo=instance_repository,
                instance_member_repo=member_repository,
                deploy_record_repo=deploy_repository,
            ),
            deploys=DeployService(
                deploy_record_repo=deploy_repository,
                instance_repo=instance_repository,
                redis_client=cast("Redis | None", self.redis_client),
            ),
            directory=InstanceMemberDirectoryV2(_db=db),
            access=InstanceDeployAccessV2(_db=db),
            progress=DeployProgressStreamV2(_redis_client=self.redis_client),
        )


@dataclass(frozen=True, kw_only=True)
class InstanceDeployApplicationResolverV2:
    """Consumer seam for an explicitly selected instance/deploy Provider."""

    provider: InstanceDeployServiceFactoryProtocolV2

    def resolve(self, operation: OperationContextV2) -> InstanceDeployApplicationServicesV2:
        return self.provider.build(operation)


def _apply_instance_deploy_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
    *,
    redis_client: object | None = None,
) -> None:
    if config.get("strategy") != "operation-async-session":
        raise ValueError("instance/deploy provider requires strategy operation-async-session")
    _ = context.provide(
        INSTANCE_DEPLOY_PROVIDER_SERVICE_V2,
        SqlInstanceDeployServiceFactoryV2(redis_client=redis_client),
        label="instance-deploy-provider",
    )


def _apply_instance_deploy_application_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("strategy") != "operation-scoped-provider":
        raise ValueError(
            "instance/deploy application resolver requires strategy operation-scoped-provider"
        )
    provider = context.require(INSTANCE_DEPLOY_PROVIDER_INJECT_V2)
    if not isinstance(provider, InstanceDeployServiceFactoryProtocolV2):
        raise RuntimeV2Error(
            "invalid_instance_deploy_provider",
            "instance/deploy provider inject does not implement the factory contract",
        )
    _ = context.provide(
        INSTANCE_DEPLOY_APPLICATION_SERVICE_V2,
        InstanceDeployApplicationResolverV2(provider=provider),
        label="instance-deploy-application",
    )


def instance_deploy_service_definitions_v2(
    *,
    redis_client: object | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return independent Provider and Consumer definitions for instances/deploys."""

    def apply_provider(context: ContextV2, config: Mapping[str, Any]) -> None:
        _apply_instance_deploy_provider_v2(
            context,
            config,
            redis_client=redis_client,
        )

    return (
        PluginDefinitionV2(
            module_ref=INSTANCE_DEPLOY_PROVIDER_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_DEPLOY_PROVIDER_MODULE_V2),
            apply=apply_provider,
        ),
        PluginDefinitionV2(
            module_ref=INSTANCE_DEPLOY_APPLICATION_MODULE_V2,
            contract_digest=generated_contract_digest_v2(INSTANCE_DEPLOY_APPLICATION_MODULE_V2),
            apply=_apply_instance_deploy_application_v2,
        ),
    )


__all__ = [
    "INSTANCE_DEPLOY_APPLICATION_MODULE_V2",
    "INSTANCE_DEPLOY_APPLICATION_SERVICE_V2",
    "INSTANCE_DEPLOY_PROVIDER_INJECT_V2",
    "INSTANCE_DEPLOY_PROVIDER_MODULE_V2",
    "INSTANCE_DEPLOY_PROVIDER_SERVICE_V2",
    "DeployProgressStreamV2",
    "InstanceDeployAccessV2",
    "InstanceDeployApplicationResolverProtocolV2",
    "InstanceDeployApplicationResolverV2",
    "InstanceDeployApplicationServicesV2",
    "InstanceDeployServiceFactoryProtocolV2",
    "InstanceMemberDirectoryV2",
    "SqlInstanceDeployServiceFactoryV2",
    "instance_deploy_service_definitions_v2",
]
