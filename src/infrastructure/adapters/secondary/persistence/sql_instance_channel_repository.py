"""SQLAlchemy implementation of InstanceChannelRepository."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.instance.instance_channel import InstanceChannelConfig
from src.domain.ports.repositories.instance_channel_repository import (
    InstanceChannelRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    InstanceChannelConfigModel,
)

logger = logging.getLogger(__name__)


class SqlInstanceChannelRepository(InstanceChannelRepository):
    """SQLAlchemy implementation of InstanceChannelRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, channel_id: str) -> InstanceChannelConfig | None:
        """Find a channel config by ID (excluding soft-deleted)."""
        query = select(InstanceChannelConfigModel).where(
            InstanceChannelConfigModel.id == channel_id,
            InstanceChannelConfigModel.deleted_at.is_(None),
        )
        result = await self._session.execute(query)
        db_model = result.scalar_one_or_none()
        return self._to_domain(db_model)

    async def find_by_instance_id(self, instance_id: str) -> list[InstanceChannelConfig]:
        """List all channel configs for an instance (excluding soft-deleted)."""
        query = (
            select(InstanceChannelConfigModel)
            .where(
                InstanceChannelConfigModel.instance_id == instance_id,
                InstanceChannelConfigModel.deleted_at.is_(None),
            )
            .order_by(InstanceChannelConfigModel.created_at.desc())
        )
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [self._to_domain(r) for r in rows]

    async def save(self, entity: InstanceChannelConfig) -> InstanceChannelConfig:
        """Create a new channel config."""
        db_model = self._to_db(entity)
        self._session.add(db_model)
        await self._session.flush()
        return entity

    async def update(self, entity: InstanceChannelConfig) -> InstanceChannelConfig:
        """Update an existing channel config."""
        stmt = (
            update(InstanceChannelConfigModel)
            .where(InstanceChannelConfigModel.id == entity.id)
            .values(
                name=entity.name,
                config=entity.config,
                status=entity.status,
                last_connected_at=entity.last_connected_at,
                updated_at=entity.updated_at,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return entity

    async def delete(self, channel_id: str) -> None:
        """Soft-delete a channel config by setting deleted_at."""
        stmt = (
            update(InstanceChannelConfigModel)
            .where(InstanceChannelConfigModel.id == channel_id)
            .values(deleted_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)
        await self._session.flush()

    def _to_domain(self, db_model: InstanceChannelConfigModel | None) -> InstanceChannelConfig:
        """Convert database model to domain entity."""
        if db_model is None:
            msg = "Cannot convert None to InstanceChannelConfig"
            raise ValueError(msg)
        return InstanceChannelConfig(
            id=db_model.id,
            instance_id=db_model.instance_id,
            channel_type=db_model.channel_type,
            name=db_model.name,
            config=db_model.config or {},
            status=db_model.status,
            last_connected_at=db_model.last_connected_at,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            deleted_at=db_model.deleted_at,
        )

    def _to_db(self, entity: InstanceChannelConfig) -> InstanceChannelConfigModel:
        """Convert domain entity to database model."""
        return InstanceChannelConfigModel(
            id=entity.id,
            instance_id=entity.instance_id,
            channel_type=entity.channel_type,
            name=entity.name,
            config=entity.config,
            status=entity.status,
            last_connected_at=entity.last_connected_at,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            deleted_at=entity.deleted_at,
        )
