"""Interrupt model I/O without cancelling the owning SubAgent operation."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import Any

from src.domain.events.agent_events import AgentDomainEvent

ControlPoll = Callable[[], Awaitable[None]]


class ModelStepInterruptedV2(Exception):
    """The old decision is discarded; its owner decides whether to restart or stop."""

    def __init__(self, events: list[AgentDomainEvent | dict[str, Any]], *, restart: bool) -> None:
        super().__init__("Model step interrupted by control")
        self.events = events
        self.restart = restart


async def await_model_control_v2[T](work: Awaitable[T], poll: ControlPoll) -> T:
    """Poll while model I/O is blocked, and unwind that I/O before returning control.

    The task is operation-owned, never detached. Caller cancellation still propagates
    as CancelledError, whereas steering raises ModelStepInterruptedV2.
    """
    task = asyncio.ensure_future(work)
    try:
        await poll()
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.1)
            await poll()
            if done:
                return task.result()
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


async def model_stream_control_v2[T](
    stream: AsyncIterator[T], poll: ControlPoll
) -> AsyncIterator[T]:
    """Keep every model read/close in one task, including its ContextVar scopes.

    The producer waits for consumer acknowledgement before reading again. It cannot
    run ahead into another model decision or leave an unowned stream on steering.
    """
    queue: asyncio.Queue[tuple[bool, T | None, Exception | None]] = asyncio.Queue(maxsize=1)
    advance = asyncio.Event()
    loop = asyncio.get_running_loop()
    next_poll = 0.0

    async def periodic_poll() -> None:
        nonlocal next_poll
        if loop.time() >= next_poll:
            await poll()
            next_poll = loop.time() + 0.1

    async def produce() -> None:
        try:
            async for item in stream:
                await queue.put((False, item, None))
                await advance.wait()
                advance.clear()
            await queue.put((True, None, None))
        except Exception as exc:
            await queue.put((True, None, exc))
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    await periodic_poll()
    producer = asyncio.create_task(produce())
    try:
        while True:
            finished, item, error = await await_model_control_v2(queue.get(), periodic_poll)
            if error is not None:
                raise error
            if finished:
                await poll()
                return
            if item is not None:
                yield item
            advance.set()
    finally:
        if not producer.done():
            producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer
