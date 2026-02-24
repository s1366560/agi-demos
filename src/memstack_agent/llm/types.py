"""LLM type definitions for memstack-agent.

This module provides core types for LLM interactions:
- Message: Chat message with role and content
- ChatResponse: Response from LLM
- StreamChunk: Streaming response chunk
- ToolCall: Function call from LLM
- Usage: Token usage tracking

All types are immutable (frozen dataclass).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    """Message role enumeration."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, kw_only=True)
class Message:
    """Immutable chat message.

    Attributes:
        role: Message role (system/user/assistant/tool)
        content: Message content
        name: Optional name (for tool messages)
        tool_call_id: Optional tool call ID (for tool result messages)
        tool_calls: Optional tool calls (for assistant messages)
    """

    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list["ToolCall"] | None = None

    @classmethod
    def system(cls, content: str) -> "Message":
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM.value, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        """Create a user message."""
        return cls(role=MessageRole.USER.value, content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list["ToolCall"] | None = None) -> "Message":
        """Create an assistant message."""
        return cls(role=MessageRole.ASSISTANT.value, content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, content: str, tool_call_id: str, name: str | None = None) -> "Message":
        """Create a tool result message."""
        return cls(role=MessageRole.TOOL.value, content=content, tool_call_id=tool_call_id, name=name)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API calls."""
        result: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return result


@dataclass(frozen=True, kw_only=True)
class ToolCall:
    """Immutable tool call from LLM.

    Attributes:
        id: Unique call identifier
        name: Tool name
        arguments: Tool arguments (parsed JSON)
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass(frozen=True, kw_only=True)
class Usage:
    """Token usage tracking.

    Attributes:
        prompt_tokens: Tokens in the prompt
        completion_tokens: Tokens in the completion
        total_tokens: Total tokens
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        """Add two usage objects."""
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass(frozen=True, kw_only=True)
class ChatResponse:
    """Immutable response from LLM.

    Attributes:
        content: Response content
        tool_calls: Optional tool calls
        finish_reason: Why the response finished
        usage: Token usage
        model: Model used for generation
    """

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    model: str | None = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if response contains tool calls."""
        return len(self.tool_calls) > 0


@dataclass(frozen=True, kw_only=True)
class StreamChunk:
    """Immutable streaming response chunk.

    Attributes:
        delta: Content delta (incremental text)
        tool_call_delta: Optional tool call delta
        finish_reason: Optional finish reason
    """

    delta: str = ""
    tool_call_delta: ToolCall | None = None
    finish_reason: str | None = None

    @property
    def is_final(self) -> bool:
        """Check if this is the final chunk."""
        return self.finish_reason is not None


__all__ = [
    "ChatResponse",
    "Message",
    "MessageRole",
    "StreamChunk",
    "ToolCall",
    "Usage",
]
