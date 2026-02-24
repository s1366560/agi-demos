"""Session Processor for memstack-agent.

The SessionProcessor orchestrates the complete agent execution cycle:
1. Receives user message
2. Calls LLM for reasoning and action
3. Executes tool calls
4. Observes results
5. Continues until task complete or blocked

This is the core execution engine that integrates all components.
"""

from collections.abc import AsyncIterator
from typing import Any

from memstack_agent.core.events import AgentEvent
from memstack_agent.core.types import (
    AgentContext,
    ProcessorConfig,
    ProcessorState,
)
from memstack_agent.tools.protocol import ToolDefinition


class SessionProcessor:
    """Core ReAct agent processing loop.

    Manages the complete agent execution cycle with:
    - Streaming LLM responses
    - Tool execution with permission control
    - Doom loop detection
    - Intelligent retry with backoff
    - Real-time cost tracking
    - SSE event emission

    Usage:
        processor = SessionProcessor(config, tools)
        async for event in processor.process(context, message):
            yield event
    """

    def __init__(
        self,
        config: ProcessorConfig,
        tools: list[ToolDefinition],
    ):
        """Initialize session processor.

        Args:
            config: Processor configuration
            tools: List of available tools
        """
        self.config = config
        self.tools = {t.name: t for t in tools}

        # Session state
        self._state = ProcessorState.IDLE
        self._step_count = 0

    @property
    def state(self) -> ProcessorState:
        """Get current processor state."""
        return self._state

    async def process(
        self,
        context: AgentContext,
        message: str,
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message through the ReAct loop.

        Args:
            context: Agent context with session info
            message: User message to process

        Yields:
            AgentEvent instances during execution
        """
        # TODO: Implement full processing loop in phase 2
        raise NotImplementedError("SessionProcessor.process() not yet implemented")

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> Any:
        """Execute a single tool call.

        Args:
            tool_name: Name of tool to execute
            tool_input: Parameters for the tool

        Returns:
            Tool execution result

        Raises:
            KeyError: If tool not found
            Exception: If tool execution fails
        """
        if tool_name not in self.tools:
            raise KeyError(f"Tool not found: {tool_name}")

        tool_def = self.tools[tool_name]
        return await tool_def.execute(**tool_input)


__all__ = ["SessionProcessor"]
