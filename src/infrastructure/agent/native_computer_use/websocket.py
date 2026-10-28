"""One private control stream per authenticated desktop socket."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis

from src.infrastructure.agent.native_computer_use.broker import NativeComputerBroker
from src.infrastructure.agent.native_computer_use.store import control_key, string

STATE_KEY = "memstack_native_computer_use_connection"


@dataclass
class DeviceConnection:
    redis: Redis
    websocket: Any = field(repr=False)
    connection_id: str = field(default_factory=lambda: str(uuid4()))
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self.pump(), name="computer-use-device-control")

    async def pump(self) -> None:
        cursor = "0-0"
        broker = NativeComputerBroker(self.redis)
        try:
            while True:
                await broker.devices.heartbeat(self.connection_id)
                batches = await self.redis.xread(
                    {control_key(self.connection_id): cursor}, count=16, block=10_000
                )
                for _stream, events in batches:
                    for event_id, values in events:
                        cursor = string(event_id)
                        fields = {string(key): string(value) for key, value in values.items()}
                        await self.websocket.send_json(
                            {
                                "type": fields["type"],
                                "request_id": fields["request_id"],
                                **(
                                    {"expires_at": int(fields["expires_at"])}
                                    if "expires_at" in fields
                                    else {}
                                ),
                            }
                        )
        finally:
            try:
                for request_id in await broker.members(
                    f"{control_key(self.connection_id)}:requests"
                ):
                    with suppress(Exception):
                        await broker.cancel_request(string(request_id))
            finally:
                await broker.devices.disconnect(self.connection_id)

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.task
        else:
            await NativeComputerBroker(self.redis).devices.disconnect(self.connection_id)


async def close_device_connection(scope: MutableMapping[str, Any]) -> None:
    state = scope.pop(STATE_KEY, None)
    if isinstance(state, DeviceConnection):
        await state.close()
