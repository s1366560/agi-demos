"""Structured result types for tool execution.

Provides ToolResult, ToolAttachment, and ToolEvent dataclasses that replace
raw string returns from tools. These types carry structured output with
metadata, attachments, error flagging, and pipeline event signaling.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolAttachment:
    """File attachment from tool execution.

    Attributes:
        name: Filename or identifier for the attachment.
        content: Raw bytes or text content.
        mime_type: MIME type of the content.
    """

    name: str
    content: bytes | str
    mime_type: str = "application/octet-stream"


@dataclass
class ToolResult:
    """Structured result from tool execution.

    Replaces raw string returns. Provides structured output with metadata,
    title, attachments, and error flagging.

    Attributes:
        output: Main output content (string for LLM consumption).
        title: Short title for UI display.
        metadata: Structured metadata dict.
        attachments: File attachments produced by the tool.
        is_error: Whether this result represents an error.
        was_truncated: Whether output was truncated.
        original_bytes: Original size before truncation.
        full_output_path: Path to full output if truncated.
    """

    output: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[ToolAttachment] = field(default_factory=list)
    is_error: bool = False
    was_truncated: bool = False
    original_bytes: int | None = None
    full_output_path: str | None = None


@dataclass
class ToolEvent:
    """Event emitted during tool execution pipeline.

    Factory class methods produce typed events for each lifecycle stage.

    Attributes:
        type: Event type identifier.
        tool_name: Name of the tool that produced this event.
        data: Arbitrary event payload.
        timestamp: Epoch seconds when the event was created.
    """

    type: str
    tool_name: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def started(cls, tool_name: str, args: dict[str, Any]) -> ToolEvent:
        """Create a 'started' event when tool execution begins."""
        return cls(type="started", tool_name=tool_name, data={"args": args})

    @classmethod
    def completed(
        cls,
        tool_name: str,
        result: ToolResult,
        artifacts: list[Any] | None = None,
    ) -> ToolEvent:
        """Create a 'completed' event when tool execution finishes."""
        data: dict[str, Any] = {
            "is_error": result.is_error,
            "was_truncated": result.was_truncated,
            "_result": result,
        }
        if artifacts is not None:
            data["artifacts"] = artifacts
        return cls(type="completed", tool_name=tool_name, data=data)

    @classmethod
    def denied(cls, tool_name: str) -> ToolEvent:
        """Create a 'denied' event when tool permission is refused."""
        return cls(type="denied", tool_name=tool_name)

    @classmethod
    def doom_loop(cls, tool_name: str) -> ToolEvent:
        """Create a 'doom_loop' event when repeated failure is detected."""
        return cls(type="doom_loop", tool_name=tool_name)

    @classmethod
    def permission_asked(cls, tool_name: str) -> ToolEvent:
        """Create a 'permission_asked' event when awaiting user approval."""
        return cls(type="permission_asked", tool_name=tool_name)

    @classmethod
    def aborted(cls, tool_name: str) -> ToolEvent:
        """Create an 'aborted' event when tool execution is cancelled."""
        return cls(type="aborted", tool_name=tool_name)
