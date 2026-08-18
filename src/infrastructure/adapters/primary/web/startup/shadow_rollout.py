"""Durable platform-plugin shadow rollout evidence writer."""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.configuration.config import get_settings
from src.infrastructure.plugins.shadow_rollout import ShadowRolloutWorker

logger = logging.getLogger(__name__)
_worker: ShadowRolloutWorker | None = None


def initialize_shadow_rollout_worker(
    session_factory: Callable[[], object],
) -> ShadowRolloutWorker | None:
    """Start the durable writer only when shadow rollout is enabled."""
    global _worker
    settings = get_settings()
    if not (
        settings.platform_plugin_agent_events_shadow or settings.platform_plugin_agent_tools_shadow
    ):
        return None
    _worker = ShadowRolloutWorker(session_factory)
    _worker.start()
    logger.info("Platform plugin shadow rollout ledger writer started")
    return _worker


async def shutdown_shadow_rollout_worker() -> None:
    """Drain evidence and stop the background writer."""
    global _worker
    worker = _worker
    if worker is None:
        return
    _worker = None
    await worker.stop()
    logger.info("Platform plugin shadow rollout ledger writer stopped")
