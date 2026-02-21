"""Channel configuration repository."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
)

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.channel_models import (
        ChannelMessageModel,
    )


class ChannelConfigRepository:
    """Repository for channel configuration persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, config: ChannelConfigModel) -> ChannelConfigModel:
        """Create a new channel configuration."""
        if not config.id:
            config.id = ChannelConfigModel.generate_id()

        self._session.add(config)
        await self._session.flush()
        return config

    async def get_by_id(self, config_id: str) -> Optional[ChannelConfigModel]:
        """Get configuration by ID."""
        result = await self._session.execute(
            select(ChannelConfigModel).where(ChannelConfigModel.id == config_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: str, channel_type: Optional[str] = None, enabled_only: bool = False
    ) -> List[ChannelConfigModel]:
        """List configurations for a project."""
        query = select(ChannelConfigModel).where(ChannelConfigModel.project_id == project_id)

        if channel_type:
            query = query.where(ChannelConfigModel.channel_type == channel_type)

        if enabled_only:
            query = query.where(ChannelConfigModel.enabled.is_(True))

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_all_enabled(self) -> List[ChannelConfigModel]:
        """List all enabled configurations across all projects.

        Used by ChannelConnectionManager to load configurations at startup.

        Returns:
            List of all enabled channel configurations.
        """
        query = select(ChannelConfigModel).where(ChannelConfigModel.enabled.is_(True))
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def update(self, config: ChannelConfigModel) -> ChannelConfigModel:
        """Update configuration."""
        await self._session.merge(config)
        await self._session.flush()
        return config

    async def delete(self, config_id: str) -> bool:
        """Delete configuration."""
        config = await self.get_by_id(config_id)
        if config:
            await self._session.delete(config)
            await self._session.flush()
            return True
        return False

    async def update_status(self, config_id: str, status: str, error: Optional[str] = None) -> bool:
        """Update connection status."""
        config = await self.get_by_id(config_id)
        if not config:
            return False

        config.status = status
        if error is not None:
            config.last_error = error

        await self._session.flush()
        return True


class ChannelMessageRepository:
    """Repository for channel message history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, message: "ChannelMessageModel") -> "ChannelMessageModel":
        """Store a message."""
        from src.infrastructure.adapters.secondary.persistence.channel_models import (
            ChannelMessageModel,
        )

        if not message.id:
            message.id = ChannelMessageModel.generate_id()

        self._session.add(message)
        await self._session.flush()
        return message

    async def list_by_chat(
        self,
        project_id: str,
        chat_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List["ChannelMessageModel"]:
        """List messages in a chat."""
        from src.infrastructure.adapters.secondary.persistence.channel_models import (
            ChannelMessageModel,
        )

        result = await self._session.execute(
            select(ChannelMessageModel)
            .where(
                ChannelMessageModel.project_id == project_id,
                ChannelMessageModel.chat_id == chat_id,
            )
            .order_by(ChannelMessageModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
