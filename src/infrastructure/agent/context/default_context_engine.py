"""Default implementation of ContextEnginePort.

Wraps the existing ContextFacade, ContextBridge, and compaction utilities
behind the pluggable ContextEnginePort protocol, enabling future replacement
without changing the SessionProcessor or ReActAgent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.assembled_context import AssembledContext
from src.domain.model.agent.conversation.message import Message, MessageRole, MessageType
from src.domain.ports.agent.context_manager_port import ContextBuildRequest

if TYPE_CHECKING:
    from src.domain.model.agent.conversation.conversation import Conversation
    from src.domain.model.agent.subagent_result import SubAgentResult
    from src.infrastructure.agent.context.context_facade import ContextFacade
    from src.infrastructure.agent.subagent.context_bridge import ContextBridge

logger = logging.getLogger(__name__)


class DefaultContextEngine:
    """Default ContextEnginePort implementation wrapping existing infrastructure.

    Delegates context assembly to ContextFacade and provides lifecycle
    hooks that are no-ops in this default implementation but can be
    overridden in specialised subclasses.

    Args:
        context_facade: The existing context facade for building context windows.
        context_bridge: Optional bridge for sub-agent context sharing.
    """

    def __init__(
        self,
        context_facade: ContextFacade,
        context_bridge: ContextBridge | None = None,
    ) -> None:
        self._context_facade = context_facade
        self._context_bridge = context_bridge

    # ------------------------------------------------------------------
    # ContextEnginePort: on_message_ingest
    # ------------------------------------------------------------------

    async def on_message_ingest(
        self,
        message: Message,
        conversation: Conversation,
    ) -> None:
        """No-op hook -- extensible in subclasses."""

    # ------------------------------------------------------------------
    # ContextEnginePort: assemble_context
    # ------------------------------------------------------------------

    async def assemble_context(
        self,
        conversation: Conversation,
        token_budget: int,
    ) -> AssembledContext:
        """Build the context window by delegating to ContextFacade.

        Converts the facade's ``ContextBuildResult`` (OpenAI-format dicts)
        into an ``AssembledContext`` domain value object.
        """
        request = ContextBuildRequest(
            system_prompt="",
            conversation_context=self._conversation_to_dicts(conversation),
            user_message="",
            max_context_tokens=token_budget,
        )
        build_result = await self._context_facade.build_context(request)

        system_prompt = ""
        non_system_dicts: list[dict[str, Any]] = []
        for msg_dict in build_result.messages:
            if msg_dict.get("role") == "system" and not system_prompt:
                system_prompt = str(msg_dict.get("content", ""))
            else:
                non_system_dicts.append(msg_dict)

        domain_messages = tuple(
            self._dict_to_domain_message(d, conversation.id) for d in non_system_dicts
        )

        total_tokens = build_result.estimated_tokens
        is_compacted = build_result.was_compressed

        return AssembledContext(
            system_prompt=system_prompt,
            messages=domain_messages,
            total_tokens=total_tokens,
            budget_tokens=token_budget,
            is_compacted=is_compacted,
        )

    # ------------------------------------------------------------------
    # ContextEnginePort: compact_context
    # ------------------------------------------------------------------

    async def compact_context(
        self,
        context: AssembledContext,
        target_tokens: int,
    ) -> AssembledContext:
        """Truncate messages from the front to fit within *target_tokens*.

        Preserves the system prompt and injected context segments.
        Drops the oldest non-system messages first until the estimated
        token total fits the target budget.
        """
        if context.total_tokens <= target_tokens:
            return AssembledContext(
                system_prompt=context.system_prompt,
                messages=context.messages,
                injected_context=context.injected_context,
                total_tokens=context.total_tokens,
                budget_tokens=target_tokens,
                is_compacted=True,
            )

        kept_messages: list[Message] = []
        running_tokens = self._context_facade.estimate_tokens(context.system_prompt)

        for segment in context.injected_context:
            running_tokens += segment.token_count

        for msg in reversed(context.messages):
            msg_tokens = self._context_facade.estimate_tokens(msg.content or "")
            if running_tokens + msg_tokens <= target_tokens:
                kept_messages.insert(0, msg)
                running_tokens += msg_tokens

        return AssembledContext(
            system_prompt=context.system_prompt,
            messages=tuple(kept_messages),
            injected_context=context.injected_context,
            total_tokens=running_tokens,
            budget_tokens=target_tokens,
            is_compacted=True,
        )

    # ------------------------------------------------------------------
    # ContextEnginePort: after_turn
    # ------------------------------------------------------------------

    async def after_turn(
        self,
        conversation: Conversation,
        turn_result: Any,
    ) -> None:
        """No-op hook -- extensible in subclasses."""

    # ------------------------------------------------------------------
    # ContextEnginePort: on_subagent_ended
    # ------------------------------------------------------------------

    async def on_subagent_ended(
        self,
        conversation: Conversation,
        result: SubAgentResult,
    ) -> None:
        """No-op hook -- extensible in subclasses."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _conversation_to_dicts(conversation: Conversation) -> list[dict[str, Any]]:
        """Convert a Conversation's messages to OpenAI-style dicts.

        Returns an empty list because the ContextFacade receives raw
        conversation context from the caller (e.g. ReActAgent) rather
        than from the Conversation entity directly.  The engine acts
        as an adapter that the SessionProcessor wires up.
        """
        return []

    @staticmethod
    def _dict_to_domain_message(
        msg_dict: dict[str, Any],
        conversation_id: str,
    ) -> Message:
        """Convert an OpenAI-format message dict to a domain Message."""
        role_str = str(msg_dict.get("role", "user"))
        role_map = {
            "user": MessageRole.USER,
            "assistant": MessageRole.ASSISTANT,
            "system": MessageRole.SYSTEM,
        }
        role = role_map.get(role_str, MessageRole.USER)

        content = msg_dict.get("content", "")
        if isinstance(content, list):
            text_parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        content = str(content)

        return Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            message_type=MessageType.TEXT,
        )
