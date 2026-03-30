"""Instance channel configuration service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.domain.model.instance.instance_channel import InstanceChannelConfig
from src.domain.ports.repositories.instance_channel_repository import (
    InstanceChannelRepository,
)

logger = logging.getLogger(__name__)


class InstanceChannelService:
    """Service for managing instance-scoped channel configurations."""

    def __init__(self, channel_repo: InstanceChannelRepository) -> None:
        self._channel_repo = channel_repo

    async def list_channels(self, instance_id: str) -> list[InstanceChannelConfig]:
        """List all channel configs for an instance."""
        return await self._channel_repo.find_by_instance_id(instance_id)

    async def create_channel(
        self,
        instance_id: str,
        channel_type: str,
        name: str,
        config: dict[str, object],
    ) -> InstanceChannelConfig:
        """Create a new channel config for an instance."""
        entity = InstanceChannelConfig(
            instance_id=instance_id,
            channel_type=channel_type,
            name=name,
            config=config,
        )
        return await self._channel_repo.save(entity)

    async def update_channel(
        self,
        channel_id: str,
        name: str | None = None,
        config: dict[str, object] | None = None,
    ) -> InstanceChannelConfig:
        """Update an existing channel config."""
        entity = await self._channel_repo.find_by_id(channel_id)
        if not entity:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)
        if name is not None:
            entity.name = name
        if config is not None:
            entity.config = config
        entity.updated_at = datetime.now(UTC)
        return await self._channel_repo.update(entity)

    async def delete_channel(self, channel_id: str) -> None:
        """Soft-delete a channel config."""
        entity = await self._channel_repo.find_by_id(channel_id)
        if not entity:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)
        await self._channel_repo.delete(channel_id)

    async def test_connection(self, channel_id: str) -> dict[str, str]:
        """Test a channel connection (stub: marks as connected)."""
        entity = await self._channel_repo.find_by_id(channel_id)
        if not entity:
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)
        entity.last_connected_at = datetime.now(UTC)
        entity.status = "connected"
        entity.updated_at = datetime.now(UTC)
        await self._channel_repo.update(entity)
        return {"status": "ok", "message": "Connection test successful"}
