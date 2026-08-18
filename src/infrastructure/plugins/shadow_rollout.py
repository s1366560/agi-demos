"""Bounded durable shadow-rollout evidence pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)
MAX_QUEUED_EVENTS = 10_000
MAX_BATCH_SIZE = 100

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
        PlatformPluginRepository,
    )


def default_repository_factory(session: Any) -> PlatformPluginRepository:  # noqa: ANN401
    """Import lazily to avoid the models-to-agent circular import edge."""
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository import (
        PlatformPluginRepository,
    )

    return PlatformPluginRepository(session)


@dataclass(frozen=True)
class QueuedShadowRolloutEvent:
    """One transport-neutral shadow comparison record."""

    capability: str
    event_name: str
    hook_name: str
    scope_type: str
    scope_id: str
    equal: bool
    legacy_payload: Mapping[str, Any]
    typed_payload: Mapping[str, Any]
    occurred_at: datetime

    def record(self) -> dict[str, Any]:
        """Return the repository persistence payload."""
        return {
            "capability": self.capability,
            "event_name": self.event_name,
            "hook_name": self.hook_name,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "equal": self.equal,
            "legacy_payload": _json_mapping(self.legacy_payload),
            "typed_payload": _json_mapping(self.typed_payload),
            "occurred_at": self.occurred_at,
        }


_queue: asyncio.Queue[QueuedShadowRolloutEvent | None] = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
_queue_lock = threading.Lock()
_dropped_events = 0


def enqueue_shadow_rollout_event(event: QueuedShadowRolloutEvent) -> bool:
    """Enqueue evidence without ever blocking the agent dispatch path."""
    global _dropped_events
    try:
        _queue.put_nowait(event)
        return True
    except asyncio.QueueFull:
        with _queue_lock:
            _dropped_events += 1
        if _dropped_events == 1 or _dropped_events % 1_000 == 0:
            logger.warning(
                "Shadow rollout evidence queue is full; dropped %d events",
                _dropped_events,
            )
        return False


def queued_event_count() -> int:
    """Return the current bounded queue depth for diagnostics."""
    return _queue.qsize()


def dropped_event_count() -> int:
    """Return the number of evidence records dropped under backpressure."""
    return _dropped_events


def reset_shadow_rollout_queue_for_test() -> None:
    """Reset process-local queue diagnostics without touching durable rows."""
    global _dropped_events
    while not _queue.empty():
        try:
            _queue.get_nowait()
            _queue.task_done()
        except asyncio.QueueEmpty:
            break
    with _queue_lock:
        _dropped_events = 0


class ShadowRolloutWorker:
    """Batch-persist shadow evidence with a dedicated DB session."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        repository_factory: Callable[[Any], PlatformPluginRepository] = default_repository_factory,
    ) -> None:
        self._session_factory = session_factory
        self._repository_factory = repository_factory
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        """Return whether the worker currently owns an active task."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start exactly one background writer."""
        if self.running:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="platform-plugin-shadow-rollout")

    async def stop(self) -> None:
        """Drain queued evidence and wait for the writer to exit."""
        task = self._task
        if task is None:
            return
        self._stopping.set()
        await _queue.put(None)
        try:
            await task
        finally:
            self._task = None

    async def _run(self) -> None:
        while True:
            first = await _queue.get()
            _queue.task_done()
            if first is None:
                return
            batch = [first]
            while len(batch) < MAX_BATCH_SIZE:
                try:
                    item = _queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                _queue.task_done()
                if item is None:
                    await self._persist(batch)
                    return
                batch.append(item)
            await self._persist(batch)

    async def _persist(self, batch: Sequence[QueuedShadowRolloutEvent]) -> None:
        if not batch:
            return
        records = [event.record() for event in batch]
        try:
            async with self._session_factory() as session:
                repository = self._repository_factory(session)
                await repository.record_shadow_rollout_events(records)
                await session.commit()
        except Exception:
            logger.exception("Failed to persist %d shadow rollout events", len(batch))
            if self._stopping.is_set():
                _record_dropped_events(len(batch))
                logger.warning(
                    "Dropping %d shadow rollout events during shutdown after persistence failure",
                    len(batch),
                )
                return
            for event in batch:
                enqueue_shadow_rollout_event(event)
            await asyncio.sleep(0.5)


def make_shadow_rollout_event(
    *,
    capability: str,
    event_name: str,
    hook_name: str,
    scope_type: str,
    scope_id: str,
    equal: bool,
    legacy_payload: Mapping[str, Any],
    typed_payload: Mapping[str, Any],
) -> QueuedShadowRolloutEvent:
    """Construct a timestamped queue record."""
    return QueuedShadowRolloutEvent(
        capability=capability,
        event_name=event_name,
        hook_name=hook_name,
        scope_type=scope_type,
        scope_id=scope_id,
        equal=equal,
        legacy_payload=legacy_payload,
        typed_payload=typed_payload,
        occurred_at=datetime.now(UTC),
    )


def event_fingerprint(event: QueuedShadowRolloutEvent) -> str:
    """Return a deterministic diagnostic identity without payload contents."""
    canonical = json.dumps(
        {
            "capability": event.capability,
            "event_name": event.event_name,
            "scope_type": event.scope_type,
            "scope_id": event.scope_id,
            "equal": event.equal,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{event.occurred_at.isoformat()}:{uuid.uuid5(uuid.NAMESPACE_URL, canonical)}"


def _json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: _redacted_json(item) for key, item in value.items()}


def _redacted_json(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, Mapping):
        return {str(key): _redacted_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted_json(item) for item in value]
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "type": type(value).__name__,
        "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
    }


def _record_dropped_events(count: int) -> None:
    global _dropped_events
    with _queue_lock:
        _dropped_events += count
