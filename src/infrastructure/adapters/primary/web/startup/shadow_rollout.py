"""Durable platform-plugin shadow rollout evidence writer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.configuration.config import get_settings
from src.infrastructure.plugins.shadow_rollout import ShadowRolloutWorker

logger = logging.getLogger(__name__)
_worker: ShadowRolloutWorker | None = None


def initialize_shadow_rollout_worker(
    session_factory: Callable[[], Any],
) -> ShadowRolloutWorker | None:
    """Start the durable writer only when shadow rollout is enabled."""
    global _worker
    settings = get_settings()
    if not (
        settings.platform_plugin_agent_events_shadow
        or settings.platform_plugin_agent_tools_shadow
        or settings.platform_plugin_llm_shadow
        or settings.platform_plugin_http_route_shadow
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


async def record_initial_http_route_inventory_shadow(
    session_factory: Callable[[], Any],
) -> bool:
    """Record one startup comparison of registry and desired route inventory."""
    settings = get_settings()
    if not settings.platform_plugin_http_route_shadow:
        return False
    from src.infrastructure.adapters.secondary.persistence.platform_plugin_governance_repository import (
        PlatformPluginGovernanceRepository,
    )
    from src.infrastructure.agent.plugins.registry import get_plugin_registry
    from src.infrastructure.plugins.http_route_rollout import (
        record_http_route_inventory_shadow,
    )

    async with session_factory() as session:
        rows = await PlatformPluginGovernanceRepository(session).list_http_routes()
    recorded = record_http_route_inventory_shadow(
        registry_routes=get_plugin_registry().list_http_routes(),
        desired_rows=rows,
        settings=settings,
    )
    if recorded:
        logger.info("Recorded platform plugin HTTP route inventory shadow evidence")
    return recorded
