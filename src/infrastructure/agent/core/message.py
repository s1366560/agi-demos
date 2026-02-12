"""Message types for agent conversation."""

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class MessageRole(str, Enum):
    """Message role types."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ToolState(str, Enum):
    """Tool execution state."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ToolPart:
    """Tool call part of a message."""

    call_id: str
    tool: str
    status: ToolState
    input: Dict[str, Any] = field(default_factory=dict)
    output: Optional[str] = None
    error: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    tool_execution_id: Optional[str] = None  # Unique ID for act/observe matching

    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate duration in milliseconds."""
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time) * 1000)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "tool",
            "call_id": self.call_id,
            "tool": self.tool,
            "status": self.status.value,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "title": self.title,
            "metadata": self.metadata,
            "duration_ms": self.duration_ms,
        }


@dataclass
class TextPart:
    """Text content part of a message."""

    text: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    synthetic: bool = False  # Generated vs from LLM

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "text",
            "text": self.text,
            "synthetic": self.synthetic,
        }


@dataclass
class ReasoningPart:
    """Reasoning/thinking part of a message."""

    text: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": "reasoning",
            "text": self.text,
            "metadata": self.metadata,
        }


# Union type for all message parts
MessagePart = Union[ToolPart, TextPart, ReasoningPart]


@dataclass
class Message:
    """
    Message in a conversation.

    A message can contain multiple parts:
    - Text content
    - Tool calls and results
    - Reasoning/thinking
    - Step markers
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    role: MessageRole = MessageRole.USER
    content: str = ""
    parts: List[MessagePart] = field(default_factory=list)

    # For assistant messages
    agent: Optional[str] = None
    parent_id: Optional[str] = None
    finish_reason: Optional[str] = None

    # Token usage
    tokens: Dict[str, int] = field(default_factory=dict)
    cost: float = 0.0

    # Error info
    error: Optional[Dict[str, Any]] = None

    # Timestamps
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def add_text(self, text: str, synthetic: bool = False) -> TextPart:
        """Add text part to message."""
        part = TextPart(text=text, synthetic=synthetic, start_time=time.time())
        self.parts.append(part)
        return part

    def add_tool_call(
        self,
        call_id: str,
        tool: str,
        input: Dict[str, Any],
    ) -> ToolPart:
        """Add tool call part to message."""
        part = ToolPart(
            call_id=call_id,
            tool=tool,
            status=ToolState.PENDING,
            input=input,
        )
        self.parts.append(part)
        return part

    def add_reasoning(self, text: str) -> ReasoningPart:
        """Add reasoning part to message."""
        part = ReasoningPart(text=text, start_time=time.time())
        self.parts.append(part)
        return part

    def get_tool_parts(self) -> List[ToolPart]:
        """Get all tool call parts."""
        return [p for p in self.parts if isinstance(p, ToolPart)]

    def get_text_parts(self) -> List[TextPart]:
        """Get all text parts."""
        return [p for p in self.parts if isinstance(p, TextPart)]

    def get_full_text(self) -> str:
        """Get concatenated text from all text parts."""
        texts = [p.text for p in self.get_text_parts()]
        return "\n".join(texts)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role.value,
            "content": self.content,
            "parts": [p.to_dict() for p in self.parts],
            "agent": self.agent,
            "parent_id": self.parent_id,
            "finish_reason": self.finish_reason,
            "tokens": self.tokens,
            "cost": self.cost,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    def to_llm_format(self) -> Dict[str, Any]:
        """
        Convert to format suitable for LLM API.

        Returns:
            Dict with role, content, and optionally tool_calls for LLM.
            For assistant messages with tool calls, includes the tool_calls field
            in OpenAI format.
        """
        result = {
            "role": self.role.value,
            "content": self.content or self.get_full_text() or None,
        }

        # Include tool_calls for assistant messages that have tool parts
        if self.role == MessageRole.ASSISTANT:
            tool_parts = self.get_tool_parts()
            if tool_parts:
                result["tool_calls"] = [
                    {
                        "id": part.call_id,
                        "type": "function",
                        "function": {
                            "name": part.tool,
                            "arguments": (json.dumps(part.input) if part.input else "{}"),
                        },
                    }
                    for part in tool_parts
                ]

        return result
