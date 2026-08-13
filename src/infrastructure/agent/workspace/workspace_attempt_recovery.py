"""Retired platform Workspace attempt recovery compatibility surface."""

from __future__ import annotations

from collections.abc import Callable


class WorkspaceAttemptRecoveryService:
    """Inactive shell retained for imports during the Core cutover."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    @property
    def is_running(self) -> bool:
        return False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def startup_sweep(self) -> int:
        return 0

    async def periodic_sweep(self) -> int:
        return 0

    async def workspace_sweep(self, workspace_id: str) -> int:
        del workspace_id
        return 0


def workspace_attempt_recovery_factory(*args: object, **kwargs: object) -> Callable[[], None]:
    del args, kwargs
    return lambda: None


__all__ = ["WorkspaceAttemptRecoveryService", "workspace_attempt_recovery_factory"]
