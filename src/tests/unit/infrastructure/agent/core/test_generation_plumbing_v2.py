"""Generation descriptor plumbing at the SessionProcessor turn boundary."""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.agent.core.react_agent_stream_mixin import StreamMixin


class _RecordingProcessor:
    def __init__(self) -> None:
        self.run_context: Any = None

    async def process(self, **kwargs: Any):
        self.run_context = kwargs["run_ctx"]
        if False:
            yield None


@pytest.mark.unit
async def test_stream_restores_process_safe_generation_payload_into_run_context() -> None:
    processor = _RecordingProcessor()
    stream = StreamMixin()

    events = [
        event
        async for event in stream._stream_process_events(  # type: ignore[arg-type]
            processor=processor,
            messages=[],
            langfuse_context={"conversation_id": "conversation-a"},
            abort_signal=None,
            matched_skill=None,
            plugin_generation={
                "profile_id": "default-v2",
                "generation": 7,
                "digest": "a" * 64,
            },
        )
    ]

    assert events == []
    assert processor.run_context.plugin_generation.profile_id == "default-v2"
    assert processor.run_context.plugin_generation.generation == 7
