"""Base tool class for ReAct agent.

.. deprecated::
    This module is deprecated. Use the ``@tool_define`` decorator from
    ``src.infrastructure.agent.tools.define`` to create new tools instead.
    Existing class-based tools will be removed in a future release.

This module provides the concrete AgentTool class that extends the domain-layer
AgentToolBase with infrastructure concerns (output truncation).

All agent tools must inherit from AgentTool and implement the required methods.

Enhanced with tool composition support (T109-T111) for intelligent tool chaining
and output truncation to prevent excessive token usage.
"""

import logging
from typing import Any

from src.domain.ports.agent.agent_tool_port import AgentToolBase
from src.infrastructure.agent.tools.truncation import (
    MAX_OUTPUT_BYTES,
    OutputTruncator,
)

logger = logging.getLogger(__name__)


class AgentTool(AgentToolBase):
    """Concrete base class for agent tools with output truncation.

    .. deprecated::
        Subclass ``AgentTool`` is deprecated. Use the ``@tool_define``
        decorator to create new tools. See ``skill_tool.py`` for an example.

    Extends AgentToolBase (domain layer) with infrastructure concerns:
    - Output truncation to prevent excessive token usage
    """

    def __init__(
        self,
        name: str,
        description: str,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ) -> None:
        """Initialize the tool.

        Args:
            name: Unique name for the tool
            description: Human-readable description of what the tool does
            max_output_bytes: Maximum output size in bytes (default: 50KB)
        """
        self._name = name
        self._description = description
        self._max_output_bytes = max_output_bytes
        self._truncator = OutputTruncator(max_bytes=max_output_bytes)

    @property
    def name(self) -> str:
        """Get the tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Get the tool description."""
        return self._description

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool with the given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            String result of the tool execution

        Raises:
            Exception: If tool execution fails
        """
        raise NotImplementedError("Subclasses must implement execute()")

    def truncate_output(self, output: str) -> str:
        """Truncate tool output to maximum byte size.

        Args:
            output: Raw output from tool execution

        Returns:
            Truncated output if exceeds limit, otherwise original output
        """
        result = self._truncator.truncate(output)
        if result.truncated:
            logger.warning(
                f"Tool {self._name} output truncated: {result.truncated_bytes} bytes removed"
            )
        return result.output
