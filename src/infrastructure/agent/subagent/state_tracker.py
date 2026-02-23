"""
SubAgent state tracking for background execution.

Tracks the lifecycle of SubAgent executions using in-memory state
with an optional Redis persistence layer for cross-process visibility.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SubAgentStatus(str, Enum):
    """Lifecycle status of a SubAgent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class SubAgentState:
    """Tracks the state of a single SubAgent execution.

    Attributes:
        execution_id: Unique execution identifier.
        subagent_id: ID of the SubAgent.
        subagent_name: Display name.
        conversation_id: Parent conversation.
        status: Current lifecycle status.
        task_description: What the SubAgent is doing.
        started_at: Execution start time.
        completed_at: Execution end time (if finished).
        progress: Optional progress percentage (0-100).
        result_summary: Brief result summary (if completed).
        error: Error message (if failed).
        tokens_used: Token consumption.
        tool_calls_count: Tool calls made.
    """

    execution_id: str
    subagent_id: str
    subagent_name: str
    conversation_id: str
    status: SubAgentStatus = SubAgentStatus.PENDING
    task_description: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: int = 0
    result_summary: str = ""
    error: Optional[str] = None
    tokens_used: int = 0
    tool_calls_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state to dictionary."""
        return {
            "execution_id": self.execution_id,
            "subagent_id": self.subagent_id,
            "subagent_name": self.subagent_name,
            "conversation_id": self.conversation_id,
            "status": self.status.value,
            "task_description": self.task_description,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "progress": self.progress,
            "result_summary": self.result_summary[:500],
            "error": self.error,
            "tokens_used": self.tokens_used,
            "tool_calls_count": self.tool_calls_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubAgentState":
        """Deserialize from dictionary."""
        state = cls(
            execution_id=data["execution_id"],
            subagent_id=data["subagent_id"],
            subagent_name=data["subagent_name"],
            conversation_id=data["conversation_id"],
            task_description=data.get("task_description", ""),
        )
        status_str = data.get("status", "pending")
        state.status = SubAgentStatus(status_str)
        if data.get("started_at"):
            state.started_at = datetime.fromisoformat(data["started_at"])
        if data.get("completed_at"):
            state.completed_at = datetime.fromisoformat(data["completed_at"])
        state.progress = data.get("progress", 0)
        state.result_summary = data.get("result_summary", "")
        state.error = data.get("error")
        state.tokens_used = data.get("tokens_used", 0)
        state.tool_calls_count = data.get("tool_calls_count", 0)
        return state


class StateTracker:
    """In-memory SubAgent execution state tracker.

    Tracks active and recently completed SubAgent executions
    for a conversation. Uses a bounded cache to prevent memory leaks.

    For cross-process visibility (e.g., multiple API workers),
    can be extended with Redis persistence.
    """

    MAX_TRACKED = 50  # Max states to keep per conversation

    def __init__(self) -> None:
        # conversation_id -> {execution_id -> SubAgentState}
        self._states: Dict[str, Dict[str, SubAgentState]] = {}

    def register(
        self,
        execution_id: str,
        subagent_id: str,
        subagent_name: str,
        conversation_id: str,
        task_description: str = "",
    ) -> SubAgentState:
        """Register a new SubAgent execution.

        Args:
            execution_id: Unique execution ID.
            subagent_id: SubAgent ID.
            subagent_name: SubAgent display name.
            conversation_id: Parent conversation.
            task_description: What the SubAgent will do.

        Returns:
            The created SubAgentState.
        """
        state = SubAgentState(
            execution_id=execution_id,
            subagent_id=subagent_id,
            subagent_name=subagent_name,
            conversation_id=conversation_id,
            task_description=task_description,
        )

        if conversation_id not in self._states:
            self._states[conversation_id] = {}

        conv_states = self._states[conversation_id]
        conv_states[execution_id] = state

        # Evict old completed states if over limit
        if len(conv_states) > self.MAX_TRACKED:
            self._evict_oldest(conversation_id)

        logger.debug(f"[StateTracker] Registered {execution_id} for {subagent_name}")
        return state

    def start(self, execution_id: str, conversation_id: str) -> Optional[SubAgentState]:
        """Mark execution as started."""
        state = self._get(execution_id, conversation_id)
        if state:
            state.status = SubAgentStatus.RUNNING
            state.started_at = datetime.now(timezone.utc)
        return state

    def complete(
        self,
        execution_id: str,
        conversation_id: str,
        summary: str = "",
        tokens_used: int = 0,
        tool_calls_count: int = 0,
    ) -> Optional[SubAgentState]:
        """Mark execution as completed."""
        state = self._get(execution_id, conversation_id)
        if state:
            state.status = SubAgentStatus.COMPLETED
            state.completed_at = datetime.now(timezone.utc)
            state.progress = 100
            state.result_summary = summary
            state.tokens_used = tokens_used
            state.tool_calls_count = tool_calls_count
        return state

    def fail(
        self,
        execution_id: str,
        conversation_id: str,
        error: str = "",
    ) -> Optional[SubAgentState]:
        """Mark execution as failed."""
        state = self._get(execution_id, conversation_id)
        if state:
            state.status = SubAgentStatus.FAILED
            state.completed_at = datetime.now(timezone.utc)
            state.error = error
        return state

    def cancel(
        self, execution_id: str, conversation_id: str
    ) -> Optional[SubAgentState]:
        """Mark execution as cancelled."""
        state = self._get(execution_id, conversation_id)
        if state:
            state.status = SubAgentStatus.CANCELLED
            state.completed_at = datetime.now(timezone.utc)
        return state

    def update_progress(
        self, execution_id: str, conversation_id: str, progress: int
    ) -> Optional[SubAgentState]:
        """Update execution progress (0-100)."""
        state = self._get(execution_id, conversation_id)
        if state:
            state.progress = min(max(progress, 0), 100)
        return state

    def get_state(
        self, execution_id: str, conversation_id: str
    ) -> Optional[SubAgentState]:
        """Get state for a specific execution."""
        return self._get(execution_id, conversation_id)

    def get_active(self, conversation_id: str) -> List[SubAgentState]:
        """Get all active (pending/running) executions for a conversation."""
        conv_states = self._states.get(conversation_id, {})
        return [
            s
            for s in conv_states.values()
            if s.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)
        ]

    def get_all(self, conversation_id: str) -> List[SubAgentState]:
        """Get all tracked executions for a conversation."""
        return list(self._states.get(conversation_id, {}).values())

    def clear(self, conversation_id: str) -> None:
        """Clear all tracked states for a conversation."""
        self._states.pop(conversation_id, None)

    def _get(
        self, execution_id: str, conversation_id: str
    ) -> Optional[SubAgentState]:
        """Get state by execution and conversation ID."""
        return self._states.get(conversation_id, {}).get(execution_id)

    def _evict_oldest(self, conversation_id: str) -> None:
        """Evict oldest completed states to stay under MAX_TRACKED."""
        conv_states = self._states.get(conversation_id, {})
        completed = [
            (eid, s)
            for eid, s in conv_states.items()
            if s.status
            in (SubAgentStatus.COMPLETED, SubAgentStatus.FAILED, SubAgentStatus.CANCELLED)
        ]
        # Sort by completion time, evict oldest
        completed.sort(key=lambda x: x[1].completed_at or datetime.min.replace(tzinfo=timezone.utc))
        while len(conv_states) > self.MAX_TRACKED and completed:
            eid, _ = completed.pop(0)
            del conv_states[eid]
