"""Session Fork/Merge Port - Domain interface for session lifecycle operations.

Defines the SessionForkMergePort protocol for forking child sessions from
a parent conversation and merging results back upon completion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.domain.events.agent_events import SessionForkedEvent, SessionMergedEvent
    from src.domain.model.agent.conversation.conversation import Conversation
    from src.domain.model.agent.merge_strategy import MergeStrategy
    from src.domain.model.agent.subagent_result import SubAgentResult


@runtime_checkable
class SessionForkMergePort(Protocol):
    """Protocol for session fork and merge operations.

    Manages the lifecycle of child sessions spawned from a parent
    conversation:

    1. fork_session  - creates a child conversation with context snapshot
    2. merge_session - merges child results back to parent per strategy
    """

    async def fork_session(
        self,
        parent: Conversation,
        *,
        user_id: str,
        title: str,
        merge_strategy: MergeStrategy,
        context_snapshot: str | None = None,
    ) -> tuple[Conversation, SessionForkedEvent]:
        """Fork a child conversation from the parent.

        Creates a new child Conversation linked to the parent via
        fork_source_id and parent_conversation_id.  Optionally captures
        a serialised context snapshot at fork time.

        Args:
            parent: The parent conversation to fork from.
            user_id: User ID for the child conversation.
            title: Title for the child conversation.
            merge_strategy: Strategy for merging results back.
            context_snapshot: Optional serialised context at fork time.

        Returns:
            A tuple of (child_conversation, SessionForkedEvent).
        """
        ...

    async def merge_session(
        self,
        parent: Conversation,
        child: Conversation,
        result: SubAgentResult,
        *,
        child_messages: list[str] | None = None,
    ) -> tuple[str, SessionMergedEvent]:
        """Merge a completed child session's results back to the parent.

        Applies the child's merge_strategy to produce content suitable
        for injection into the parent conversation's context:

        - RESULT_ONLY:   uses result.to_context_message()
        - FULL_HISTORY:  joins child_messages into a collapsed segment
        - SUMMARY:       uses result.summary

        Args:
            parent: The parent conversation receiving the merge.
            child: The completed child conversation.
            result: Structured result from the child's execution.
            child_messages: Optional list of child message content strings.
                Required when child's merge_strategy is FULL_HISTORY.

        Returns:
            A tuple of (merged_content_string, SessionMergedEvent).
        """
        ...
