"""Conversation-aware, coordinator-first message router (Track B P2-3 phase-2).

Wraps an inner ``MessageRouterPort`` (binding-based fallback) and consults the
conversation aggregate to apply mode-specific routing before falling through.

Agent First rule:
    The resolution rules here are all **structural** — enum comparison, set
    membership on the roster, and a single explicit-mention read from the
    domain ``Message.mentions`` field.  We NEVER regex or NLP-parse message
    content to guess who should answer.  Subjective "who should speak next?"
    decisions are expressed via either:
      * the user's explicit ``@mention`` (captured at the domain layer), or
      * the coordinator agent (an Agent).

Resolution order:
    1. ``message.mentions[0]`` if the mentioned agent is in the roster.
    2. MULTI_AGENT_ISOLATED   → ``focused_agent_id`` (if set).
    3. MULTI_AGENT_SHARED / MULTI_AGENT_ISOLATED / AUTONOMOUS →
       ``coordinator_agent_id`` (if set).
    4. AUTONOMOUS without coordinator → raise — invariant violation caught
       elsewhere, but we log and fall through rather than crash.
    5. SINGLE_AGENT, None (legacy), or no winner above → delegate to inner
       binding router.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.ports.agent.message_router_port import MessageRouterPort

if TYPE_CHECKING:
    from src.domain.model.agent.conversation.conversation import Conversation
    from src.domain.model.agent.conversation.message import Message
    from src.domain.model.agent.message_binding import MessageBinding
    from src.domain.model.agent.routing_context import RoutingContext
    from src.domain.ports.repositories.agent_repository import ConversationRepository

logger = logging.getLogger(__name__)


class ConversationAwareRouter:
    """Coordinator-first, mode-aware router that wraps a binding router.

    Implements :class:`MessageRouterPort` by deferring binding registration
    to the inner router and adding a pre-step that consults the conversation
    aggregate to apply multi-agent routing rules.
    """

    def __init__(
        self,
        inner: MessageRouterPort,
        conversation_repository: ConversationRepository,
    ) -> None:
        self._inner = inner
        self._conversations = conversation_repository

    async def resolve_agent(
        self,
        message: Message,
        context: RoutingContext,
    ) -> str | None:
        """See :meth:`MessageRouterPort.resolve_agent`.

        Multi-agent winners short-circuit the inner router; legacy single-agent
        conversations and conversations that do not resolve multi-agent fall
        through to binding-based routing.
        """
        conversation = await self._conversations.find_by_id(context.conversation_id)

        if conversation is None:
            # Legacy / pre-creation route — bindings still apply.
            return await self._inner.resolve_agent(message, context)

        roster = set(conversation.participant_agents or [])

        # 1. Explicit mention wins when it names a current participant.
        mentions = getattr(message, "mentions", None) or []
        for mentioned in mentions:
            if mentioned and mentioned in roster:
                logger.debug(
                    "ConversationAwareRouter: explicit mention -> %s (conv=%s)",
                    mentioned,
                    conversation.id,
                )
                return mentioned

        winner = self._resolve_by_mode(conversation, roster)
        if winner is not None:
            return winner

        # Single-agent / legacy / unresolved → inner binding router.
        return await self._inner.resolve_agent(message, context)

    @staticmethod
    def _resolve_by_mode(conversation: Conversation, roster: set[str]) -> str | None:
        """Pure structural mode resolution (Agent First — no content parsing)."""
        mode = conversation.conversation_mode
        coordinator = conversation.coordinator_agent_id
        focused = conversation.focused_agent_id

        if mode == ConversationMode.MULTI_AGENT_ISOLATED:
            if focused and focused in roster:
                return focused
            if coordinator and coordinator in roster:
                return coordinator
        elif mode in (ConversationMode.MULTI_AGENT_SHARED, ConversationMode.AUTONOMOUS):
            if coordinator and coordinator in roster:
                return coordinator
            if mode == ConversationMode.AUTONOMOUS:
                # Invariant says AUTONOMOUS requires a coordinator; do not
                # silently elect a participant — log and fall through so the
                # binding layer (or supervisor) can surface the problem.
                logger.warning(
                    "AUTONOMOUS conversation %s has no valid coordinator; "
                    "falling through",
                    conversation.id,
                )
        return None

    async def register_binding(self, binding: MessageBinding) -> None:
        await self._inner.register_binding(binding)

    async def remove_binding(self, binding_id: str) -> None:
        await self._inner.remove_binding(binding_id)
