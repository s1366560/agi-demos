"""Session repository interface (Port)."""

from abc import ABC, abstractmethod
from typing import Optional, List
from datetime import datetime

from src.domain.model.session.entities import Session, SessionMessage, SessionStatus, SessionKind, MessageRole
from src.domain.model.session.value_objects import SessionKey
from src.domain.model.session.aggregates import SessionAggregate


class SessionRepository(ABC):
    """Repository for Session entities."""

    @abstractmethod
    async def save(self, session: Session) -> None:
        """Save a session (create or update)."""
        pass

    @abstractmethod
    async def get_by_id(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        pass

    @abstractmethod
    async def get_by_session_key(self, session_key: str) -> Optional[Session]:
        """Get a session by session key."""
        pass

    @abstractmethod
    async def list_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        kind: Optional[SessionKind] = None,
        status: Optional[SessionStatus] = None,
        limit: int = 50,
        offset: int = 0,
        active_minutes: Optional[int] = None,
    ) -> List[Session]:
        """List sessions with optional filters."""
        pass

    @abstractmethod
    async def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    async def count_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        kind: Optional[SessionKind] = None,
        status: Optional[SessionStatus] = None,
    ) -> int:
        """Count sessions with optional filters."""
        pass


class SessionMessageRepository(ABC):
    """Repository for SessionMessage entities."""

    @abstractmethod
    async def save(self, message: SessionMessage) -> None:
        """Save a message (create or update)."""
        pass

    @abstractmethod
    async def get_by_id(self, message_id: str) -> Optional[SessionMessage]:
        """Get a message by ID."""
        pass

    @abstractmethod
    async def get_session_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        include_tools: bool = False,
    ) -> List[SessionMessage]:
        """Get messages for a session."""
        pass

    @abstractmethod
    async def get_last_messages(
        self,
        session_id: str,
        limit: int = 5,
        include_tools: bool = False,
    ) -> List[SessionMessage]:
        """Get the last N messages for a session."""
        pass

    @abstractmethod
    async def delete_session_messages(self, session_id: str) -> int:
        """Delete all messages for a session. Returns count deleted."""
        pass

    @abstractmethod
    async def count_session_messages(self, session_id: str) -> int:
        """Count messages in a session."""
        pass


class SessionAggregateRepository(ABC):
    """Repository for SessionAggregate (combines Session + Messages)."""

    @abstractmethod
    async def get_aggregate(self, session_id: str) -> Optional[SessionAggregate]:
        """Get a session aggregate with its messages."""
        pass

    @abstractmethod
    async def get_aggregate_by_key(self, session_key: str) -> Optional[SessionAggregate]:
        """Get a session aggregate by session key."""
        pass

    @abstractmethod
    async def save_aggregate(self, aggregate: SessionAggregate) -> None:
        """Save a session aggregate (session + all messages)."""
        pass

    @abstractmethod
    async def create_aggregate(
        self,
        session_key: SessionKey,
        agent_id: str,
        kind: SessionKind = SessionKind.MAIN,
        model: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> SessionAggregate:
        """Create a new session aggregate."""
        pass
