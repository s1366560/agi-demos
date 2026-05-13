"""Port for the workspace-blackboard event channel.

Implementations decide *how* events reach subscribers:
- ``UnifiedBusBlackboardEventPort`` reuses the existing routing-key based
  pub/sub on top of Redis Streams (legacy behaviour).
- ``RedisStreamBlackboardEventPort`` writes to a dedicated per-workspace
  stream ``bb:events:{workspace_id}`` and supports replay via XRANGE so
  late-joining subscribers (or WS reconnects with ``Last-Event-ID``) do
  not lose events.

Selection is environment-driven (``BLACKBOARD_EVENT_TRANSPORT``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.domain.events.types import AgentEventType


class BlackboardEventPort(ABC):
    """Workspace blackboard event channel."""

    @abstractmethod
    async def publish(
        self,
        *,
        workspace_id: str,
        event_type: AgentEventType,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str | None:
        """Publish an event. Returns the assigned stream id when available."""

    @abstractmethod
    async def stream_since(
        self,
        *,
        workspace_id: str,
        last_id: str = "0",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return events for ``workspace_id`` strictly newer than ``last_id``.

        Order is oldest → newest. Each entry contains at minimum:
        ``{"id": str, "event_type": str, "payload": dict, "metadata": dict}``.

        Implementations that do not support replay (pub/sub-only transport)
        MUST return an empty list rather than raising.
        """


__all__ = ["BlackboardEventPort"]
