"""Active persistence of protocol-v2 publication deadline outcomes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN_V2_DEADLINE_POLL_SECONDS = 1.0
MAX_PLUGIN_V2_DEADLINE_BATCH_SIZE = 1000

SessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PlatformPluginDeadlineReconcilerV2:
    """Refresh overdue publications in fresh, bounded SQL transactions."""

    def __init__(
        self,
        *,
        session_factory: SessionFactoryV2,
        clock: Callable[[], datetime] | None = None,
        batch_size: int = 100,
        poll_interval_seconds: float = DEFAULT_PLUGIN_V2_DEADLINE_POLL_SECONDS,
    ) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= MAX_PLUGIN_V2_DEADLINE_BATCH_SIZE:
            raise ValueError("plugin v2 deadline batch size must be between 1 and 1000")
        if poll_interval_seconds <= 0:
            raise ValueError("plugin v2 deadline poll interval must be positive")
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._batch_size = batch_size
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """Return whether the process-local reconciliation loop is active."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start one process-local loop; repeated calls are idempotent."""
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="platform-plugin-publication-deadlines-v2",
        )

    async def stop(self) -> None:
        """Wake and drain the active loop without abandoning its SQL transaction."""
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        try:
            await task
        finally:
            self._task = None

    async def run_once(self) -> int:
        """Refresh one bounded overdue batch and commit it atomically."""
        async with self._session_factory() as session:
            reconciled = await PlatformPluginRepositoryV2(session).reconcile_publication_deadlines(
                now=self._utc_now(),
                limit=self._batch_size,
            )
            await session.commit()
            return reconciled

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                _ = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Plugin v2 publication deadline reconciliation failed",
                    exc_info=True,
                    extra={"event": "platform_plugin_v2.deadline_reconcile_failed"},
                )
            try:
                _ = await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("plugin v2 deadline clock must include a timezone")
        return now.astimezone(UTC)


__all__ = [
    "DEFAULT_PLUGIN_V2_DEADLINE_POLL_SECONDS",
    "PlatformPluginDeadlineReconcilerV2",
]
