"""Retired platform Blackboard outbox dispatcher compatibility surface."""

from __future__ import annotations

from typing import Any

BlackboardOutboxPublisher = Any


class BlackboardOutboxDispatcher:
    """Inactive shell; Avernet Core owns Blackboard events and replay."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    @property
    def is_running(self) -> bool:
        return False

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_once(self) -> int:
        return 0


__all__ = ["BlackboardOutboxDispatcher", "BlackboardOutboxPublisher"]
