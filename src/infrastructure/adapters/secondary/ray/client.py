"""Ray client helpers for Actor-based agent runtime."""

from __future__ import annotations

import asyncio
from typing import Any

import ray

from src.configuration.ray_config import get_ray_settings

_ray_init_lock = asyncio.Lock()


async def init_ray_if_needed() -> None:
    """Initialize Ray runtime if not already initialized."""
    if ray.is_initialized():
        return

    async with _ray_init_lock:
        if ray.is_initialized():
            return

        settings = get_ray_settings()
        ray.init(
            address=settings.ray_address,
            namespace=settings.ray_namespace,
            log_to_driver=settings.ray_log_to_driver,
            ignore_reinit_error=True,
        )


async def await_ray(ref: Any) -> Any:
    """Await a Ray ObjectRef without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ray.get, ref)
