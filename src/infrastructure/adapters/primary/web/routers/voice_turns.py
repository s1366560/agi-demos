"""A new voice turn fences and cancels old agent/TTS work before it can emit."""

import asyncio
import base64
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import WebSocket


class VoiceTurnSocket:
    def __init__(self, websocket: WebSocket, current: Callable[[], bool], generation: int) -> None:
        self.websocket = websocket
        self.current = current
        self.generation = generation

    async def send_json(self, value: dict[str, Any]) -> None:
        if self.current():
            await self.websocket.send_json({**value, "turn_generation": self.generation})

    async def send_bytes(self, value: bytes) -> None:
        if self.current():
            await self.websocket.send_json(
                {
                    "type": "tts_audio",
                    "turn_generation": self.generation,
                    "data_base64": base64.b64encode(value).decode("ascii"),
                }
            )


async def voice_turns(
    websocket: WebSocket,
    utterances: asyncio.Queue[str],
    interrupts: asyncio.Queue[None],
    shutdown: asyncio.Event,
    agent: Callable[..., Coroutine[Any, Any, None]],
    tts: Callable[..., Coroutine[Any, Any, None]],
    agent_arguments: dict[str, Any],
    tts_arguments: dict[str, Any],
) -> None:
    generation = 0
    tasks: list[asyncio.Task[None]] = []

    async def retire() -> None:
        nonlocal generation
        generation += 1
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        tasks.clear()

    try:
        while not shutdown.is_set():
            text_task = asyncio.create_task(utterances.get())
            interrupt_task = asyncio.create_task(interrupts.get())
            stop_task = asyncio.create_task(shutdown.wait())
            try:
                completed, _ = await asyncio.wait(
                    [text_task, interrupt_task, stop_task], return_when=asyncio.FIRST_COMPLETED
                )
                if stop_task in completed:
                    return
                await retire()
                await websocket.send_json(
                    {"type": "voice_interrupted", "turn_generation": generation}
                )
                if text_task in completed:
                    turn = generation

                    def still_current(expected: int = turn) -> bool:
                        return expected == generation

                    socket = VoiceTurnSocket(websocket, still_current, turn)
                    queue: asyncio.Queue[str] = asyncio.Queue()
                    queue.put_nowait(text_task.result())
                    synthesis: asyncio.Queue[str | None] = asyncio.Queue()
                    turn_stop = asyncio.Event()
                    tasks.extend(
                        [
                            asyncio.create_task(
                                agent(
                                    websocket=socket,
                                    asr_final_queue=queue,
                                    tts_text_queue=synthesis,
                                    shutdown=turn_stop,
                                    **agent_arguments,
                                )
                            ),
                            asyncio.create_task(
                                tts(
                                    websocket=socket,
                                    tts_text_queue=synthesis,
                                    shutdown=turn_stop,
                                    **tts_arguments,
                                )
                            ),
                        ]
                    )
            finally:
                for task in (text_task, interrupt_task, stop_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(text_task, interrupt_task, stop_task, return_exceptions=True)
    finally:
        await retire()
