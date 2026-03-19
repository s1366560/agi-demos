"""Context Engine Port - Domain interface for pluggable context assembly.

Defines the ContextEnginePort protocol that infrastructure adapters implement
to provide context lifecycle management: ingestion, assembly, compaction,
and post-turn hooks.

This port supersedes the lower-level ContextManagerPort by adding lifecycle
hooks that integrate with the SessionProcessor's turn cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.domain.model.agent.assembled_context import AssembledContext
    from src.domain.model.agent.conversation.conversation import Conversation
    from src.domain.model.agent.conversation.message import Message
    from src.domain.model.agent.subagent_result import SubAgentResult


@runtime_checkable
class ContextEnginePort(Protocol):
    """Protocol for pluggable context engine implementations.

    The context engine manages the full lifecycle of context assembly
    within a single conversation turn:

    1. on_message_ingest  - called when a new user message arrives
    2. assemble_context   - builds the context window for LLM invocation
    3. compact_context    - compresses context when it exceeds token budget
    4. after_turn         - post-turn bookkeeping (e.g. summary updates)
    5. on_subagent_ended  - merges sub-agent results into parent context
    """

    async def on_message_ingest(
        self,
        message: Message,
        conversation: Conversation,
    ) -> None:
        """Hook called when a new message is ingested into the conversation.

        Implementations may update internal state, trigger memory recall,
        or perform any pre-assembly bookkeeping.

        Args:
            message: The newly ingested message.
            conversation: The owning conversation.
        """
        ...

    async def assemble_context(
        self,
        conversation: Conversation,
        token_budget: int,
    ) -> AssembledContext:
        """Build the context window for the next LLM invocation.

        Combines conversation history, system prompt segments, memory
        recalls, and any injected sub-agent results into a single
        AssembledContext that fits within the token budget.

        Args:
            conversation: The active conversation.
            token_budget: Maximum token count for the assembled context.

        Returns:
            An AssembledContext ready for LLM invocation.
        """
        ...

    async def compact_context(
        self,
        context: AssembledContext,
        target_tokens: int,
    ) -> AssembledContext:
        """Compress an assembled context to fit a smaller token budget.

        Called when the assembled context exceeds the model's limit.
        Implementations may summarise older messages, drop low-priority
        segments, or apply other compaction strategies.

        Args:
            context: The current (over-budget) assembled context.
            target_tokens: The desired maximum token count after compaction.

        Returns:
            A new AssembledContext within the target token budget.
        """
        ...

    async def after_turn(
        self,
        conversation: Conversation,
        turn_result: Any,
    ) -> None:
        """Post-turn hook for bookkeeping after a complete ReAct turn.

        Called after the processor finishes a turn (think -> act -> observe).
        Implementations may persist running summaries, update token metrics,
        or flush caches.

        Args:
            conversation: The active conversation.
            turn_result: The result of the completed turn.  Typed as Any
                because the concrete TurnResult type lives in infrastructure;
                it will be narrowed once that type is promoted to domain.
        """
        ...

    async def on_subagent_ended(
        self,
        conversation: Conversation,
        result: SubAgentResult,
    ) -> None:
        """Merge a completed sub-agent's result into the parent context.

        Called when a child sub-agent finishes execution. The implementation
        should format the result and inject it into the parent conversation's
        context window for subsequent turns.

        Args:
            conversation: The parent conversation.
            result: Structured result from the completed sub-agent.
        """
        ...
