"""Thread-Bound Sub-Agent Sessions.

Manages bindings between thread contexts (e.g., Feishu threads) and sub-agents,
ensuring subsequent messages within a thread are routed to the same sub-agent
for the duration of the TTL.

This is an in-memory service instantiated per-process — no external stores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThreadBinding:
    """Immutable value object representing a thread-to-agent binding.

    Attributes:
        thread_id: External thread identifier (e.g., Feishu thread ID).
        agent_id: The sub-agent bound to this thread.
        conversation_id: Conversation context for the binding.
        created_at: When this binding was established.
        ttl_seconds: Time-to-live in seconds before the binding expires.
    """

    thread_id: str
    agent_id: str
    conversation_id: str
    created_at: datetime
    ttl_seconds: int = 3600


class ThreadBindingService:
    """Manages in-memory thread-to-agent bindings with TTL-based expiry.

    Thread bindings ensure that once a sub-agent is spawned for a thread
    context, subsequent messages in that thread are routed to the same
    sub-agent until the binding expires.
    """

    def __init__(self, default_ttl: int = 3600) -> None:
        self._default_ttl = default_ttl
        self._bindings: dict[str, ThreadBinding] = {}

    def bind(
        self,
        thread_id: str,
        agent_id: str,
        conversation_id: str,
        ttl_seconds: int | None = None,
    ) -> ThreadBinding:
        """Create or overwrite a binding for a thread.

        Args:
            thread_id: External thread identifier.
            agent_id: Sub-agent to bind.
            conversation_id: Conversation context.
            ttl_seconds: Optional TTL override; uses default if None.

        Returns:
            The newly created ThreadBinding.
        """
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        binding = ThreadBinding(
            thread_id=thread_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            created_at=datetime.now(UTC),
            ttl_seconds=effective_ttl,
        )
        self._bindings[thread_id] = binding
        logger.info(
            "Bound thread %s to agent %s (conversation=%s, ttl=%ds)",
            thread_id,
            agent_id,
            conversation_id,
            effective_ttl,
        )
        return binding

    def resolve(self, thread_id: str) -> ThreadBinding | None:
        """Resolve a thread to its bound agent.

        Returns the binding if it exists and has not expired. Expired
        bindings are cleaned up on access.

        Args:
            thread_id: External thread identifier to resolve.

        Returns:
            The active ThreadBinding, or None if absent or expired.
        """
        binding = self._bindings.get(thread_id)
        if binding is None:
            return None

        if self._is_expired(binding):
            del self._bindings[thread_id]
            logger.debug(
                "Binding for thread %s expired (agent=%s)",
                thread_id,
                binding.agent_id,
            )
            return None

        return binding

    def unbind(self, thread_id: str) -> bool:
        """Remove a thread binding.

        Args:
            thread_id: External thread identifier to unbind.

        Returns:
            True if a binding existed and was removed, False otherwise.
        """
        if thread_id in self._bindings:
            removed = self._bindings.pop(thread_id)
            logger.info(
                "Unbound thread %s from agent %s",
                thread_id,
                removed.agent_id,
            )
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove all expired bindings.

        Returns:
            Number of expired bindings removed.
        """
        now = datetime.now(UTC)
        expired_ids = [
            tid
            for tid, binding in self._bindings.items()
            if binding.created_at + timedelta(seconds=binding.ttl_seconds) < now
        ]
        for tid in expired_ids:
            del self._bindings[tid]

        if expired_ids:
            logger.info("Cleaned up %d expired thread bindings", len(expired_ids))
        return len(expired_ids)

    def active_count(self) -> int:
        """Return the number of non-expired bindings.

        Returns:
            Count of active (non-expired) bindings.
        """
        now = datetime.now(UTC)
        return sum(
            1
            for binding in self._bindings.values()
            if binding.created_at + timedelta(seconds=binding.ttl_seconds) >= now
        )

    @staticmethod
    def _is_expired(binding: ThreadBinding) -> bool:
        """Check whether a binding has exceeded its TTL."""
        return binding.created_at + timedelta(seconds=binding.ttl_seconds) < datetime.now(UTC)
