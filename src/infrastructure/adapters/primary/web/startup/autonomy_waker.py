"""Compatibility startup hooks for the retired Workspace autonomy waker."""

from __future__ import annotations


async def initialize_autonomy_idle_waker() -> None:
    """Do not start a platform worker for Avernet-owned Workspace tasks."""
    return None


async def shutdown_autonomy_idle_waker() -> None:
    """No-op because the retired worker can never be started."""
    return None


__all__ = ["initialize_autonomy_idle_waker", "shutdown_autonomy_idle_waker"]
