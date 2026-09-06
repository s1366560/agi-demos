"""Recover committed market requests and receipts outside HTTP admission."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.startup.http_route_publication_v2 import (
    HttpRoutePublicationCoordinatorV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.plugins.v2.builtin_http_routes import BuiltinRouteGraphV2
from src.infrastructure.plugins.v2.lifecycle_tasks import OwnedLifecycleTaskV2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

from .marketplace_publication_receipt_v2 import persist_marketplace_receipt_v2
from .marketplace_requested_recovery_v2 import recover_live_requested_root_v2

logger = logging.getLogger(__name__)


class MarketplaceReceiptRecoveryV2:
    """Resume exact requests or retry retained outcomes using fresh SQL sessions."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        *,
        host: PlatformPluginRuntimeHostV2,
        coordinator: HttpRoutePublicationCoordinatorV2,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        policy: PlatformPluginPublicationPolicyV2,
        poll_interval_seconds: float = 5.0,
        trusted_public_keys: tuple[str, ...] = (),
        allowed_registries: frozenset[str] = frozenset(),
        on_route_commit: Callable[[BuiltinRouteGraphV2], None] | None = None,
    ) -> None:
        if not math.isfinite(poll_interval_seconds) or poll_interval_seconds <= 0:
            raise ValueError("receipt recovery interval must be finite and positive")
        self._host = host
        self._coordinator = coordinator
        self._session_factory = session_factory
        self._policy = policy
        self._trusted_public_keys = tuple(trusted_public_keys)
        self._allowed_registries = frozenset(allowed_registries)
        self._on_route_commit = on_route_commit
        self._interval = poll_interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._stop_task: OwnedLifecycleTaskV2 | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start one loop, independently of data-plane generation admission."""
        if self.is_running:
            return
        self._stop_event = asyncio.Event()
        self._stop_task = None
        self._task = asyncio.create_task(self._run(), name="marketplace-receipt-recovery-v2")

    async def stop(self) -> None:
        """Wake the loop and drain any owned persistence through waiter cancellation."""
        task = self._task
        if task is None:
            return
        self._stop_event.set()
        if self._stop_task is None:

            async def drain() -> None:
                try:
                    await asyncio.shield(task)
                finally:
                    if self._task is task:
                        self._task = None

            self._stop_task = OwnedLifecycleTaskV2(drain, name="marketplace-receipt-recovery-stop")
        await self._stop_task.wait()

    async def run_once(self) -> bool:
        """Recover a retained receipt or apply the exact committed unapplied request."""
        if self._host.pending_receipt is None:
            return await recover_live_requested_root_v2(
                coordinator=self._coordinator,
                session_factory=self._session_factory,
                policy=self._policy,
                trusted_public_keys=self._trusted_public_keys,
                allowed_registries=self._allowed_registries,
                on_route_commit=self._on_route_commit,
            )
        try:
            _ = await self._coordinator.retry_pending_receipt(
                lambda publication: persist_marketplace_receipt_v2(
                    self._session_factory,
                    publication,
                    policy=self._policy,
                )
            )
        except RuntimeV2Error as error:
            if error.code == "route_receipt_unavailable":
                # The foreground publication may have completed while we waited for its lock.
                return False
            raise
        return True

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                _ = await self.run_once()
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
                logger.warning(
                    "Marketplace recovery attempt cancelled; retained authority is unchanged"
                )
            except Exception as error:
                logger.warning(
                    "Marketplace recovery deferred (%s)",
                    type(error).__name__,
                )
            try:
                _ = await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except TimeoutError:
                continue
