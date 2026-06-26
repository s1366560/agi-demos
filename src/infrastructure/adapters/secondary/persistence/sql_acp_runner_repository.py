"""Persistence helpers for ACP runner pools and live runner state."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    ACPRunnerInstanceModel,
    ACPRunnerPoolModel,
    ACPRunnerSessionModel,
    ACPRunnerTokenModel,
)


def hash_runner_token(token: str) -> str:
    """Hash a runner registration token for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_runner_token() -> str:
    """Generate a plaintext token shown once to tenant admins."""
    return f"ms_acp_runner_{secrets.token_urlsafe(32)}"


class ACPRunnerRepository:
    """Repository for tenant-scoped ACP runner resources."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_pools_by_tenant(self, tenant_id: str) -> list[ACPRunnerPoolModel]:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerPoolModel)
                .where(
                    ACPRunnerPoolModel.tenant_id == tenant_id,
                    ACPRunnerPoolModel.deleted_at.is_(None),
                )
                .order_by(ACPRunnerPoolModel.name.asc(), ACPRunnerPoolModel.pool_key.asc())
            )
        )
        return list(result.scalars().all())

    async def list_pools_by_cluster(
        self,
        *,
        tenant_id: str,
        cluster_id: str,
    ) -> list[ACPRunnerPoolModel]:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerPoolModel)
                .where(
                    ACPRunnerPoolModel.tenant_id == tenant_id,
                    ACPRunnerPoolModel.cluster_id == cluster_id,
                    ACPRunnerPoolModel.deleted_at.is_(None),
                )
                .order_by(ACPRunnerPoolModel.name.asc(), ACPRunnerPoolModel.pool_key.asc())
            )
        )
        return list(result.scalars().all())

    async def get_pool_by_tenant_key(
        self,
        *,
        tenant_id: str,
        pool_key: str,
    ) -> ACPRunnerPoolModel | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerPoolModel).where(
                    ACPRunnerPoolModel.tenant_id == tenant_id,
                    ACPRunnerPoolModel.pool_key == pool_key,
                    ACPRunnerPoolModel.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_pool_by_id(self, pool_id: str) -> ACPRunnerPoolModel | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerPoolModel).where(
                    ACPRunnerPoolModel.id == pool_id,
                    ACPRunnerPoolModel.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_pool_by_cluster_key(
        self,
        *,
        tenant_id: str,
        cluster_id: str,
        pool_key: str,
    ) -> ACPRunnerPoolModel | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerPoolModel).where(
                    ACPRunnerPoolModel.tenant_id == tenant_id,
                    ACPRunnerPoolModel.cluster_id == cluster_id,
                    ACPRunnerPoolModel.pool_key == pool_key,
                    ACPRunnerPoolModel.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def create_pool(
        self,
        *,
        tenant_id: str,
        cluster_id: str,
        pool_key: str,
        name: str,
        mode: str,
        enabled: bool,
        labels: dict[str, Any],
        capacity_policy: dict[str, Any],
        scheduling_policy: dict[str, Any],
        created_by: str,
    ) -> ACPRunnerPoolModel:
        pool = ACPRunnerPoolModel(
            id=ACPRunnerPoolModel.generate_id(),
            tenant_id=tenant_id,
            cluster_id=cluster_id,
            pool_key=pool_key,
            name=name,
            mode=mode,
            enabled=enabled,
            labels=labels,
            capacity_policy=capacity_policy,
            scheduling_policy=scheduling_policy,
            created_by=created_by,
        )
        self._session.add(pool)
        await self._session.flush()
        return pool

    async def update_pool(
        self,
        pool: ACPRunnerPoolModel,
        *,
        name: str,
        mode: str,
        enabled: bool,
        labels: dict[str, Any],
        capacity_policy: dict[str, Any],
        scheduling_policy: dict[str, Any],
    ) -> ACPRunnerPoolModel:
        pool.name = name
        pool.mode = mode
        pool.enabled = enabled
        pool.labels = labels
        pool.capacity_policy = capacity_policy
        pool.scheduling_policy = scheduling_policy
        pool.updated_at = datetime.now(UTC)
        await self._session.flush()
        return pool

    async def list_instances_by_tenant(self, tenant_id: str) -> list[ACPRunnerInstanceModel]:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerInstanceModel).where(
                    ACPRunnerInstanceModel.tenant_id == tenant_id
                )
            )
        )
        return list(result.scalars().all())

    async def list_instances_by_pool(self, pool_id: str) -> list[ACPRunnerInstanceModel]:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerInstanceModel).where(ACPRunnerInstanceModel.pool_id == pool_id)
            )
        )
        return list(result.scalars().all())

    async def upsert_instance(
        self,
        *,
        pool: ACPRunnerPoolModel,
        runner_id: str,
        status: str,
        connection_id: str | None,
        version: str | None,
        capabilities: dict[str, Any],
        current_sessions: int,
        max_sessions: int,
        last_error: str | None,
    ) -> ACPRunnerInstanceModel:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerInstanceModel).where(
                    ACPRunnerInstanceModel.pool_id == pool.id,
                    ACPRunnerInstanceModel.runner_id == runner_id,
                )
            )
        )
        instance = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if instance is None:
            instance = ACPRunnerInstanceModel(
                id=ACPRunnerInstanceModel.generate_id(),
                pool_id=pool.id,
                tenant_id=pool.tenant_id,
                runner_id=runner_id,
                status=status,
                connection_id=connection_id,
                version=version,
                capabilities=capabilities,
                current_sessions=current_sessions,
                max_sessions=max_sessions,
                last_heartbeat_at=now,
                last_error=last_error,
            )
            self._session.add(instance)
        else:
            instance.status = status
            instance.connection_id = connection_id
            instance.version = version
            instance.capabilities = capabilities
            instance.current_sessions = current_sessions
            instance.max_sessions = max_sessions
            instance.last_heartbeat_at = now
            instance.last_error = last_error
            instance.updated_at = now
        await self._session.flush()
        return instance

    async def mark_runner_offline(
        self,
        *,
        tenant_id: str,
        runner_id: str,
        connection_id: str | None,
        last_error: str | None = None,
    ) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerInstanceModel).where(
                    ACPRunnerInstanceModel.tenant_id == tenant_id,
                    ACPRunnerInstanceModel.runner_id == runner_id,
                    ACPRunnerInstanceModel.connection_id == connection_id,
                )
            )
        )
        now = datetime.now(UTC)
        for instance in result.scalars().all():
            instance.status = "offline"
            instance.connection_id = None
            instance.last_error = last_error
            instance.updated_at = now
        await self._session.flush()

    async def create_registration_token(
        self,
        *,
        pool: ACPRunnerPoolModel,
        created_by: str,
        name: str | None = None,
        expires_in_hours: int = 24,
    ) -> tuple[ACPRunnerTokenModel, str]:
        token = generate_runner_token()
        row = ACPRunnerTokenModel(
            id=ACPRunnerTokenModel.generate_id(),
            pool_id=pool.id,
            tenant_id=pool.tenant_id,
            token_hash=hash_runner_token(token),
            name=name,
            expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        return row, token

    async def consume_registration_token(self, token: str) -> ACPRunnerTokenModel | None:
        token_hash = hash_runner_token(token)
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerTokenModel).where(ACPRunnerTokenModel.token_hash == token_hash)
            )
        )
        row = cast(ACPRunnerTokenModel | None, result.scalar_one_or_none())
        now = datetime.now(UTC)
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at < now:
            return None
        row.used_at = now
        await self._session.flush()
        return row

    async def create_session_mapping(
        self,
        *,
        session_id: str,
        tenant_id: str,
        pool_id: str,
        runner_id: str,
        agent_key: str,
        owner_user_id: str,
        remote_session_id: str | None,
    ) -> ACPRunnerSessionModel:
        now = datetime.now(UTC)
        row = ACPRunnerSessionModel(
            id=ACPRunnerSessionModel.generate_id(),
            session_id=session_id,
            tenant_id=tenant_id,
            pool_id=pool_id,
            runner_id=runner_id,
            agent_key=agent_key,
            owner_user_id=owner_user_id,
            remote_session_id=remote_session_id,
            status="active",
            last_activity_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def update_session_status(
        self,
        *,
        session_id: str,
        status: str,
        remote_session_id: str | None = None,
        last_error: str | None = None,
    ) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPRunnerSessionModel).where(ACPRunnerSessionModel.session_id == session_id)
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        row.status = status
        if remote_session_id is not None:
            row.remote_session_id = remote_session_id
        row.last_error = last_error
        row.last_activity_at = datetime.now(UTC)
        row.updated_at = row.last_activity_at
        await self._session.flush()
