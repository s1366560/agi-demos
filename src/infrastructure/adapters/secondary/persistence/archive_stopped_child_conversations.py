"""Persist legal conversation status after a child session is stopped.

``conversations.status`` only accepts ``active``, ``archived``, and
``deleted``. Spawn-record / agent-session status may be ``stopped``, but that
value is not a legal conversation status and must not be written here.

The durable "ended but retained" state for a stopped child conversation is
``archived``. Root conversations are never changed by this helper.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.conversation.conversation import ConversationStatus
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
)

logger = logging.getLogger(__name__)

_ACTIVE = ConversationStatus.ACTIVE.value
_ARCHIVED = ConversationStatus.ARCHIVED.value
_DELETED = ConversationStatus.DELETED.value
_LEGAL_STATUSES = {_ACTIVE, _ARCHIVED, _DELETED}


async def archive_stopped_child_conversations(
    session: AsyncSession,
    session_ids: Iterable[str],
    *,
    commit: bool = True,
) -> list[str]:
    """Archive active child conversations after their sessions are stopped.

    Idempotent and restart-safe:

    * missing rows are skipped
    * already-archived children are left unchanged
    * deleted children stay deleted
    * unexpected status values are left unchanged
    * conversations without a parent (root threads) are never archived

    Returns the child session IDs that are archived when this call returns,
    including ones that were already archived.
    """
    unique_ids = [session_id for session_id in dict.fromkeys(session_ids) if session_id]
    if not unique_ids:
        return []

    archived: list[str] = []
    dirty = False

    for session_id in unique_ids:
        child = await session.get(DBConversation, session_id)
        if child is None:
            continue
        if not child.parent_conversation_id:
            logger.debug(
                "Skipping conversation status sync for root session=%s",
                session_id,
            )
            continue
        if child.status == _DELETED:
            continue
        if child.status == _ARCHIVED:
            archived.append(session_id)
            continue
        if child.status != _ACTIVE:
            logger.warning(
                "Refusing to archive child session=%s with unexpected status=%s "
                "(legal conversation statuses: %s)",
                session_id,
                child.status,
                sorted(_LEGAL_STATUSES),
            )
            continue

        child.status = _ARCHIVED
        child.updated_at = datetime.now(UTC)
        archived.append(session_id)
        dirty = True

    if dirty and commit:
        await session.commit()

    return archived
