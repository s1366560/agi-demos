"""Run-scoped cancellation delivered to the executing task on every substrate."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


class CancellationSignalStore(Protocol):
    async def get(self, name: str) -> object: ...


@dataclass(frozen=True, kw_only=True)
class RunCancellationIdentity:
    tenant_id: str
    project_id: str
    conversation_id: str
    run_id: str

    @property
    def key(self) -> str:
        return f"agent:run-cancellation:{self.run_id}"

    def payload(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


async def cancellation_requested(
    store: CancellationSignalStore, identity: RunCancellationIdentity
) -> bool:
    value = await store.get(identity.key)
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return False
    return value == identity.payload()


async def watch_run_cancellation(
    store: CancellationSignalStore,
    identity: RunCancellationIdentity,
    execution: asyncio.Task[object],
) -> None:
    """Cancel this exact execution, including a blocked model/tool await.

    The signal is retained for queued admission and process retries. This watcher never
    addresses a conversation-wide queue or consumes another worker's control message.
    """
    store_unavailable = False
    while not execution.done():
        try:
            requested = await cancellation_requested(store, identity)
            store_unavailable = False
        except Exception:
            if not store_unavailable:
                logger.warning("Run cancellation store unavailable; retrying")
                store_unavailable = True
            await asyncio.sleep(0.1)
            continue
        if requested:
            _ = execution.cancel()
            return
        await asyncio.sleep(0.1)


async def start_run_cancellation_monitor(
    store: CancellationSignalStore, identity: RunCancellationIdentity
) -> asyncio.Task[None]:
    if await cancellation_requested(store, identity):
        raise asyncio.CancelledError
    execution = asyncio.current_task()
    if execution is None:
        raise RuntimeError("Run cancellation requires an executing task")
    return asyncio.create_task(watch_run_cancellation(store, identity, execution))
