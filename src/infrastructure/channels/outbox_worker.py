"""Outbox retry worker for reliable channel message delivery.

This background task polls the outbox table for failed messages whose
next_retry_at has passed, and attempts to resend them via the appropriate
channel adapter.
"""


from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.infrastructure.adapters.secondary.persistence.channel_models import ChannelOutboxModel
    from src.infrastructure.adapters.secondary.persistence.channel_repository import (
        ChannelOutboxRepository,
    )

logger = logging.getLogger(__name__)

OUTBOX_POLL_INTERVAL = 30  # seconds between polls
OUTBOX_BATCH_SIZE = 20  # max messages per poll cycle


class OutboxRetryWorker:
    """Background worker that retries failed outbox messages."""

    def __init__(
        self,
        session_factory: Callable[..., Any],
        get_connection_fn: Callable[[str], Any],
    ) -> None:
        self._session_factory = session_factory
        self._get_connection = get_connection_fn
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self) -> None:
        """Start the background retry loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[OutboxWorker] Started")

    async def stop(self) -> None:
        """Stop the background retry loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[OutboxWorker] Stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await asyncio.sleep(OUTBOX_POLL_INTERVAL)
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[OutboxWorker] Poll error: {e}", exc_info=True)

    async def _process_batch(self) -> None:
        """Process a batch of retryable outbox messages."""
        from src.infrastructure.adapters.secondary.persistence.channel_repository import (
            ChannelOutboxRepository,
        )

        async with self._session_factory() as session:
            repo = ChannelOutboxRepository(session)
            items = await repo.list_pending_retry(limit=OUTBOX_BATCH_SIZE)

            if not items:
                return

            logger.info(f"[OutboxWorker] Processing {len(items)} retryable messages")

            for item in items:
                await self._retry_item(item, repo, session)

    async def _retry_item(self, item: ChannelOutboxModel, repo: ChannelOutboxRepository, session: AsyncSession) -> None:
        """Retry a single outbox message."""
        try:
            connection = self._get_connection(item.channel_config_id)
            if not connection:
                await repo.mark_failed(item.id, "no active connection")
                await session.commit()
                return

            adapter = connection.adapter
            if not getattr(adapter, "connected", False):
                await repo.mark_failed(item.id, "adapter disconnected")
                await session.commit()
                return

            sent_message_id = await adapter.send_text(
                item.chat_id,
                item.content_text,
                reply_to=item.reply_to_channel_message_id,
            )

            await repo.mark_sent(item.id, sent_message_id)
            await session.commit()
            logger.info(
                f"[OutboxWorker] Retried successfully: outbox_id={item.id}, "
                f"sent_id={sent_message_id}"
            )

        except Exception as e:
            try:
                await repo.mark_failed(item.id, str(e))
                await session.commit()
            except Exception as commit_err:
                logger.warning(f"[OutboxWorker] Failed to update outbox status: {commit_err}")
            logger.warning(f"[OutboxWorker] Retry failed for {item.id}: {e}")
