"""Background dispatcher that drains blackboard outbox rows to Redis.

Companion to ``SqlBlackboardOutboxRepository``. Polls pending rows,
publishes them via the workspace event bus, and marks them dispatched.
Failures bump ``attempt_count`` (already incremented at claim time) and
schedule exponential backoff; rows past ``max_attempts`` move to
``dead_letter`` and surface in ops dashboards.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, cast

import redis.asyncio as redis_async

from src.domain.events.types import AgentEventType
from src.domain.ports.services.blackboard_event_port import BlackboardEventPort
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceBlackboardOutboxModel
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_outbox_repository import (
    SqlBlackboardOutboxRepository,
)

logger = logging.getLogger(__name__)


BlackboardOutboxSessionFactory = Callable[[], AbstractAsyncContextManager[Any]]
BlackboardOutboxPublisher = Callable[[WorkspaceBlackboardOutboxModel], Awaitable[None]]


class BlackboardOutboxDispatcher:
    """Poll the blackboard outbox and publish pending events to Redis."""

    def __init__(
        self,
        *,
        session_factory: BlackboardOutboxSessionFactory,
        redis_client: redis_async.Redis | None,
        poll_interval_seconds: float = 0.5,
        batch_size: int = 32,
        publisher: BlackboardOutboxPublisher | None = None,
        event_port: BlackboardEventPort | None = None,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._redis_client = redis_client
        self._poll_interval_seconds = max(0.05, poll_interval_seconds)
        self._batch_size = max(1, batch_size)
        self._event_port = event_port
        self._publisher = publisher or self._default_publisher
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def _is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self.is_running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="blackboard-outbox-dispatcher")
        logger.info("blackboard outbox dispatcher started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            _ = self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("blackboard outbox dispatcher stopped")

    async def run_once(self) -> int:
        """Claim one batch and process synchronously; returns processed count."""
        async with self._session_factory() as session:
            repo = SqlBlackboardOutboxRepository(session)
            items = await repo.claim_due(limit=self._batch_size)
            # Snapshot fields we need before commit so we don't touch detached
            # ORM instances after the session closes on commit.
            snapshots: list[tuple[str, WorkspaceBlackboardOutboxModel]] = [
                (item.id, item) for item in items
            ]
            await session.commit()

        if not snapshots:
            return 0

        for outbox_id, snapshot in snapshots:
            try:
                await self._publisher(snapshot)
            except Exception as exc:
                logger.warning(
                    "blackboard outbox publish failed",
                    extra={
                        "outbox_id": outbox_id,
                        "workspace_id": snapshot.workspace_id,
                        "event_type": snapshot.event_type,
                        "error": str(exc),
                    },
                )
                async with self._session_factory() as session:
                    repo = SqlBlackboardOutboxRepository(session)
                    _ = await repo.mark_failed(outbox_id, str(exc))
                    await session.commit()
                continue

            async with self._session_factory() as session:
                repo = SqlBlackboardOutboxRepository(session)
                _ = await repo.mark_dispatched(outbox_id)
                await session.commit()

        return len(snapshots)

    async def _poll_loop(self) -> None:
        try:
            while self._is_running():
                processed = 0
                try:
                    processed = await self.run_once()
                except asyncio.CancelledError:
                    if not self._is_running():
                        break
                    logger.warning("blackboard outbox dispatcher cancelled mid-batch")
                except Exception:
                    logger.exception("blackboard outbox dispatcher poll iteration failed")
                    processed = 0
                # If we drained a full batch, poll again immediately.
                if processed >= self._batch_size:
                    continue
                try:
                    await asyncio.sleep(self._poll_interval_seconds)
                except asyncio.CancelledError:
                    break
        finally:
            self._running = False

    async def _default_publisher(self, item: WorkspaceBlackboardOutboxModel) -> None:
        try:
            event_type = AgentEventType(item.event_type)
        except ValueError as exc:
            raise RuntimeError(
                f"unknown blackboard event_type={item.event_type!r}"
            ) from exc

        payload = dict(item.payload_json or {})
        metadata = dict(item.metadata_json or {})
        correlation_id = item.correlation_id or item.workspace_id

        # Preferred path: a configured event port encapsulates the transport.
        if self._event_port is not None:
            await self._event_port.publish(
                workspace_id=item.workspace_id,
                event_type=event_type,
                payload=payload,
                metadata=metadata,
                correlation_id=correlation_id,
            )
            return

        if self._redis_client is None:
            raise RuntimeError("redis client unavailable for blackboard outbox dispatcher")
        # Deferred import to avoid a circular import between the primary-web
        # routers package (which wires this dispatcher at startup) and this
        # module's import-time dependencies.
        from src.infrastructure.adapters.primary.web.routers.workspace_events import (
            publish_workspace_event,
        )

        await publish_workspace_event(
            cast(Any, self._redis_client),
            workspace_id=item.workspace_id,
            event_type=event_type,
            payload=payload,
            metadata=metadata,
            correlation_id=correlation_id,
        )


__all__ = ["BlackboardOutboxDispatcher"]
