"""ReAct Agent implementation.

This module provides the core ReAct (Reasoning + Acting) agent
that implements the four-layer architecture:
- Think: Generate thoughts about current state
- Act: Select and execute tools
- Observe: Process tool results
- Repeat: Continue until task complete

The ReActAgent uses a SessionProcessor to orchestrate the
execution loop and emit events.
"""

from collections.abc import AsyncIterator

from memstack_agent.core.events import (
    AgentEvent,
    CompleteEvent,
    ErrorEvent,
    StartEvent,
)
from memstack_agent.core.types import AgentContext, ProcessorConfig, ProcessorState
from memstack_agent.tools.protocol import ToolDefinition


class ReActAgent:
    """ReAct Agent implementing the Think-Act-Observe loop.

    The agent:
    1. Receives a user message
    2. Thinks about what to do (LLM reasoning)
    3. Acts by calling tools
    4. Observes tool results
    5. Repeats until task complete

    Usage:
        agent = ReActAgent(
            config=ProcessorConfig(model="gpt-4"),
            tools=[tool1, tool2],
        )

        async for event in agent.run(context, message):
            # Handle events (streaming)
            print(event)
    """

    def __init__(
        self,
        config: ProcessorConfig,
        tools: list[ToolDefinition],
    ):
        """Initialize the ReAct agent.

        Args:
            config: Processor configuration
            tools: Available tools for the agent
        """
        self.config = config
        self.tools = {t.name: t for t in tools}

    async def run(
        self,
        context: AgentContext,
        message: str,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent on a user message.

        Yields events as the agent processes:
        - StartEvent: Processing begins
        - ThoughtEvent: Agent thinking
        - ActEvent: Tool calls
        - ObserveEvent: Tool results
        - CompleteEvent: Processing finishes
        - ErrorEvent: If an error occurs

        Args:
            context: Agent context with session info
            message: User message to process

        Yields:
            AgentEvent instances during execution
        """
        # Emit start event
        yield StartEvent(
            conversation_id=context.conversation_id,
            user_id=context.user_id,
            model=context.model,
        )

        try:
            # TODO: Implement full ReAct loop in phase 2
            # For now, just emit complete event
            yield CompleteEvent(
                conversation_id=context.conversation_id,
                result="Agent execution not yet implemented",
            )
        except Exception as e:
            yield ErrorEvent(
                conversation_id=context.conversation_id,
                message=str(e),
            )

    @property
    def state(self) -> ProcessorState:
        """Get current agent state."""
        # TODO: Track actual state in phase 2
        return ProcessorState.IDLE


__all__ = ["ReActAgent"]
