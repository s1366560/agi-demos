"""ExecuteStep use case for multi-level thinking.

This use case handles execution of individual steps,
including task-level thinking for each step.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.domain.llm_providers.llm_types import LLMClient
from src.domain.model.agent import ThoughtLevel

if TYPE_CHECKING:
    from src.domain.ports.agent.agent_tool_port import AgentToolBase

logger = logging.getLogger(__name__)


class ExecuteStepUseCase:
    """Use case for executing individual steps."""

    def __init__(
        self,
        llm: LLMClient,
        tools: dict[str, AgentToolBase],
    ):
        """
        Initialize the use case.

        Args:
            llm: LLM for task-level thinking
            tools: Dictionary of available tools
        """
        self._llm = llm
        self._tools = tools

    async def execute(
        self,
        work_plan: Any,
        conversation_context: list[dict],
    ) -> dict[str, Any]:
        """Execute a step (placeholder - plan system being refactored)."""
        raise NotImplementedError("Plan execution system is being refactored")
