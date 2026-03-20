"""Session fork/merge service -- infrastructure implementation.

Implements SessionForkMergePort by delegating to Conversation.fork() for
session creation and switching on MergeStrategy for result merging.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.domain.events.agent_events import SessionForkedEvent, SessionMergedEvent
from src.domain.model.agent.merge_strategy import MergeStrategy

if TYPE_CHECKING:
    from src.domain.model.agent.conversation.conversation import Conversation
    from src.domain.model.agent.subagent_result import SubAgentResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full-history merge constants
# ---------------------------------------------------------------------------

_FULL_HISTORY_HEADER = "[Full History from child session '{title}']"
_FULL_HISTORY_SEPARATOR = "\n---\n"


class SessionForkMergeService:
    """Default SessionForkMergePort implementation.

    Pure domain-logic service with no infrastructure dependencies.
    Fork delegates to ``Conversation.fork()``; merge switches on the
    child conversation's ``merge_strategy`` field.
    """

    # ------------------------------------------------------------------
    # fork_session
    # ------------------------------------------------------------------

    async def fork_session(
        self,
        parent: Conversation,
        *,
        user_id: str,
        title: str,
        merge_strategy: MergeStrategy,
        context_snapshot: str | None = None,
    ) -> tuple[Conversation, SessionForkedEvent]:
        """Create a child conversation forked from *parent*."""
        child = parent.fork(
            user_id=user_id,
            title=title,
            merge_strategy=merge_strategy,
            context_snapshot=context_snapshot,
        )
        event = SessionForkedEvent(
            parent_conversation_id=parent.id,
            child_conversation_id=child.id,
        )
        logger.debug(
            "Forked session %s -> %s (strategy=%s)",
            parent.id,
            child.id,
            merge_strategy.value,
        )
        return child, event

    # ------------------------------------------------------------------
    # merge_session
    # ------------------------------------------------------------------

    async def merge_session(
        self,
        parent: Conversation,
        child: Conversation,
        result: SubAgentResult,
        *,
        child_messages: list[str] | None = None,
    ) -> tuple[str, SessionMergedEvent]:
        """Merge *child* results back into *parent* per strategy."""
        strategy = child.merge_strategy or MergeStrategy.RESULT_ONLY

        if strategy is MergeStrategy.RESULT_ONLY:
            merged = result.to_context_message()
        elif strategy is MergeStrategy.FULL_HISTORY:
            merged = self._merge_full_history(child, child_messages)
        elif strategy is MergeStrategy.SUMMARY:
            merged = result.summary
        else:  # pragma: no cover -- exhaustive enum guard
            merged = result.to_context_message()

        event = SessionMergedEvent(
            parent_conversation_id=parent.id,
            child_conversation_id=child.id,
            merge_strategy=strategy.value,
        )
        logger.debug(
            "Merged session %s -> %s (strategy=%s, content_len=%d)",
            child.id,
            parent.id,
            strategy.value,
            len(merged),
        )
        return merged, event

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_full_history(
        child: Conversation,
        child_messages: list[str] | None,
    ) -> str:
        """Join child messages into a collapsed context segment."""
        header = _FULL_HISTORY_HEADER.format(title=child.title)
        if not child_messages:
            return header + "\n(No messages recorded)"
        body = _FULL_HISTORY_SEPARATOR.join(child_messages)
        return header + "\n" + body
