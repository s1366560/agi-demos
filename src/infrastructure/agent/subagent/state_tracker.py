"""
SubAgent state tracking for background execution.

Tracks the lifecycle of SubAgent executions using in-memory state
with an optional Redis persistence layer for cross-process visibility.
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

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
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: int = 0
    result_summary: str = ""
    error: str | None = None
    tokens_used: int = 0
    tool_calls_count: int = 0

    def to_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, data: dict[str, Any]) -> "SubAgentState":
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

    def __init__(self, redis_client: Any | None = None) -> None:  # noqa: ANN401
        # conversation_id -> {execution_id -> SubAgentState}
        self._states: dict[str, dict[str, SubAgentState]] = {}
        self._redis: Any | None = redis_client
        self._lock = threading.Lock()
        self._background_tasks: set[asyncio.Task[None]] = set()

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
        with self._lock:
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

        self._fire_and_forget_persist(state)
        return state

    def start(self, execution_id: str, conversation_id: str) -> SubAgentState | None:
        """Mark execution as started."""
        with self._lock:
            state = self._get(execution_id, conversation_id)
            if state:
                state.status = SubAgentStatus.RUNNING
                state.started_at = datetime.now(UTC)
        if state:
            self._fire_and_forget_persist(state)
        return state

    def complete(
        self,
        execution_id: str,
        conversation_id: str,
        summary: str = "",
        tokens_used: int = 0,
        tool_calls_count: int = 0,
    ) -> SubAgentState | None:
        """Mark execution as completed."""
        with self._lock:
            state = self._get(execution_id, conversation_id)
            if state:
                state.status = SubAgentStatus.COMPLETED
                state.completed_at = datetime.now(UTC)
                state.progress = 100
                state.result_summary = summary
                state.tokens_used = tokens_used
                state.tool_calls_count = tool_calls_count
        if state:
            self._fire_and_forget_persist(state)
        return state

    def fail(
        self,
        execution_id: str,
        conversation_id: str,
        error: str = "",
    ) -> SubAgentState | None:
        """Mark execution as failed."""
        with self._lock:
            state = self._get(execution_id, conversation_id)
            if state:
                state.status = SubAgentStatus.FAILED
                state.completed_at = datetime.now(UTC)
                state.error = error
        if state:
            self._fire_and_forget_persist(state)
        return state

    def cancel(self, execution_id: str, conversation_id: str) -> SubAgentState | None:
        """Mark execution as cancelled."""
        with self._lock:
            state = self._get(execution_id, conversation_id)
            if state:
                state.status = SubAgentStatus.CANCELLED
                state.completed_at = datetime.now(UTC)
        if state:
            self._fire_and_forget_persist(state)
        return state

    def update_progress(
        self, execution_id: str, conversation_id: str, progress: int
    ) -> SubAgentState | None:
        """Update execution progress (0-100)."""
        with self._lock:
            state = self._get(execution_id, conversation_id)
            if state:
                state.progress = min(max(progress, 0), 100)
        if state:
            self._fire_and_forget_persist(state)
        return state

    def get_state(self, execution_id: str, conversation_id: str) -> SubAgentState | None:
        """Get state for a specific execution."""
        return self._get(execution_id, conversation_id)

    def get_active(self, conversation_id: str) -> list[SubAgentState]:
        """Get all active (pending/running) executions for a conversation."""
        conv_states = self._states.get(conversation_id, {})
        return [
            s
            for s in conv_states.values()
            if s.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)
        ]

    def get_all(self, conversation_id: str) -> list[SubAgentState]:
        """Get all tracked executions for a conversation."""
        return list(self._states.get(conversation_id, {}).values())

    def clear(self, conversation_id: str) -> None:
        """Clear all tracked states for a conversation."""
        with self._lock:
            self._states.pop(conversation_id, None)

    def _get(self, execution_id: str, conversation_id: str) -> SubAgentState | None:
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
        completed.sort(key=lambda x: x[1].completed_at or datetime.min.replace(tzinfo=UTC))
        while len(conv_states) > self.MAX_TRACKED and completed:
            eid, _ = completed.pop(0)
            del conv_states[eid]

    def get_state_by_execution_id(self, execution_id: str) -> SubAgentState | None:
        """Find state by execution_id across all conversations.

        This scans all tracked conversations, so prefer get_state() when
        the conversation_id is known.

        Args:
            execution_id: The execution ID to look up.

        Returns:
            The SubAgentState if found, else None.
        """
        with self._lock:
            for conv_states in self._states.values():
                if execution_id in conv_states:
                    return conv_states[execution_id]
        return None

    def _fire_and_forget_persist(self, state: SubAgentState) -> None:
        """Persist state to Redis in a fire-and-forget manner.

        Creates an asyncio task if a Redis client is available.
        Failures are logged but do not affect in-memory state.
        """
        if self._redis is None:
            return
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._persist_to_redis(state))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            # No running event loop; skip Redis persistence
            logger.debug("[StateTracker] No event loop for Redis persist")

    async def _persist_to_redis(self, state: SubAgentState) -> None:
        """Write state to Redis with a TTL.

        Key format: ``subagent:state:{conversation_id}:{execution_id}``
        TTL: 3600 seconds (1 hour).
        """
        if self._redis is None:
            return
        key = f"subagent:state:{state.conversation_id}:{state.execution_id}"
        try:
            payload = json.dumps(state.to_dict())
            await self._redis.setex(key, 3600, payload)
        except Exception as exc:
            logger.warning(f"[StateTracker] Redis persist failed for {key}: {exc}")

    async def recover_from_redis(self, conversation_id: str) -> list[SubAgentState]:
        """Recover states for a conversation from Redis.

        Scans Redis for keys matching the conversation and deserializes
        them back into ``SubAgentState`` objects.

        Args:
            conversation_id: Conversation to recover.

        Returns:
            List of recovered SubAgentState objects.
        """
        if self._redis is None:
            return []

        recovered: list[SubAgentState] = []
        pattern = f"subagent:state:{conversation_id}:*"
        try:
            keys: list[str] = []
            cursor: int | str = 0
            while True:
                cursor, batch = await self._redis.scan(cursor=cursor, match=pattern, count=100)
                keys.extend(batch)
                if cursor == 0:
                    break

            for key in keys:
                raw = await self._redis.get(key)
                if raw:
                    data = json.loads(raw)
                    recovered.append(SubAgentState.from_dict(data))
        except Exception as exc:
            logger.warning(f"[StateTracker] Redis recovery failed for {conversation_id}: {exc}")

        return recovered
