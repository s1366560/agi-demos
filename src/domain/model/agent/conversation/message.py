"""Message entity for conversation messages."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict

from src.domain.model.agent.execution.thought_level import ThoughtLevel
from src.domain.shared_kernel import Entity


class MessageRole(str, Enum):
    """Role of the message sender."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageType(str, Enum):
    """Type of message content."""

    TEXT = "text"
    THOUGHT = "thought"  # Agent reasoning
    TOOL_CALL = "tool_call"  # Agent invoking a tool
    TOOL_RESULT = "tool_result"  # Tool execution result
    ERROR = "error"

    # Multi-level thinking message types
    WORK_PLAN = "work_plan"  # Work-level plan
    STEP_START = "step_start"  # Step beginning
    STEP_END = "step_end"  # Step completion
    PATTERN_MATCH = "pattern_match"  # Workflow pattern matched


@dataclass(kw_only=True)
class ToolCall:
    """
    Represents a tool invocation by the agent.

    Attributes:
        name: The name of the tool being called
        arguments: The arguments passed to the tool
        call_id: Unique identifier for this tool call
    """

    name: str
    arguments: Dict[str, Any]
    call_id: str | None = None


@dataclass(kw_only=True)
class ToolResult:
    """
    Represents the result of a tool execution.

    Attributes:
        tool_call_id: The ID of the tool call this result corresponds to
        result: The result output from the tool
        is_error: Whether the tool execution resulted in an error
        error_message: Optional error message if execution failed
    """

    tool_call_id: str
    result: str
    is_error: bool = False
    error_message: str | None = None


@dataclass(kw_only=True)
class Message(Entity):
    """
    A single message in a conversation.

    Messages can be from the user, assistant (agent), or system.
    They can contain text, agent thoughts, tool calls, or tool results.
    """

    conversation_id: str
    role: MessageRole
    content: str
    message_type: MessageType = MessageType.TEXT
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Multi-level thinking support
    work_plan_ref: str | None = None  # ID of the work plan this belongs to
    task_step_index: int | None = None  # Which step this message is for
    thought_level: ThoughtLevel | None = None  # WORK or TASK

    def __post_init__(self):
        """Validate message consistency."""
        self._validate_tool_matching()

    def _validate_tool_matching(self) -> None:
        """Validate that tool results reference valid tool calls."""
        if not self.tool_results:
            return

        # Collect all tool_call call_ids
        call_ids = {call.call_id for call in self.tool_calls if call.call_id is not None}

        # Check each result references a valid call
        for result in self.tool_results:
            if result.tool_call_id not in call_ids:
                raise ValueError(
                    f"ToolResult references unknown tool_call_id: {result.tool_call_id}"
                )

    def is_from_user(self) -> bool:
        """Check if this message is from the user."""
        return self.role == MessageRole.USER

    def is_from_assistant(self) -> bool:
        """Check if this message is from the assistant."""
        return self.role == MessageRole.ASSISTANT

    def has_tool_calls(self) -> bool:
        """Check if this message contains tool calls."""
        return len(self.tool_calls) > 0

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to this message."""
        self.tool_calls.append(tool_call)

    def add_tool_result(self, tool_result: ToolResult) -> None:
        """Add a tool result to this message."""
        self.tool_results.append(tool_result)

    def get_tool_result(self, call_id: str) -> ToolResult | None:
        """Get the tool result for a specific call_id."""
        for result in self.tool_results:
            if result.tool_call_id == call_id:
                return result
        return None
