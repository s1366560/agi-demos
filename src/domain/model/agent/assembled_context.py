"""Assembled context value object for the pluggable context engine."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.model.agent.context_segment import ContextSegment
from src.domain.model.agent.conversation.message import Message
from src.domain.shared_kernel import ValueObject


@dataclass(frozen=True)
class AssembledContext(ValueObject):
    """The fully assembled context ready for LLM invocation.

    Produced by ContextEnginePort.assemble_context() and consumed
    by SessionProcessor before each LLM call.

    Attributes:
        system_prompt: the system prompt for the LLM.
        messages: ordered conversation messages for the context window.
        injected_context: additional context segments from memory/RAG/graph.
        total_tokens: estimated total token count of the assembled context.
        budget_tokens: the token budget that was targeted.
        is_compacted: whether compaction was applied to fit the budget.
    """

    system_prompt: str
    messages: tuple[Message, ...] = ()
    injected_context: tuple[ContextSegment, ...] = ()
    total_tokens: int = 0
    budget_tokens: int = 0
    is_compacted: bool = False

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def segment_count(self) -> int:
        return len(self.injected_context)

    @property
    def is_over_budget(self) -> bool:
        return self.budget_tokens > 0 and self.total_tokens > self.budget_tokens

    def with_compacted(
        self,
        *,
        messages: tuple[Message, ...],
        total_tokens: int,
    ) -> AssembledContext:
        """Return a new AssembledContext with compacted messages."""
        return AssembledContext(
            system_prompt=self.system_prompt,
            messages=messages,
            injected_context=self.injected_context,
            total_tokens=total_tokens,
            budget_tokens=self.budget_tokens,
            is_compacted=True,
        )
