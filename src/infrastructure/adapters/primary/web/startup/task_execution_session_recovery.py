"""Compatibility hooks for retired platform task-session recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as redis

    from src.configuration.di_container import DIContainer


async def initialize_task_execution_session_recovery(
    *,
    container: DIContainer,
    redis_client: redis.Redis | None,
) -> None:
    """Do not compose a legacy recovery worker under Core authority."""
    del container, redis_client
    return None


async def shutdown_task_execution_session_recovery() -> None:
    """No-op because the retired worker can never be started."""
    return None


__all__ = [
    "initialize_task_execution_session_recovery",
    "shutdown_task_execution_session_recovery",
]
