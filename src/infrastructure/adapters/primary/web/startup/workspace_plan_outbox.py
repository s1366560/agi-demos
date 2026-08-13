"""Compatibility hooks for the retired legacy Workspace Plan V2 outbox worker."""

from __future__ import annotations

from typing import Any


async def initialize_workspace_plan_outbox_worker(*, redis_client: Any = None) -> None:  # noqa: ANN401
    """Keep the retired startup hook fail-closed and inactive."""
    _ = redis_client
    return None


async def shutdown_workspace_plan_outbox_worker() -> None:
    """No-op because Avernet Workspace Core owns plan progression."""
    return None


__all__ = [
    "initialize_workspace_plan_outbox_worker",
    "shutdown_workspace_plan_outbox_worker",
]
