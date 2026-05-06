"""In-memory ExecutionLeaseRepository — for tests and local fallback.

NOT safe for multi-process production. Use ``RedisExecutionLeaseRepository``
for any deployment with > 1 worker process.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import override

from src.domain.model.recovery.lease import ExecutionLease
from src.domain.ports.repositories.execution_lease_repository import (
    ExecutionLeaseRepository,
)


class InMemoryExecutionLeaseRepository(ExecutionLeaseRepository):
    """Process-local lease store keyed by (project_id, task_id)."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, ExecutionLease]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    @override
    async def get(self, *, project_id: str, task_id: str) -> ExecutionLease | None:
        async with self._lock:
            return self._store.get(project_id, {}).get(task_id)

    @override
    async def upsert(self, *, project_id: str, lease: ExecutionLease) -> None:
        async with self._lock:
            self._store[project_id][lease.task_id] = lease

    @override
    async def release(self, *, project_id: str, task_id: str) -> None:
        async with self._lock:
            self._store.get(project_id, {}).pop(task_id, None)

    @override
    async def list_running(self, *, project_id: str) -> list[ExecutionLease]:
        async with self._lock:
            return list(self._store.get(project_id, {}).values())
