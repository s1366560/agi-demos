"""
WebSocket Topic Management

Manages topic subscriptions for unified WebSocket event delivery.
Supports multiple topic types:
- agent:{conversation_id} - Agent conversation events
- sandbox:{project_id} - Sandbox lifecycle events
- system:{event_type} - System-wide events
- lifecycle:{tenant_id}:{project_id} - Agent lifecycle state
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TopicType(str, Enum):
    """Supported topic types."""

    AGENT = "agent"
    SANDBOX = "sandbox"
    SYSTEM = "system"
    LIFECYCLE = "lifecycle"


@dataclass
class TopicSubscription:
    """Represents a topic subscription."""

    topic_type: TopicType
    topic_key: str  # Full topic string e.g. "agent:conv-123"
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


class TopicManager:
    """
    Manages WebSocket topic subscriptions.

    Features:
    - Multi-topic subscription per session
    - Topic -> Sessions reverse index for efficient broadcasting
    - Thread-safe operations with asyncio Lock
    - Topic parsing and validation
    """

    def __init__(self) -> None:
        # session_id -> set of subscribed topic keys
        self._session_topics: dict[str, set[str]] = {}
        # topic_key -> set of session_ids
        self._topic_sessions: dict[str, set[str]] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    @staticmethod
    def parse_topic(topic: str) -> tuple[TopicType, str, str | None]:
        """
        Parse a topic string into its components.

        Args:
            topic: Topic string (e.g., "agent:conv-123", "sandbox:proj-456")

        Returns:
            Tuple of (topic_type, primary_id, secondary_id)
            secondary_id is only used for lifecycle topics

        Raises:
            ValueError: If topic format is invalid
        """
        parts = topic.split(":")
        if len(parts) < 2:
            raise ValueError(f"Invalid topic format: {topic}")

        try:
            topic_type = TopicType(parts[0])
        except ValueError:
            raise ValueError(f"Unknown topic type: {parts[0]}") from None

        if topic_type == TopicType.LIFECYCLE:
            if len(parts) != 3:
                raise ValueError(f"Lifecycle topic requires tenant:project format: {topic}")
            return topic_type, parts[1], parts[2]

        return topic_type, parts[1], None

    @staticmethod
    def build_topic(topic_type: TopicType, primary_id: str, secondary_id: str | None = None) -> str:
        """Build a topic string from components."""
        if topic_type == TopicType.LIFECYCLE and secondary_id:
            return f"{topic_type.value}:{primary_id}:{secondary_id}"
        return f"{topic_type.value}:{primary_id}"

    async def subscribe(self, session_id: str, topic: str) -> bool:
        """
        Subscribe a session to a topic.

        Args:
            session_id: The WebSocket session ID
            topic: The topic to subscribe to

        Returns:
            True if subscription was created, False if already subscribed
        """
        # Validate topic format
        try:
            TopicManager.parse_topic(topic)
        except ValueError as e:
            logger.warning(f"[TopicManager] Invalid topic: {e}")
            return False

        async with self._lock:
            # Initialize session set if needed
            if session_id not in self._session_topics:
                self._session_topics[session_id] = set()

            # Check if already subscribed
            if topic in self._session_topics[session_id]:
                return False

            # Add subscription
            self._session_topics[session_id].add(topic)

            # Update reverse index
            if topic not in self._topic_sessions:
                self._topic_sessions[topic] = set()
            self._topic_sessions[topic].add(session_id)

            logger.debug(f"[TopicManager] Session {session_id[:8]}... subscribed to {topic}")
            return True

    async def unsubscribe(self, session_id: str, topic: str) -> bool:
        """
        Unsubscribe a session from a topic.

        Args:
            session_id: The WebSocket session ID
            topic: The topic to unsubscribe from

        Returns:
            True if unsubscribed, False if not subscribed
        """
        async with self._lock:
            # Check if session has subscriptions
            if session_id not in self._session_topics:
                return False

            # Check if subscribed to this topic
            if topic not in self._session_topics[session_id]:
                return False

            # Remove subscription
            self._session_topics[session_id].discard(topic)

            # Update reverse index
            if topic in self._topic_sessions:
                self._topic_sessions[topic].discard(session_id)
                if not self._topic_sessions[topic]:
                    del self._topic_sessions[topic]

            logger.debug(f"[TopicManager] Session {session_id[:8]}... unsubscribed from {topic}")
            return True

    async def unsubscribe_all(self, session_id: str) -> set[str]:
        """
        Unsubscribe a session from all topics.

        Args:
            session_id: The WebSocket session ID

        Returns:
            Set of topics that were unsubscribed
        """
        async with self._lock:
            if session_id not in self._session_topics:
                return set()

            topics = self._session_topics.pop(session_id)

            # Update reverse index
            for topic in topics:
                if topic in self._topic_sessions:
                    self._topic_sessions[topic].discard(session_id)
                    if not self._topic_sessions[topic]:
                        del self._topic_sessions[topic]

            logger.debug(
                f"[TopicManager] Session {session_id[:8]}... unsubscribed from {len(topics)} topics"
            )
            return topics

    def get_subscribers(self, topic: str) -> set[str]:
        """Get all session IDs subscribed to a topic."""
        return self._topic_sessions.get(topic, set()).copy()

    def get_subscriptions(self, session_id: str) -> set[str]:
        """Get all topics a session is subscribed to."""
        return self._session_topics.get(session_id, set()).copy()

    def is_subscribed(self, session_id: str, topic: str) -> bool:
        """Check if a session is subscribed to a topic."""
        return topic in self._session_topics.get(session_id, set())

    def get_stats(self) -> dict[str, Any]:
        """Get subscription statistics."""
        return {
            "total_sessions": len(self._session_topics),
            "total_topics": len(self._topic_sessions),
            "topics_by_type": {
                topic_type.value: sum(
                    1 for t in self._topic_sessions if t.startswith(f"{topic_type.value}:")
                )
                for topic_type in TopicType
            },
        }


# Global topic manager instance
_topic_manager: TopicManager | None = None


def get_topic_manager() -> TopicManager:
    """Get the global topic manager instance."""
    global _topic_manager
    if _topic_manager is None:
        _topic_manager = TopicManager()
    return _topic_manager
