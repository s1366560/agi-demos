"""SQL adapter for context summary persistence using conversation meta JSON.

Stores context summaries in the conversation.meta["context_summary"] field,
avoiding the need for a new database table or Alembic migration.
"""

import logging
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.conversation.context_summary import ContextSummary
from src.domain.ports.agent.context_manager_port import ContextSummaryPort
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
)

logger = logging.getLogger(__name__)

SUMMARY_KEY = "context_summary"


class SqlContextSummaryAdapter(ContextSummaryPort):
    """Persists context summaries in conversation.meta JSON column."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, conversation_id: str) -> Optional[ContextSummary]:
        """Load cached context summary from conversation metadata."""
        from sqlalchemy import select

        result = await self._session.execute(
            select(DBConversation.meta).where(DBConversation.id == conversation_id)
        )
        meta = result.scalar_one_or_none()
        if not meta or SUMMARY_KEY not in meta:
            return None

        try:
            return ContextSummary.from_dict(meta[SUMMARY_KEY])
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"Invalid context summary in conversation {conversation_id}: {e}")
            return None

    async def save_summary(self, conversation_id: str, summary: ContextSummary) -> None:
        """Save context summary into conversation.meta JSON."""
        from sqlalchemy import select

        # Read current meta, merge summary, write back
        result = await self._session.execute(
            select(DBConversation.meta).where(DBConversation.id == conversation_id)
        )
        current_meta = result.scalar_one_or_none() or {}
        updated_meta = {**current_meta, SUMMARY_KEY: summary.to_dict()}

        await self._session.execute(
            update(DBConversation)
            .where(DBConversation.id == conversation_id)
            .values(meta=updated_meta)
        )
        await self._session.flush()

        logger.info(
            f"Saved context summary for conversation {conversation_id}: "
            f"{summary.messages_covered_count} messages, "
            f"{summary.summary_tokens} tokens, "
            f"level={summary.compression_level}"
        )

    async def invalidate_summary(self, conversation_id: str) -> None:
        """Remove cached summary from conversation metadata."""
        from sqlalchemy import select

        result = await self._session.execute(
            select(DBConversation.meta).where(DBConversation.id == conversation_id)
        )
        current_meta = result.scalar_one_or_none() or {}

        if SUMMARY_KEY in current_meta:
            updated_meta = {k: v for k, v in current_meta.items() if k != SUMMARY_KEY}
            await self._session.execute(
                update(DBConversation)
                .where(DBConversation.id == conversation_id)
                .values(meta=updated_meta)
            )
            await self._session.flush()
            logger.info(f"Invalidated context summary for conversation {conversation_id}")
