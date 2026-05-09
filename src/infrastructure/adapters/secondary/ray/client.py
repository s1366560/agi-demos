"""Ray client helpers for Actor-based agent runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from functools import partial
from typing import Any

import ray

from src.configuration.ray_config import get_ray_settings
from src.infrastructure.adapters.secondary import ray as ray_pkg

logger = logging.getLogger(__name__)

_ray_init_lock = asyncio.Lock()
_ray_available = False
_ray_failure_cooldown_until = 0.0

_DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0
_DEFAULT_INIT_TIMEOUT_SECONDS = 5.0
_DEFAULT_FAILURE_COOLDOWN_SECONDS = 30.0


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw is None else _positive_float(raw, default)


def _settings_float(settings: Any, attr_name: str, env_name: str, default: float) -> float:
    value = getattr(settings, attr_name, None)
    if value is not None:
        return _positive_float(value, default)
    return _positive_float_env(env_name, default)


def _ray_connect_timeout_seconds(settings: Any | None = None) -> float:
    if settings is not None:
        return _settings_float(
            settings,
            "ray_connect_timeout",
            "RAY_CONNECT_TIMEOUT",
            _DEFAULT_CONNECT_TIMEOUT_SECONDS,
        )
    return _positive_float_env("RAY_CONNECT_TIMEOUT", _DEFAULT_CONNECT_TIMEOUT_SECONDS)


def _ray_init_timeout_seconds(settings: Any | None = None) -> float:
    if settings is not None:
        return _settings_float(
            settings,
            "ray_init_timeout_seconds",
            "RAY_INIT_TIMEOUT_SECONDS",
            _DEFAULT_INIT_TIMEOUT_SECONDS,
        )
    return _positive_float_env("RAY_INIT_TIMEOUT_SECONDS", _DEFAULT_INIT_TIMEOUT_SECONDS)


def _ray_failure_cooldown_seconds(settings: Any | None = None) -> float:
    if settings is not None:
        return _settings_float(
            settings,
            "ray_failure_cooldown_seconds",
            "RAY_FAILURE_COOLDOWN_SECONDS",
            _DEFAULT_FAILURE_COOLDOWN_SECONDS,
        )
    return _positive_float_env(
        "RAY_FAILURE_COOLDOWN_SECONDS",
        _DEFAULT_FAILURE_COOLDOWN_SECONDS,
    )


def _cooldown_remaining_seconds(now: float | None = None) -> float:
    now_val = time.monotonic() if now is None else now
    return max(0.0, _ray_failure_cooldown_until - now_val)


def _set_ray_failure_cooldown(settings: Any | None = None) -> float:
    global _ray_failure_cooldown_until
    cooldown = _ray_failure_cooldown_seconds(settings)
    _ray_failure_cooldown_until = time.monotonic() + cooldown
    return cooldown


def _ray_log(
    level: int,
    event: str,
    *,
    address: str,
    namespace: str,
    elapsed_ms: float | None = None,
    cooldown_seconds: float | None = None,
    error: str | None = None,
) -> None:
    logger.log(
        level,
        event,
        extra={
            "event": event,
            "ray_address": address,
            "ray_namespace": namespace,
            "elapsed_ms": round(elapsed_ms, 2) if elapsed_ms is not None else None,
            "cooldown_seconds": round(cooldown_seconds, 2)
            if cooldown_seconds is not None
            else None,
            "error": error,
        },
    )


def _module_init_failed() -> bool:
    """Return the current package-level Ray init failure marker.

    The agent-actor worker resets ``src.infrastructure.adapters.secondary.ray``
    between retry attempts. Read the value dynamically so a transient startup
    failure does not freeze this client module in an unavailable state.
    """
    return bool(getattr(ray_pkg, "_ray_init_failed", False))


def _init_ray_blocking(
    *,
    address: str,
    namespace: str,
    log_to_driver: bool,
) -> None:
    ray.init(
        address=address,
        namespace=namespace,
        log_to_driver=log_to_driver,
        ignore_reinit_error=True,
    )


def _ray_is_initialized() -> bool:
    global _ray_available
    if not ray.is_initialized():
        return False
    _ray_available = True
    return True


def _log_cooldown_skip(settings: Any) -> bool:
    cooldown_remaining = _cooldown_remaining_seconds()
    if cooldown_remaining <= 0:
        return False
    _ray_log(
        logging.INFO,
        "ray.init.cooldown_skip",
        address=settings.ray_address,
        namespace=settings.ray_namespace,
        cooldown_seconds=cooldown_remaining,
    )
    return True


async def _ray_cluster_reachable(settings: Any, *, start: float) -> bool:
    global _ray_available
    loop = asyncio.get_running_loop()
    connect_timeout = _ray_connect_timeout_seconds(settings)
    try:
        reachable = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(
                    ray_pkg._check_ray_reachable,
                    settings.ray_address,
                    connect_timeout,
                ),
            ),
            timeout=connect_timeout + 0.5,
        )
    except TimeoutError:
        reachable = False

    if reachable:
        return True

    _ray_available = False
    cooldown = _set_ray_failure_cooldown(settings)
    _ray_log(
        logging.WARNING,
        "ray.init.unreachable",
        address=settings.ray_address,
        namespace=settings.ray_namespace,
        elapsed_ms=(time.perf_counter() - start) * 1000,
        cooldown_seconds=cooldown,
    )
    return False


async def _connect_ray(settings: Any, *, start: float) -> bool:
    global _ray_available
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(
                    _init_ray_blocking,
                    address=settings.ray_address,
                    namespace=settings.ray_namespace,
                    log_to_driver=settings.ray_log_to_driver,
                ),
            ),
            timeout=_ray_init_timeout_seconds(settings),
        )
        _ray_available = True
        _ray_log(
            logging.INFO,
            "ray.init.success",
            address=settings.ray_address,
            namespace=settings.ray_namespace,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )
        return True
    except TimeoutError:
        event = "ray.init.timeout"
        error = None
    except Exception as exc:
        event = "ray.init.failed"
        error = str(exc)

    _ray_available = False
    cooldown = _set_ray_failure_cooldown(settings)
    _ray_log(
        logging.WARNING,
        event,
        address=settings.ray_address,
        namespace=settings.ray_namespace,
        elapsed_ms=(time.perf_counter() - start) * 1000,
        cooldown_seconds=cooldown,
        error=error,
    )
    return False


async def init_ray_if_needed() -> bool:
    """Initialize Ray runtime if not already initialized.

    Returns:
        True if Ray is initialized and available, False otherwise.
    """
    # If module-level init already determined Ray is unreachable, skip
    if _module_init_failed():
        return False

    if _ray_is_initialized():
        return True

    settings = get_ray_settings()
    if _log_cooldown_skip(settings):
        return False

    async with _ray_init_lock:
        available = _ray_is_initialized()

        if not available:
            settings = get_ray_settings()
            if _log_cooldown_skip(settings):
                return False

            start = time.perf_counter()
            _ray_log(
                logging.INFO,
                "ray.init.start",
                address=settings.ray_address,
                namespace=settings.ray_namespace,
            )

            if await _ray_cluster_reachable(settings, start=start):
                available = await _connect_ray(settings, start=start)

        return available


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
