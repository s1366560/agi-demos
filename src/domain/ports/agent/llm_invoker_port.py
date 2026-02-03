"""
LLM Invoker Port - Domain interface for LLM invocation.

Defines the contract for invoking LLM providers with streaming support.
Infrastructure adapters (LiteLLM, OpenAI, etc.) implement this interface.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


class StreamEventType(str, Enum):
    """Types of events in LLM stream."""

    CONTENT = "content"  # Text content chunk
    TOOL_CALL = "tool_call"  # Tool/function call
    TOOL_CALL_DELTA = "tool_call_delta"  # Partial tool call
    FINISH = "finish"  # Stream finished
    ERROR = "error"  # Error occurred


@dataclass
class StreamChunk:
    """A chunk from LLM streaming response.

    Attributes:
        event_type: Type of stream event
        content: Text content (for CONTENT events)
        tool_call: Tool call data (for TOOL_CALL events)
        finish_reason: Reason for finishing (for FINISH events)
        error: Error message (for ERROR events)
        raw: Raw response data from provider
    """

    event_type: StreamEventType
    content: Optional[str] = None
    tool_call: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class LLMInvocationRequest:
    """Request for LLM invocation.

    Attributes:
        messages: Conversation messages
        tools: Available tools in OpenAI format
        model: Model identifier (optional, uses default)
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        stop_sequences: Sequences that stop generation
        metadata: Additional provider-specific metadata
    """

    messages: List[Dict[str, Any]]
    tools: Optional[List[Dict[str, Any]]] = None
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMInvocationResult:
    """Result from non-streaming LLM invocation.

    Attributes:
        content: Generated text content
        tool_calls: Tool calls made by model
        finish_reason: Reason for completion
        usage: Token usage statistics
        model: Model that was used
        raw_response: Full raw response
    """

    content: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Dict[str, int] = field(default_factory=dict)
    model: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0

    @property
    def total_tokens(self) -> int:
        """Get total token count."""
        return self.usage.get("total_tokens", 0)


@runtime_checkable
class LLMInvokerPort(Protocol):
    """
    Protocol for LLM invocation.

    Implementations handle the actual communication with LLM providers.
    Supports both streaming and non-streaming invocation.

    Example:
        class LiteLLMInvoker(LLMInvokerPort):
            async def invoke_stream(
                self, request: LLMInvocationRequest
            ) -> AsyncIterator[StreamChunk]:
                async for chunk in litellm.acompletion_stream(...):
                    yield StreamChunk(...)

            async def invoke(
                self, request: LLMInvocationRequest
            ) -> LLMInvocationResult:
                response = await litellm.acompletion(...)
                return LLMInvocationResult(...)
    """

    async def invoke_stream(
        self, request: LLMInvocationRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        Invoke LLM with streaming response.

        Args:
            request: Invocation request with messages and config

        Yields:
            StreamChunk for each piece of response

        Raises:
            LLMInvocationError: If invocation fails
        """
        ...

    async def invoke(self, request: LLMInvocationRequest) -> LLMInvocationResult:
        """
        Invoke LLM without streaming.

        Args:
            request: Invocation request with messages and config

        Returns:
            Complete invocation result

        Raises:
            LLMInvocationError: If invocation fails
        """
        ...

    def get_model_info(self, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Get information about a model.

        Args:
            model: Model identifier, or None for default

        Returns:
            Dict with model info (context_window, pricing, etc.)
        """
        ...
