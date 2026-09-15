"""Deliver durable cancellation requests to the task that actually owns execution."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from types import TracebackType
from typing import Self

from src.domain.model.agent.subagent_run import SubAgentRunStatus
from src.domain.model.agent.tool_policy import ControlMessageType
from src.domain.ports.agent.control_channel_port import ControlChannelPort

from .async_run_registry_v2 import registry_call_v2
from .run_registry import SubAgentRunRegistry


class SubAgentOwnerControlV2:
    """One operation-owned watcher; closing always waits for its task to exit.

    Redis supplies prompt delivery. The registry request remains authoritative
    after stream loss or API restart. Only the actual runner writes a terminal
    acknowledgement, after unwinding execution. A failed control read aborts
    the owner and is exposed separately from user cancellation.
    """

    def __init__(
        self,
        registry: Callable[[], SubAgentRunRegistry],
        conversation_id: str,
        run_id: str,
        channel: ControlChannelPort | None,
    ) -> None:
        self._registry = registry
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._channel = channel
        self._watcher: asyncio.Task[None] | None = None
        self.failure: Exception | None = None

    async def __aenter__(self) -> Self:
        owner = asyncio.current_task()
        assert owner is not None
        self._watcher = asyncio.create_task(
            self._watch(owner), name=f"subagent-control-{self._run_id}"
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._watcher is not None:
            _ = self._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await self._watcher

        if self._channel is not None:
            run = await registry_call_v2(
                self._registry(), "get_run", self._conversation_id, self._run_id
            )
            if run is None or run.status not in {
                SubAgentRunStatus.PENDING,
                SubAgentRunStatus.RUNNING,
            }:
                await self._channel.cleanup(self._run_id)

    async def _watch(self, owner: asyncio.Task[object]) -> None:
        try:
            while True:
                run = await registry_call_v2(
                    self._registry(), "get_run", self._conversation_id, self._run_id
                )
                if run is not None and run.metadata.get("cancel_requested") is True:
                    if not owner.cancelling():
                        _ = owner.cancel()
                    return
                if self._channel is not None:
                    control = await self._channel.check_control(self._run_id)
                    if control is not None and control.message_type is ControlMessageType.KILL:
                        if not owner.cancelling():
                            _ = owner.cancel()
                        return
                await asyncio.sleep(0.1)
        except Exception as exc:
            self.failure = exc
            if not owner.cancelling():
                _ = owner.cancel()
