"""LLM Protocol definitions for memstack-agent.

Defines Protocol-based interfaces for LLM clients, following
the same pattern as the Tool Protocol.
"""

from typing import Any, AsyncGenerator, List, Optional, Protocol, runtime_checkable

from memstack_agent.llm.types import ChatResponse, Message, StreamChunk
from memstack_agent.tools.protocol import ToolDefinition


@runtime_checkable
class LLMClient(Protocol):
    """Protocol for LLM client implementations.

    Any object implementing this interface can be used as an LLM client.
    Supports both streaming and non-streaming responses, with optional
    tool calling support.

    Example:
        class MyLLMClient:
            async def generate(
                self,
                messages: List[Message],
                tools: Optional[List[ToolDefinition]] = None,
                **kwargs: Any,
            ) -> ChatResponse:
                # Implementation
                ...

            async def stream(
                self,
                messages: List[Message],
                tools: Optional[List[ToolDefinition]] = None,
                **kwargs: Any,
            ) -> AsyncGenerator[StreamChunk, None]:
                # Implementation
                ...
    """

    async def generate(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate a non-streaming response.

        Args:
            messages: List of conversation messages
            tools: Optional tool definitions for function calling
            **kwargs: Additional provider-specific parameters

        Returns:
            ChatResponse with content and optional tool calls
        """
        ...

    async def stream(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Generate a streaming response.

        Args:
            messages: List of conversation messages
            tools: Optional tool definitions for function calling
            **kwargs: Additional provider-specific parameters

        Yields:
            StreamChunk objects with incremental content
        """
        ...


@runtime_checkable
class LLMClientSync(Protocol):
    """Protocol for synchronous LLM clients (rarely needed).

    Provided for compatibility with sync-only environments.
    """

    def generate_sync(
        self,
        messages: List[Message],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate a non-streaming response synchronously.

        Args:
            messages: List of conversation messages
            tools: Optional tool definitions for function calling
            **kwargs: Additional provider-specific parameters

        Returns:
            ChatResponse with content and optional tool calls
        """
        ...


__all__ = [
    "LLMClient",
    "LLMClientSync",
]
