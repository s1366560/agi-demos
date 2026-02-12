"""Structured result model for SubAgent execution.

SubAgentResult captures the output of an independent SubAgent execution,
including a summary for the orchestrator, execution metrics, and artifacts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SubAgentResult:
    """Structured result from a SubAgent execution.

    This is the contract between a SubAgent process and the orchestrator.
    The orchestrator receives this result and injects a summary into the
    main agent's context window.

    Attributes:
        subagent_id: ID of the SubAgent that produced this result.
        subagent_name: Display name of the SubAgent.
        summary: LLM-generated or extracted summary of the execution.
        success: Whether the execution completed successfully.
        tool_calls_count: Number of tool calls made during execution.
        tokens_used: Total tokens consumed (input + output).
        execution_time_ms: Wall-clock execution time in milliseconds.
        final_content: Raw final text content from the SubAgent.
        artifacts: List of artifact references produced.
        error: Error message if execution failed.
        metadata: Additional execution metadata.
        completed_at: Timestamp of completion.
    """

    subagent_id: str
    subagent_name: str
    summary: str
    success: bool
    tool_calls_count: int = 0
    tokens_used: int = 0
    execution_time_ms: int = 0
    final_content: str = ""
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_context_message(self) -> str:
        """Format result as a context message for the orchestrator.

        Returns a concise message that can be injected into the main
        agent's conversation as an assistant/system message.
        """
        if self.success:
            header = f"[SubAgent '{self.subagent_name}' completed successfully]"
        else:
            header = f"[SubAgent '{self.subagent_name}' failed: {self.error}]"

        parts = [header]

        if self.summary:
            parts.append(f"Result: {self.summary}")

        if self.tool_calls_count > 0:
            parts.append(f"(Used {self.tool_calls_count} tool calls, {self.tokens_used} tokens)")

        return "\n".join(parts)

    def to_event_data(self) -> Dict[str, Any]:
        """Convert to SSE event payload."""
        return {
            "subagent_id": self.subagent_id,
            "subagent_name": self.subagent_name,
            "summary": self.summary,
            "success": self.success,
            "tool_calls_count": self.tool_calls_count,
            "tokens_used": self.tokens_used,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
        }
