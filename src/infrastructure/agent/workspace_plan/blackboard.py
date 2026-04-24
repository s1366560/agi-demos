"""M7 — in-memory :class:`BlackboardPort` with asyncio-backed subscriptions.

Purpose: give subagents a typed pub/sub channel for artifact exchange that
does NOT rely on free-form ``@mention`` routing or ``metadata`` dict magic.

Usage from a tool:

    await blackboard.put(BlackboardEntry(
        plan_id=..., key="architecture.md", value=md_text, published_by=agent_id
    ))

    async for entry in blackboard.subscribe(plan_id, keys=("architecture.md",)):
        ...

Replace with a Redis Stream-backed implementation in production; the
:class:`BlackboardPort` protocol is the stable surface.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import override

from src.domain.ports.services.blackboard_port import BlackboardEntry, BlackboardPort


class InMemoryBlackboard(BlackboardPort):
    def __init__(self) -> None:
        super().__init__()
        # plan_id -> key -> latest entry
        self._store: dict[str, dict[str, BlackboardEntry]] = {}
        self._version_seq: dict[str, dict[str, int]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[BlackboardEntry]]] = {}
        self._lock = asyncio.Lock()

    @override
    async def put(self, entry: BlackboardEntry) -> int:
        async with self._lock:
            plan_bucket = self._store.setdefault(entry.plan_id, {})
            seq_bucket = self._version_seq.setdefault(entry.plan_id, {})
            next_version = seq_bucket.get(entry.key, 0) + 1
            stored = replace(entry, version=next_version)
            plan_bucket[entry.key] = stored
            seq_bucket[entry.key] = next_version
            subs = list(self._subscribers.get(entry.plan_id, ()))
        for q in subs:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(stored)
        return next_version

    @override
    async def get(self, plan_id: str, key: str) -> BlackboardEntry | None:
        return self._store.get(plan_id, {}).get(key)

    @override
    async def list(self, plan_id: str) -> list[BlackboardEntry]:
        return list(self._store.get(plan_id, {}).values())

    @override
    async def subscribe(
        self, plan_id: str, keys: tuple[str, ...] | None = None
    ) -> AsyncIterator[BlackboardEntry]:
        queue: asyncio.Queue[BlackboardEntry] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.setdefault(plan_id, []).append(queue)
        try:
            while True:
                entry = await queue.get()
                if keys is None or entry.key in keys:
                    yield entry
        finally:
            async with self._lock:
                subs = self._subscribers.get(plan_id, [])
                if queue in subs:
                    subs.remove(queue)
