"""Volcengine ASR and TTS adapters delegating to streaming WebSocket clients.

These adapters implement the domain port interfaces (ASRServicePort, TTSServicePort)
by wrapping the low-level Volcengine streaming clients. Both non-streaming and
streaming methods are provided.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, BinaryIO

from src.domain.ports.services.audio_service_port import ASRServicePort, TTSServicePort

logger = logging.getLogger(__name__)


class VolcengineASRAdapter(ASRServicePort):
    """Volcengine ASR using streaming WebSocket V3 client."""

    def __init__(self, access_key: str, app_key: str) -> None:
        self._access_key = access_key
        self._app_key = app_key

    async def transcribe(
        self,
        audio_file: BinaryIO,
        language: str = "zh-CN",
        options: dict[str, Any] | None = None,
    ) -> str:
        """Non-streaming: read all audio, send through streaming client, collect result."""
        from src.infrastructure.adapters.secondary.external.volcengine.asr_streaming_client import (
            AsyncASRStreamingClient,
        )

        client = AsyncASRStreamingClient(self._access_key, self._app_key)
        await client.connect()
        try:
            audio_data = audio_file.read()
            chunk_size = 3200  # 100ms of 16kHz 16-bit mono
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i : i + chunk_size]
                is_last = i + chunk_size >= len(audio_data)
                await client.send_audio(chunk, is_last=is_last)

            final_text = ""
            while True:
                result = await client.receive()
                if result is None:
                    break
                text = result.get("payload_msg", {}).get("result", {}).get("text", "")
                if text:
                    final_text = text
                if result.get("is_last_package"):
                    break
            return final_text
        finally:
            await client.close()

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str = "zh-CN",
        options: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming: yield interim/final results as audio chunks arrive."""
        from src.infrastructure.adapters.secondary.external.volcengine.asr_streaming_client import (
            AsyncASRStreamingClient,
        )

        client = AsyncASRStreamingClient(self._access_key, self._app_key)
        await client.connect()
        try:

            async def _send_audio() -> None:
                async for chunk in audio_stream:
                    await client.send_audio(chunk)
                await client.send_audio(b"", is_last=True)

            send_task = asyncio.create_task(_send_audio())

            try:
                while True:
                    result = await client.receive()
                    if result is None:
                        break
                    text = result.get("payload_msg", {}).get("result", {}).get("text", "")
                    if text:
                        yield text
                    if result.get("is_last_package"):
                        break
            finally:
                if not send_task.done():
                    send_task.cancel()
                    try:
                        await send_task
                    except asyncio.CancelledError:
                        pass
        finally:
            await client.close()


class VolcengineTTSAdapter(TTSServicePort):
    """Volcengine TTS using bidirectional WebSocket V3 client."""

    def __init__(
        self,
        access_key: str,
        app_key: str,
        speaker: str = "zh_female_tianmeixiaoyuan_moon_bigtts",
    ) -> None:
        self._access_key = access_key
        self._app_key = app_key
        self._speaker = speaker

    async def synthesize(
        self,
        text: str,
        voice_type: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Non-streaming: collect all audio chunks into a single bytes object."""
        from src.infrastructure.adapters.secondary.external.volcengine.tts_streaming_client import (
            AsyncTTSStreamingClient,
        )

        speaker = voice_type or self._speaker
        client = AsyncTTSStreamingClient(self._access_key, self._app_key, speaker=speaker)
        await client.connect()
        try:
            chunks: list[bytes] = []
            async for chunk in client.synthesize(text):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            await client.close()

    async def synthesize_stream(
        self,
        text: str,
        voice_type: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """Streaming: yield audio chunks as they arrive from the TTS client."""
        from src.infrastructure.adapters.secondary.external.volcengine.tts_streaming_client import (
            AsyncTTSStreamingClient,
        )

        speaker = voice_type or self._speaker
        client = AsyncTTSStreamingClient(self._access_key, self._app_key, speaker=speaker)
        await client.connect()
        try:
            async for chunk in client.synthesize(text):
                yield chunk
        finally:
            await client.close()
