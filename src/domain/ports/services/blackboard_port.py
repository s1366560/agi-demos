"""Port: blackboard — typed pub/sub channel for artifacts between agents."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class BlackboardEntry:
    plan_id: str
    key: str
    value: Any
    published_by: str
    version: int = 1
    schema_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BlackboardPort(Protocol):
    async def put(self, entry: BlackboardEntry) -> int:
        """Publish an artifact; returns the assigned version."""
        ...

    async def get(self, plan_id: str, key: str) -> BlackboardEntry | None: ...
    async def list(self, plan_id: str) -> list[BlackboardEntry]: ...
    async def subscribe(
        self, plan_id: str, keys: tuple[str, ...] | None = None
    ) -> AsyncIterator[BlackboardEntry]: ...
