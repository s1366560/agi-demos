"""Concrete ``BlackboardEventPort`` implementations.

This module owns the two transports that the dispatcher can use:

- ``UnifiedBusBlackboardEventPort`` — delegates to
  ``publish_workspace_event``; preserves M1 behaviour and routing-key
  semantics. Does not implement replay.
- ``RedisStreamBlackboardEventPort`` — XADD to ``bb:events:{workspace_id}``
  with a bounded MAXLEN and XRANGE-based replay.

Factory ``build_blackboard_event_port`` selects an adapter from the
``BLACKBOARD_EVENT_TRANSPORT`` env var (``pubsub`` (default) | ``stream``).
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from src.domain.events.types import AgentEventType
from src.domain.ports.services.blackboard_event_port import BlackboardEventPort

if TYPE_CHECKING:
    import redis.asyncio as redis_async

logger = logging.getLogger(__name__)

_TRANSPORT_ENV = "BLACKBOARD_EVENT_TRANSPORT"
_MAXLEN_ENV = "BLACKBOARD_EVENT_STREAM_MAXLEN"
DEFAULT_STREAM_MAXLEN = 5000


class UnifiedBusBlackboardEventPort(BlackboardEventPort):
    """Legacy adapter that publishes via ``publish_workspace_event``.

    Replay (``stream_since``) is not supported and returns ``[]``.
    """

    def __init__(self, redis_client: redis_async.Redis | None) -> None:
        self._redis = redis_client

    async def publish(
        self,
        *,
        workspace_id: str,
        event_type: AgentEventType,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str | None:
        # Deferred import to avoid a circular import with the primary-web
        # routers package at startup.
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event,
        )

        await publish_workspace_event(
            cast(Any, self._redis),
            workspace_id=workspace_id,
            event_type=event_type,
            payload=payload,
            metadata=metadata or {},
            correlation_id=correlation_id or workspace_id,
        )
        return None

    async def stream_since(
        self,
        *,
        workspace_id: str,
        last_id: str = "0",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        # Pub/sub transport has no built-in replay.
        return []


class RedisStreamBlackboardEventPort(BlackboardEventPort):
    """Dedicated per-workspace Redis Stream transport.

    Stream key: ``bb:events:{workspace_id}``. Each entry stores the event
    payload + metadata as JSON fields, so replay needs only XRANGE.
    """

    STREAM_KEY_PREFIX = "bb:events:"

    def __init__(
        self,
        redis_client: redis_async.Redis | None,
        *,
        maxlen: int = DEFAULT_STREAM_MAXLEN,
    ) -> None:
        self._redis = redis_client
        self._maxlen = max(100, maxlen)

    @classmethod
    def stream_key(cls, workspace_id: str) -> str:
        return f"{cls.STREAM_KEY_PREFIX}{workspace_id}"

    async def publish(
        self,
        *,
        workspace_id: str,
        event_type: AgentEventType,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str | None:
        if self._redis is None:
            logger.error(
                "[BlackboardStream] redis_client is None; event dropped",
                extra={"workspace_id": workspace_id, "event_type": event_type.value},
            )
            return None

        fields = {
            "event_type": event_type.value,
            "payload": json.dumps(payload, default=str),
            "metadata": json.dumps(metadata or {}, default=str),
            "correlation_id": correlation_id or workspace_id,
            "workspace_id": workspace_id,
        }
        try:
            stream_id = await self._redis.xadd(
                self.stream_key(workspace_id),
                cast(Any, fields),
                maxlen=self._maxlen,
                approximate=True,
            )
        except Exception:
            logger.exception(
                "[BlackboardStream] XADD failed",
                extra={"workspace_id": workspace_id, "event_type": event_type.value},
            )
            raise
        if isinstance(stream_id, bytes):
            stream_id = stream_id.decode("utf-8")
        return stream_id

    async def stream_since(
        self,
        *,
        workspace_id: str,
        last_id: str = "0",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if self._redis is None:
            return []
        # XRANGE returns entries strictly newer than ``last_id`` when we use
        # the ``(`` exclusive lower bound. Defaulting to "0" returns the whole
        # stream up to ``limit`` items.
        lower = f"({last_id}" if last_id and last_id != "0" else "-"
        try:
            entries = await self._redis.xrange(
                self.stream_key(workspace_id),
                min=lower,
                max="+",
                count=max(1, limit),
            )
        except Exception:
            logger.exception(
                "[BlackboardStream] XRANGE failed",
                extra={"workspace_id": workspace_id, "last_id": last_id},
            )
            return []

        result: list[dict[str, Any]] = []
        for entry in entries:
            stream_id, fields = entry
            if isinstance(stream_id, bytes):
                stream_id = stream_id.decode("utf-8")
            decoded = _decode_fields(fields)
            result.append(
                {
                    "id": stream_id,
                    "event_type": decoded.get("event_type", ""),
                    "payload": _safe_json_load(decoded.get("payload", "{}")),
                    "metadata": _safe_json_load(decoded.get("metadata", "{}")),
                    "correlation_id": decoded.get("correlation_id", ""),
                    "workspace_id": decoded.get("workspace_id", workspace_id),
                }
            )
        return result


def _decode_fields(fields: dict[str, Any] | list[Any]) -> dict[str, str]:
    """Decode a Redis hash mapping to ``dict[str, str]``."""
    out: dict[str, str] = {}
    if not fields:
        return out
    # fields is either dict.items() or a list of tuples from Redis.
    items: Any = fields.items() if isinstance(fields, dict) else fields  # type: ignore[union-attr]
    for key, value in items:
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        out[str(key)] = str(value)
    return out


def _safe_json_load(raw: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def get_blackboard_event_transport() -> str:
    """Return the configured transport, normalized to lowercase."""
    return (os.environ.get(_TRANSPORT_ENV, "pubsub") or "pubsub").strip().lower()


def _stream_maxlen() -> int:
    raw = os.environ.get(_MAXLEN_ENV)
    if raw is None:
        return DEFAULT_STREAM_MAXLEN
    try:
        value = int(raw.strip())
    except ValueError:
        return DEFAULT_STREAM_MAXLEN
    return value if value > 0 else DEFAULT_STREAM_MAXLEN


def build_blackboard_event_port(
    redis_client: redis_async.Redis | None,
) -> BlackboardEventPort:
    """Construct the configured ``BlackboardEventPort``.

    Falls back to ``UnifiedBusBlackboardEventPort`` for unknown values to
    preserve current behaviour.
    """
    transport = get_blackboard_event_transport()
    if transport == "stream":
        return RedisStreamBlackboardEventPort(redis_client, maxlen=_stream_maxlen())
    return UnifiedBusBlackboardEventPort(redis_client)


__all__ = [
    "DEFAULT_STREAM_MAXLEN",
    "RedisStreamBlackboardEventPort",
    "UnifiedBusBlackboardEventPort",
    "build_blackboard_event_port",
    "get_blackboard_event_transport",
]
