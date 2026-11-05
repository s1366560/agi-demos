"""Transcription may never silently dispatch an agent turn or TTS."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.model.audio_session import AudioMode
from src.infrastructure.adapters.primary.web.routers import voice_websocket
from src.infrastructure.adapters.primary.web.routers.voice_protocol import (
    transcript_events,
    voice_mode,
)


@pytest.mark.unit
def test_voice_requires_explicit_mode_and_unknown_mode_fails() -> None:
    assert voice_mode({}) is AudioMode.DICTATION
    assert voice_mode({"mode": "meeting"}) is AudioMode.MEETING
    assert voice_mode({"mode": "voice"}) is AudioMode.VOICE
    with pytest.raises(ValueError):
        voice_mode({"mode": "automatic"})


@pytest.mark.unit
def test_speaker_ids_are_namespaced_per_provider_connection() -> None:
    response = {
        "payload_msg": {
            "result": {
                "utterances": [
                    {
                        "text": "hello",
                        "start_time": 20,
                        "end_time": 300,
                        "speaker_id": "1",
                        "definite": True,
                    }
                ]
            }
        }
    }
    first = transcript_events(response, "provider-connection-a", 1)[0]
    second = transcript_events(response, "provider-connection-b", 1)[0]
    assert first["start_ms"] == 20
    assert first["end_ms"] == 300
    assert first["speaker_id"] != second["speaker_id"]
    assert first["type"] == "asr_final"


@pytest.mark.unit
@pytest.mark.parametrize("mode", [AudioMode.DICTATION, AudioMode.MEETING])
async def test_transcript_only_does_not_enqueue_agent_turn(mode: AudioMode) -> None:
    response = {"is_last_package": True, "payload_msg": {"result": {"text": "inspect my calendar"}}}
    asr = SimpleNamespace(receive=AsyncMock(side_effect=[response, None]))
    websocket = SimpleNamespace(send_json=AsyncMock())
    queue: asyncio.Queue[str] = asyncio.Queue()
    await voice_websocket._asr_processor(websocket, asr, queue, asyncio.Event(), mode=mode)
    assert queue.empty()
    assert websocket.send_json.call_args_list[-1].args[0]["type"] == "asr_final"


@pytest.mark.unit
async def test_provider_final_is_dispatched_once_and_interim_is_not_a_turn() -> None:
    utterance = {"text": "hello", "start_time": 0, "end_time": 400, "definite": True}
    response = {"payload_msg": {"result": {"utterances": [utterance]}}}
    asr = SimpleNamespace(receive=AsyncMock(side_effect=[response, response, None]))
    websocket = SimpleNamespace(send_json=AsyncMock())
    queue: asyncio.Queue[str] = asyncio.Queue()
    await voice_websocket._asr_processor(
        websocket, asr, queue, asyncio.Event(), mode=AudioMode.VOICE
    )
    assert queue.qsize() == 1
    assert queue.get_nowait() == "hello"
