"""Retired platform plan-outbox worker compatibility surface."""

from __future__ import annotations

from typing import Any

WorkspacePlanOutboxHandler = Any


class WorkspacePlanOutboxWorker:
    """Inactive shell; Avernet Core owns Workspace event delivery."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    @property
    def worker_id(self) -> str:
        return "retired-workspace-plan-outbox"

    @property
    def is_running(self) -> bool:
        return False

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_once(self) -> int:
        return 0


__all__ = ["WorkspacePlanOutboxHandler", "WorkspacePlanOutboxWorker"]
