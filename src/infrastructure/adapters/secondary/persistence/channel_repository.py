"""Channel configuration repository."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine import CursorResult

from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelOutboxModel,
    ChannelSessionBindingModel,
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

    async def get_by_id(self, config_id: str) -> ChannelConfigModel | None:
        """Get configuration by ID."""
        result = await self._session.execute(
            select(ChannelConfigModel).where(ChannelConfigModel.id == config_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: str, channel_type: str | None = None, enabled_only: bool = False
    ) -> list[ChannelConfigModel]:
        """List configurations for a project."""
        query = select(ChannelConfigModel).where(ChannelConfigModel.project_id == project_id)

        if channel_type:
            query = query.where(ChannelConfigModel.channel_type == channel_type)

        if enabled_only:
            query = query.where(ChannelConfigModel.enabled.is_(True))

        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_all_enabled(self) -> list[ChannelConfigModel]:
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

    async def update_status(self, config_id: str, status: str, error: str | None = None) -> bool:
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
    ) -> list["ChannelMessageModel"]:
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


class ChannelSessionBindingRepository:
    """Repository for deterministic channel session bindings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_session_key(
        self,
        project_id: str,
        session_key: str,
    ) -> ChannelSessionBindingModel | None:
        """Get binding by project and deterministic session key."""
        result = await self._session.execute(
            select(ChannelSessionBindingModel).where(
                ChannelSessionBindingModel.project_id == project_id,
                ChannelSessionBindingModel.session_key == session_key,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_conversation_id(
        self,
        conversation_id: str,
    ) -> ChannelSessionBindingModel | None:
        """Get binding by conversation ID."""
        result = await self._session.execute(
            select(ChannelSessionBindingModel).where(
                ChannelSessionBindingModel.conversation_id == conversation_id
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        project_id: str,
        channel_config_id: str,
        conversation_id: str,
        channel_type: str,
        chat_id: str,
        chat_type: str,
        session_key: str,
        thread_id: str | None = None,
        topic_id: str | None = None,
    ) -> ChannelSessionBindingModel:
        """Create a deterministic session binding if absent."""
        existing = await self.get_by_session_key(project_id, session_key)
        if existing:
            return existing

        binding = ChannelSessionBindingModel(
            project_id=project_id,
            channel_config_id=channel_config_id,
            conversation_id=conversation_id,
            channel_type=channel_type,
            chat_id=chat_id,
            chat_type=chat_type,
            thread_id=thread_id,
            topic_id=topic_id,
            session_key=session_key,
        )
        if not binding.id:
            binding.id = ChannelSessionBindingModel.generate_id()
        try:
            async with self._session.begin_nested():
                self._session.add(binding)
                await self._session.flush()
            return binding
        except IntegrityError:
            existing = await self.get_by_session_key(project_id, session_key)
            if existing:
                return existing
            raise


class ChannelOutboxRepository:
    """Repository for outbound delivery queue records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, item: ChannelOutboxModel) -> ChannelOutboxModel:
        """Create a new outbox message record."""
        if not item.id:
            item.id = ChannelOutboxModel.generate_id()
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_by_id(self, outbox_id: str) -> ChannelOutboxModel | None:
        """Get outbox record by ID."""
        result = await self._session.execute(
            select(ChannelOutboxModel).where(ChannelOutboxModel.id == outbox_id)
        )
        return result.scalar_one_or_none()

    async def mark_sent(self, outbox_id: str, sent_channel_message_id: str | None) -> bool:
        """Mark outbox message as sent."""
        result = await self._session.execute(
            update(ChannelOutboxModel)
            .where(
                ChannelOutboxModel.id == outbox_id,
                ChannelOutboxModel.status.in_(("pending", "failed")),
            )
            .values(
                status="sent",
                sent_channel_message_id=sent_channel_message_id,
                last_error=None,
                next_retry_at=None,
            )
        )
        await self._session.flush()
        return cast(CursorResult[Any], result).rowcount > 0

    async def mark_failed(self, outbox_id: str, error_message: str) -> bool:
        """Mark outbox message as failed/dead-letter with retry backoff."""
        current_result = await self._session.execute(
            select(ChannelOutboxModel.attempt_count, ChannelOutboxModel.max_attempts)
            .where(
                ChannelOutboxModel.id == outbox_id,
                ChannelOutboxModel.status.in_(("pending", "failed")),
            )
            .with_for_update()
        )
        current = current_result.one_or_none()
        if current is None:
            return False

        current_attempt_count, max_attempts = current
        next_attempt_count = int(current_attempt_count) + 1
        move_to_dead_letter = next_attempt_count >= int(max_attempts)
        next_retry_at = None
        if not move_to_dead_letter:
            backoff_seconds = min(2**next_attempt_count, 300)
            next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)

        result = await self._session.execute(
            update(ChannelOutboxModel)
            .where(
                ChannelOutboxModel.id == outbox_id,
                ChannelOutboxModel.status.in_(("pending", "failed")),
                ChannelOutboxModel.attempt_count == int(current_attempt_count),
            )
            .values(
                attempt_count=next_attempt_count,
                last_error=error_message,
                status="dead_letter" if move_to_dead_letter else "failed",
                next_retry_at=next_retry_at,
            )
        )
        await self._session.flush()
        return cast(CursorResult[Any], result).rowcount > 0

    async def list_pending_retry(self, limit: int = 20) -> list[ChannelOutboxModel]:
        """List outbox messages eligible for retry.

        Returns failed messages whose next_retry_at has passed.
        """
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(ChannelOutboxModel)
            .where(
                ChannelOutboxModel.status == "failed",
                ChannelOutboxModel.next_retry_at <= now,
            )
            .order_by(ChannelOutboxModel.next_retry_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
