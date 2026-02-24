"""Context Loader - Smart context loading with summary caching.

Implements the dual-layer loading strategy:
1. If a cached summary exists and covers older messages, load
   [summary] + [recent messages after cutoff] instead of re-compressing.
2. If no summary exists, fall back to loading the last N messages.
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.domain.model.agent.conversation.context_summary import ContextSummary
from src.domain.ports.agent.context_manager_port import ContextSummaryPort
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class ContextLoadResult:
    """Result of smart context loading."""

    # Conversation messages for LLM context (role + content dicts)
    messages: list[dict[str, Any]]
    # Cached summary (if loaded from cache)
    summary: ContextSummary | None = None
    # Whether context was loaded from cached summary
    from_cache: bool = False
    # Total messages in the conversation (for status reporting)
    total_message_count: int = 0
    # Messages loaded as recent context (after summary cutoff)
    recent_message_count: int = 0
    # Messages covered by summary
    summarized_message_count: int = 0


class ContextLoader:
    """Loads conversation context with summary caching support.

    When a cached summary exists and covers older messages, this loader
    returns [summary] + [recent messages] instead of loading all 50 messages
    and re-compressing every turn.
    """

    def __init__(
        self,
        event_repo: AgentExecutionEventRepository,
        summary_adapter: ContextSummaryPort,
    ) -> None:
        self._event_repo = event_repo
        self._summary_adapter = summary_adapter

    async def load_context(
        self,
        conversation_id: str,
        exclude_event_id: str | None = None,
        fallback_limit: int = 50,
    ) -> ContextLoadResult:
        """Load conversation context with smart summary caching.

        Args:
            conversation_id: The conversation ID
            exclude_event_id: Event ID to exclude (e.g., current user message)
            fallback_limit: Max messages when no summary exists

        Returns:
            ContextLoadResult with messages and summary metadata
        """
        total_count = await self._event_repo.count_messages(conversation_id)

        # Try to load cached summary
        summary = await self._summary_adapter.get_summary(conversation_id)

        if summary and summary.messages_covered_up_to > 0:
            return await self._load_with_summary(
                conversation_id=conversation_id,
                summary=summary,
                exclude_event_id=exclude_event_id,
                total_count=total_count,
            )

        # No cached summary - fall back to current behavior
        return await self._load_without_summary(
            conversation_id=conversation_id,
            exclude_event_id=exclude_event_id,
            limit=fallback_limit,
            total_count=total_count,
        )

    async def _load_with_summary(
        self,
        conversation_id: str,
        summary: ContextSummary,
        exclude_event_id: str | None,
        total_count: int,
    ) -> ContextLoadResult:
        """Load recent messages after summary cutoff."""
        recent_events = await self._event_repo.get_message_events_after(
            conversation_id=conversation_id,
            after_time_us=summary.messages_covered_up_to,
        )

        messages = [
            {
                "role": event.event_data.get("role", "user"),
                "content": event.event_data.get("content", ""),
            }
            for event in recent_events
            if exclude_event_id is None or event.id != exclude_event_id
        ]

        logger.info(
            f"[ContextLoader] Loaded from cache: summary covers "
            f"{summary.messages_covered_count} messages, "
            f"{len(messages)} recent messages loaded"
        )

        return ContextLoadResult(
            messages=messages,
            summary=summary,
            from_cache=True,
            total_message_count=total_count,
            recent_message_count=len(messages),
            summarized_message_count=summary.messages_covered_count,
        )

    async def _load_without_summary(
        self,
        conversation_id: str,
        exclude_event_id: str | None,
        limit: int,
        total_count: int,
    ) -> ContextLoadResult:
        """Fall back to loading last N messages (current behavior)."""
        message_events = await self._event_repo.get_message_events(
            conversation_id=conversation_id,
            limit=limit,
        )

        messages = [
            {
                "role": event.event_data.get("role", "user"),
                "content": event.event_data.get("content", ""),
            }
            for event in message_events
            if exclude_event_id is None or event.id != exclude_event_id
        ]

        if total_count > limit:
            logger.warning(
                f"[ContextLoader] Conversation {conversation_id} has {total_count} "
                f"messages but only loading last {limit}. "
                f"Context summary will be generated after compression."
            )

        return ContextLoadResult(
            messages=messages,
            summary=None,
            from_cache=False,
            total_message_count=total_count,
            recent_message_count=len(messages),
            summarized_message_count=0,
        )

    async def save_summary(
        self,
        conversation_id: str,
        summary: ContextSummary,
    ) -> None:
        """Save a context summary after compression."""
        await self._summary_adapter.save_summary(conversation_id, summary)

    async def invalidate_summary(self, conversation_id: str) -> None:
        """Invalidate cached summary (forces re-generation)."""
        await self._summary_adapter.invalidate_summary(conversation_id)
