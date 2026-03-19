"""In-memory registry tracking which agent owns which conversation."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSession:
    """Immutable snapshot of an agent-to-conversation binding.

    Attributes:
        agent_id: Unique identifier of the agent.
        conversation_id: Conversation this agent is handling.
        project_id: Project scope.
        registered_at: UTC timestamp when the session was registered.
    """

    agent_id: str
    conversation_id: str
    project_id: str
    registered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AgentSessionRegistry:
    """Thread-safe, in-memory registry of active agent sessions.

    Maps (project_id, conversation_id) -> AgentSession so that the
    system can look up which agent currently owns a conversation.

    All mutations are guarded by an asyncio.Lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # key = (project_id, conversation_id)
        self._sessions: dict[tuple[str, str], AgentSession] = {}

    async def register(
        self,
        agent_id: str,
        conversation_id: str,
        project_id: str,
    ) -> AgentSession:
        """Register an agent session for a conversation."""
        session = AgentSession(
            agent_id=agent_id,
            conversation_id=conversation_id,
            project_id=project_id,
        )
        async with self._lock:
            key = (project_id, conversation_id)
            self._sessions[key] = session
            logger.debug(
                "Registered agent session: agent=%s conv=%s project=%s",
                agent_id,
                conversation_id,
                project_id,
            )
        return session

    async def unregister(
        self,
        conversation_id: str,
        project_id: str,
    ) -> AgentSession | None:
        """Remove the session for a conversation. Returns the removed session."""
        async with self._lock:
            return self._sessions.pop((project_id, conversation_id), None)

    async def get_session_for_conversation(
        self,
        conversation_id: str,
        project_id: str,
    ) -> AgentSession | None:
        """Look up the active agent session for a conversation."""
        async with self._lock:
            return self._sessions.get((project_id, conversation_id))

    async def get_sessions(
        self,
        project_id: str,
    ) -> list[AgentSession]:
        """Return all active sessions for a project."""
        async with self._lock:
            return [s for (pid, _), s in self._sessions.items() if pid == project_id]

    async def get_active_agent_ids(
        self,
        project_id: str,
    ) -> set[str]:
        """Return the set of agent IDs with active sessions in a project."""
        async with self._lock:
            return {s.agent_id for (pid, _), s in self._sessions.items() if pid == project_id}

    async def clear_project(self, project_id: str) -> int:
        """Remove all sessions for a project. Returns count removed."""
        async with self._lock:
            keys_to_remove = [k for k in self._sessions if k[0] == project_id]
            for k in keys_to_remove:
                del self._sessions[k]
            return len(keys_to_remove)
