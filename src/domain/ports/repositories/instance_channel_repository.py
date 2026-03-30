"""Repository interface for InstanceChannelConfig entity."""

from abc import ABC, abstractmethod

from src.domain.model.instance.instance_channel import InstanceChannelConfig


class InstanceChannelRepository(ABC):
    """Repository interface for InstanceChannelConfig entity."""

    @abstractmethod
    async def find_by_id(self, channel_id: str) -> InstanceChannelConfig | None:
        """Find a channel config by ID (excluding soft-deleted)."""

    @abstractmethod
    async def find_by_instance_id(self, instance_id: str) -> list[InstanceChannelConfig]:
        """List all channel configs for an instance (excluding soft-deleted)."""

    @abstractmethod
    async def save(self, entity: InstanceChannelConfig) -> InstanceChannelConfig:
        """Create a new channel config. Returns the saved entity."""

    @abstractmethod
    async def update(self, entity: InstanceChannelConfig) -> InstanceChannelConfig:
        """Update an existing channel config. Returns the updated entity."""

    @abstractmethod
    async def delete(self, channel_id: str) -> None:
        """Soft-delete a channel config by setting deleted_at."""
