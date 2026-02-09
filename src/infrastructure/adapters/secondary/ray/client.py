"""Ray client helpers for Actor-based agent runtime."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import ray

from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary.ray import _ray_init_failed

logger = logging.getLogger(__name__)

_ray_init_lock = asyncio.Lock()
_ray_available = False


async def init_ray_if_needed() -> bool:
    """Initialize Ray runtime if not already initialized.

    Returns:
        True if Ray is initialized and available, False otherwise.
    """
    global _ray_available

    # If module-level init already determined Ray is unreachable, skip
    if _ray_init_failed:
        return False

    if ray.is_initialized():
        _ray_available = True
        return True

    async with _ray_init_lock:
        if ray.is_initialized():
            _ray_available = True
            return True

        settings = get_ray_settings()

        # TCP pre-check to avoid hanging on ray.init()
        from src.infrastructure.adapters.secondary.ray import _check_ray_reachable
        reachable = await asyncio.get_running_loop().run_in_executor(
            None, _check_ray_reachable, settings.ray_address, 3
        )
        if not reachable:
            _ray_available = False
            logger.warning(
                "[Ray] Cluster at %s is unreachable (TCP check). "
                "Agent chat will use local in-process execution.",
                settings.ray_address,
            )
            return False

        try:
            ray.init(
                address=settings.ray_address,
                namespace=settings.ray_namespace,
                log_to_driver=settings.ray_log_to_driver,
                ignore_reinit_error=True,
                allow_multiple=True,
            )
            _ray_available = True
            logger.info("[Ray] Connected to Ray cluster at %s", settings.ray_address)
            return True
        except Exception as e:
            _ray_available = False
            logger.warning(
                "[Ray] Failed to connect to Ray cluster at %s: %s. "
                "Agent chat will use local in-process execution.",
                settings.ray_address,
                e,
            )
            return False


def is_ray_available() -> bool:
    """Check if Ray has been successfully initialized."""
    return _ray_available and ray.is_initialized()


def mark_ray_unavailable() -> None:
    """Mark Ray as unavailable after a connection failure at runtime."""
    global _ray_available
    _ray_available = False
    logger.warning("[Ray] Marked as unavailable due to runtime connection failure")


async def await_ray(ref: Any) -> Any:
    """Await a Ray ObjectRef without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ray.get, ref)
