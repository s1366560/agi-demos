"""
Agent Session Registry for HITL Real-time Response Delivery.

This module provides a registry for tracking active Agent sessions
that are waiting for HITL responses. It enables direct in-memory
delivery of HITL responses without going through Temporal.
delivery of HITL responses within the same worker process.

Architecture:
- Each Agent Worker maintains its own registry instance
- Sessions register when they start waiting for HITL
- HITLResponseListener uses the registry to find target sessions
- Sessions unregister when HITL is resolved or cancelled

Thread Safety:
- Uses asyncio.Lock for concurrent access
- All public methods are async-safe
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HITLWaiter:
    """Represents an active HITL wait registration."""

    request_id: str
    conversation_id: str
    hitl_type: str
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Callback to invoke when response arrives
    response_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None
    # Event to signal when response is ready (alternative to callback)
    response_event: asyncio.Event | None = None
    # Response data (set when response arrives)
    response_data: dict[str, Any] | None = None


class AgentSessionRegistry:
    """
    Registry for tracking Agent sessions waiting for HITL responses.

    This enables direct in-memory delivery of HITL responses when
    the session is running on the same Worker that receives the response.

    Design:
    - Single instance per Agent Worker process
    - Fast O(1) lookups by request_id or conversation_id
    - Automatic cleanup on timeout or cancellation
    - Thread-safe with asyncio.Lock

    Usage:
        registry = AgentSessionRegistry()

        # When HITL pause starts
        waiter = await registry.register_waiter(
            request_id="clar_abc123",
            conversation_id="conv_xyz",
            hitl_type="clarification",
        )

        # Wait for response (with timeout)
        response = await registry.wait_for_response(request_id, timeout=300)

        # Or use callback style
        await registry.register_waiter(
            request_id="clar_abc123",
            conversation_id="conv_xyz",
            hitl_type="clarification",
            response_callback=my_callback,
        )
    """

    def __init__(self) -> None:
        # request_id -> HITLWaiter
        self._waiters: dict[str, HITLWaiter] = {}
        # conversation_id -> List[request_id] (multiple HITL requests possible)
        self._conversation_requests: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

        # Metrics
        self._total_registered = 0
        self._total_delivered = 0
        self._total_timeouts = 0

    async def register_waiter(
        self,
        request_id: str,
        conversation_id: str,
        hitl_type: str,
        response_callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> HITLWaiter:
        """
        Register a session as waiting for an HITL response.

        Args:
            request_id: Unique HITL request ID
            conversation_id: Conversation this HITL belongs to
            hitl_type: Type of HITL (clarification, decision, env_var, permission)
            response_callback: Optional async callback when response arrives

        Returns:
            HITLWaiter object for tracking
        """
        async with self._lock:
            # Create waiter with event for synchronous waiting
            waiter = HITLWaiter(
                request_id=request_id,
                conversation_id=conversation_id,
                hitl_type=hitl_type,
                response_callback=response_callback,
                response_event=asyncio.Event(),
            )

            self._waiters[request_id] = waiter

            # Add to conversation index
            if conversation_id not in self._conversation_requests:
                self._conversation_requests[conversation_id] = []
            self._conversation_requests[conversation_id].append(request_id)

            self._total_registered += 1

            logger.debug(
                f"[SessionRegistry] Registered HITL waiter: "
                f"request_id={request_id}, conversation_id={conversation_id}, "
                f"type={hitl_type}"
            )

            return waiter

    async def unregister_waiter(self, request_id: str) -> bool:
        """
        Unregister a waiter (called when HITL is resolved or cancelled).

        Args:
            request_id: The HITL request to unregister

        Returns:
            True if waiter was found and removed, False otherwise
        """
        async with self._lock:
            waiter = self._waiters.pop(request_id, None)
            if not waiter:
                return False

            # Remove from conversation index
            conv_requests = self._conversation_requests.get(waiter.conversation_id, [])
            if request_id in conv_requests:
                conv_requests.remove(request_id)
                if not conv_requests:
                    del self._conversation_requests[waiter.conversation_id]

            logger.debug(f"[SessionRegistry] Unregistered HITL waiter: {request_id}")
            return True

    async def deliver_response(
        self,
        request_id: str,
        response_data: dict[str, Any],
    ) -> bool:
        """
        Deliver an HITL response to a waiting session.

        This is the fast path - if the session is on this Worker,
        the response is delivered directly in-memory.

        Args:
            request_id: The HITL request ID
            response_data: The user's response data

        Returns:
            True if response was delivered, False if waiter not found
        """
        async with self._lock:
            waiter = self._waiters.get(request_id)
            if not waiter:
                logger.debug(f"[SessionRegistry] No waiter found for request: {request_id}")
                return False

            # Store response data
            waiter.response_data = response_data

            # Signal the event (for wait_for_response callers)
            if waiter.response_event:
                waiter.response_event.set()

        # Call callback outside lock (it may be slow)
        if waiter.response_callback:
            try:
                await waiter.response_callback(response_data)
            except Exception as e:
                logger.error(f"[SessionRegistry] Response callback error for {request_id}: {e}")

        self._total_delivered += 1

        logger.info(
            f"[SessionRegistry] Delivered HITL response in-memory: "
            f"request_id={request_id}, type={waiter.hitl_type}"
        )

        return True

    async def wait_for_response(
        self,
        request_id: str,
        timeout: float = 300.0,
    ) -> dict[str, Any] | None:
        """
        Wait for an HITL response with timeout.

        This blocks until the response arrives or timeout occurs.
        Use this when you need synchronous-style waiting.

        Args:
            request_id: The HITL request to wait for
            timeout: Maximum seconds to wait

        Returns:
            Response data if received, None if timeout or not found
        """
        waiter = self._waiters.get(request_id)
        if not waiter or not waiter.response_event:
            return None

        try:
            await asyncio.wait_for(waiter.response_event.wait(), timeout=timeout)
            return waiter.response_data
        except TimeoutError:
            self._total_timeouts += 1
            logger.warning(f"[SessionRegistry] Wait timeout for request: {request_id}")
            return None

    def has_waiter(self, request_id: str) -> bool:
        """Check if a waiter exists for the given request."""
        return request_id in self._waiters

    def get_waiter(self, request_id: str) -> HITLWaiter | None:
        """Get waiter by request ID (non-blocking)."""
        return self._waiters.get(request_id)

    def get_waiters_by_conversation(self, conversation_id: str) -> list[HITLWaiter]:
        """Get all waiters for a conversation."""
        request_ids = self._conversation_requests.get(conversation_id, [])
        return [self._waiters[rid] for rid in request_ids if rid in self._waiters]

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        return {
            "active_waiters": len(self._waiters),
            "active_conversations": len(self._conversation_requests),
            "total_registered": self._total_registered,
            "total_delivered": self._total_delivered,
            "total_timeouts": self._total_timeouts,
            "delivery_rate": (
                self._total_delivered / self._total_registered
                if self._total_registered > 0
                else 0.0
            ),
        }

    async def cleanup_expired(self, max_age_seconds: float = 3600.0) -> int:
        """
        Clean up waiters that have been waiting too long.

        This prevents memory leaks from abandoned HITL requests.

        Args:
            max_age_seconds: Maximum age before cleanup (default 1 hour)

        Returns:
            Number of waiters cleaned up
        """
        now = datetime.now(UTC)
        expired_ids = []

        async with self._lock:
            for request_id, waiter in self._waiters.items():
                age = (now - waiter.registered_at).total_seconds()
                if age > max_age_seconds:
                    expired_ids.append(request_id)

        # Unregister outside main lock
        cleaned = 0
        for request_id in expired_ids:
            if await self.unregister_waiter(request_id):
                cleaned += 1

        if cleaned > 0:
            logger.info(f"[SessionRegistry] Cleaned up {cleaned} expired waiters")

        return cleaned


# Global singleton for the current Worker process
_registry_instance: AgentSessionRegistry | None = None


def get_session_registry() -> AgentSessionRegistry:
    """Get the global AgentSessionRegistry instance."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = AgentSessionRegistry()
    return _registry_instance


def reset_session_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry_instance
    _registry_instance = None
