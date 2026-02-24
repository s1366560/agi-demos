"""Context bridge for SubAgent execution.

Handles context transfer between the orchestrator (main agent) and SubAgent:
- Orchestrator -> SubAgent: task description + condensed relevant context
- SubAgent -> Orchestrator: structured SubAgentResult with summary

Avoids copying full conversation history to keep SubAgent context windows lean.
Optionally injects relevant memories from the knowledge graph.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default budget ratio: SubAgent gets 30% of the main agent's token budget
DEFAULT_BUDGET_RATIO = 0.3
DEFAULT_MAX_CONTEXT_MESSAGES = 5
DEFAULT_MAX_CONTEXT_CHARS = 4000


@dataclass(frozen=True)
class SubAgentContext:
    """Condensed context package sent to a SubAgent.

    Attributes:
        task_description: Clear description of what the SubAgent should do.
        system_prompt: SubAgent's specialized system prompt.
        context_messages: Condensed recent conversation messages.
        token_budget: Maximum tokens the SubAgent may consume.
        metadata: Additional metadata (project_id, tenant_id, etc.).
        memory_context: Formatted memory snippet from knowledge graph.
    """

    task_description: str
    system_prompt: str
    context_messages: list[dict[str, str]] = field(default_factory=list)
    token_budget: int = 60000
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_context: str = ""


class ContextBridge:
    """Transfers context between orchestrator and SubAgent.

    Responsibilities:
    - Extract relevant context from the main conversation
    - Apply token budget constraints
    - Build the SubAgent's initial message list
    """

    def __init__(
        self,
        budget_ratio: float = DEFAULT_BUDGET_RATIO,
        max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ) -> None:
        self._budget_ratio = budget_ratio
        self._max_context_messages = max_context_messages
        self._max_context_chars = max_context_chars

    def build_subagent_context(
        self,
        user_message: str,
        subagent_system_prompt: str,
        conversation_context: list[dict[str, str]] | None = None,
        main_token_budget: int = 200000,
        project_id: str = "",
        tenant_id: str = "",
        memory_context: str = "",
    ) -> SubAgentContext:
        """Build a condensed context package for a SubAgent.

        Args:
            user_message: The user's original message (becomes the task).
            subagent_system_prompt: The SubAgent's system prompt.
            conversation_context: Recent conversation messages from the main agent.
            main_token_budget: The main agent's total token budget.
            project_id: Project ID for scoping.
            tenant_id: Tenant ID for scoping.
            memory_context: Pre-formatted memory snippet from MemoryAccessor.

        Returns:
            SubAgentContext ready for SubAgentProcess.
        """
        condensed = self._condense_context(conversation_context)
        token_budget = int(main_token_budget * self._budget_ratio)

        return SubAgentContext(
            task_description=user_message,
            system_prompt=subagent_system_prompt,
            context_messages=condensed,
            token_budget=token_budget,
            metadata={
                "project_id": project_id,
                "tenant_id": tenant_id,
            },
            memory_context=memory_context,
        )

    def build_messages(self, context: SubAgentContext) -> list[dict[str, Any]]:
        """Build the initial message list for a SubAgent's processor.

        Constructs: [system, ...condensed_context, (memory), user_task]

        If memory_context is present, it is injected as a system message
        before the task message to provide relevant knowledge.

        Args:
            context: The SubAgentContext to convert.

        Returns:
            Message list ready for SessionProcessor.process().
        """
        messages: list[dict[str, Any]] = []

        # System prompt
        messages.append(
            {
                "role": "system",
                "content": context.system_prompt,
            }
        )

        # Condensed conversation context (if any)
        for msg in context.context_messages:
            messages.append(
                {
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                }
            )

        # Memory context from knowledge graph (if available)
        if context.memory_context:
            messages.append(
                {
                    "role": "system",
                    "content": context.memory_context,
                }
            )

        # Task message
        messages.append(
            {
                "role": "user",
                "content": context.task_description,
            }
        )

        return messages

    def _condense_context(
        self,
        conversation_context: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        """Condense conversation context to fit SubAgent budget.

        Takes the most recent messages up to limits, truncating
        individual messages if needed.

        Args:
            conversation_context: Full conversation history.

        Returns:
            Condensed list of recent messages.
        """
        if not conversation_context:
            return []

        # Take the most recent N messages
        recent = conversation_context[-self._max_context_messages :]

        condensed: list[dict[str, str]] = []
        total_chars = 0

        for msg in recent:
            content = msg.get("content", "")
            role = msg.get("role", "user")

            remaining_budget = self._max_context_chars - total_chars
            if remaining_budget <= 0:
                break

            if len(content) > remaining_budget:
                content = content[:remaining_budget] + "... [truncated]"

            condensed.append({"role": role, "content": content})
            total_chars += len(content)

        return condensed
