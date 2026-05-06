"""Redis-backed FrictionLedger.

Stores friction signals as JSON entries in a Redis Stream per project. Streams
give us:

- O(log N) append + range queries by score (timestamp)
- Built-in TTL via ``XADD MAXLEN ~``
- Replay from arbitrary offsets without locking

Stream key format: ``memstack:friction:{project_id}``

Retention: capped at ``max_len`` entries (approximate trim) and signals older
than ``ttl_days`` are filtered out at query time. Adjust both via constructor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, override

from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.ports.repositories.friction_ledger import FrictionLedger

if TYPE_CHECKING:
    from redis.asyncio import Redis


KEY_PREFIX = "memstack:friction:"


class RedisFrictionLedger(FrictionLedger):
    """Friction ledger persisted to Redis Streams (one stream per project)."""

    def __init__(
        self,
        redis: Redis,
        *,
        max_len: int = 50_000,
        ttl_days: int = 30,
    ) -> None:
        self._redis = redis
        self._max_len = max_len
        self._ttl = timedelta(days=ttl_days)

    @staticmethod
    def _key(project_id: str) -> str:
        return f"{KEY_PREFIX}{project_id}"

    @override
    async def append(self, signal: FrictionSignal) -> None:
        payload: dict[str, Any] = {
            "task_id": signal.task_id,
            "kind": signal.kind.value,
            "source_lane": signal.source_lane or "",
            "target_lane": signal.target_lane or "",
            "metadata": json.dumps(signal.metadata, default=str),
            "observed_at": signal.observed_at.isoformat(),
        }
        # redis-py types are invariant on the field dict; cast to satisfy pyright
        # while preserving runtime behaviour (all values are str-encodable).
        await self._redis.xadd(
            self._key(signal.project_id),
            payload,  # pyright: ignore[reportArgumentType]
            maxlen=self._max_len,
            approximate=True,
        )

    @override
    async def query_window(
        self,
        project_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[FrictionSignal]:
        now = datetime.now(UTC)
        oldest_allowed = now - self._ttl
        effective_since = max(since, oldest_allowed) if since else oldest_allowed
        effective_until = until or now

        raw: list[tuple[bytes, dict[bytes, bytes]]] = await self._redis.xrange(  # type: ignore[no-untyped-call]
            self._key(project_id), min="-", max="+", count=limit
        )

        out: list[FrictionSignal] = []
        for _entry_id, fields in raw:
            decoded = {
                k.decode() if isinstance(k, bytes) else k: (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in fields.items()
            }
            try:
                observed_at = datetime.fromisoformat(decoded["observed_at"])
            except (KeyError, ValueError):
                continue
            if observed_at < effective_since or observed_at > effective_until:
                continue
            try:
                kind = FrictionKind(decoded["kind"])
            except (KeyError, ValueError):
                continue
            metadata_raw = decoded.get("metadata", "{}")
            try:
                metadata = json.loads(metadata_raw) if metadata_raw else {}
            except json.JSONDecodeError:
                metadata = {}
            source_lane = decoded.get("source_lane") or None
            target_lane = decoded.get("target_lane") or None
            out.append(
                FrictionSignal(
                    project_id=project_id,
                    task_id=decoded.get("task_id", ""),
                    kind=kind,
                    source_lane=source_lane,
                    target_lane=target_lane,
                    metadata=metadata,
                    observed_at=observed_at,
                )
            )
        out.sort(key=lambda s: s.observed_at)
        return out
