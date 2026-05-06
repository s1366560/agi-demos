"""In-memory implementations of friction-loop ports.

Used by:
- Tests (no Redis / no DB needed).
- Local-dev fallback when Redis is unavailable.

NOT safe for multi-process production.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from typing import override

from src.domain.model.flow.friction_signal import FrictionSignal
from src.domain.model.flow.playbook import Playbook, PlaybookStatus
from src.domain.ports.repositories.friction_ledger import FrictionLedger
from src.domain.ports.repositories.playbook_repository import PlaybookRepository


class InMemoryFrictionLedger(FrictionLedger):
    """Process-local friction ledger backed by a dict of lists."""

    def __init__(self) -> None:
        self._signals: dict[str, list[FrictionSignal]] = defaultdict(list)
        self._lock = asyncio.Lock()

    @override
    async def append(self, signal: FrictionSignal) -> None:
        async with self._lock:
            self._signals[signal.project_id].append(signal)

    @override
    async def query_window(
        self,
        project_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[FrictionSignal]:
        async with self._lock:
            buf = list(self._signals.get(project_id, ()))
        upper = until or datetime.now(UTC)
        out = [s for s in buf if (since is None or s.observed_at >= since) and s.observed_at <= upper]
        out.sort(key=lambda s: s.observed_at)
        return out[:limit]


class InMemoryPlaybookRepository(PlaybookRepository):
    """Process-local playbook store. Upserts by ``id``."""

    def __init__(self) -> None:
        self._store: dict[str, Playbook] = {}
        self._lock = asyncio.Lock()

    @override
    async def save(self, playbook: Playbook) -> Playbook:
        async with self._lock:
            self._store[playbook.id] = playbook
            return playbook

    @override
    async def find_by_id(self, playbook_id: str) -> Playbook | None:
        async with self._lock:
            return self._store.get(playbook_id)

    @override
    async def find_by_project(
        self,
        project_id: str,
        *,
        status: PlaybookStatus | None = None,
        limit: int = 100,
    ) -> list[Playbook]:
        async with self._lock:
            items = [p for p in self._store.values() if p.project_id == project_id]
        if status is not None:
            items = [p for p in items if p.status == status]
        items.sort(key=lambda p: p.created_at, reverse=True)
        return items[:limit]

    @override
    async def record_hit(self, playbook_id: str) -> None:
        async with self._lock:
            existing = self._store.get(playbook_id)
            if existing is None:
                return
            self._store[playbook_id] = replace(
                existing,
                hit_count=existing.hit_count + 1,
                last_used_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
