"""Contract test: every model-visible message is logged (I2 invariant).

The Python-side half of the shared model-visible => logged invariant. The
session log at this seam is the conversation ``messages`` list handed into
the step plus the processor's logged instruction state; anything else that
reaches the LLM (the runtime-guidance system message) must be derived from
that logged state, never from ephemeral data.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
)


async def _fake_stream(captured: list[dict[str, Any]], _self: Any, messages, **kwargs):
    captured.extend(messages)
    text_end = MagicMock()
    text_end.type = StreamEventType.TEXT_END
    text_end.data = {"full_text": "Done."}
    yield text_end
    finish = MagicMock()
    finish.type = StreamEventType.FINISH
    finish.data = {"reason": "stop"}
    yield finish


@pytest.mark.unit
class TestModelVisibleLogged:
    async def test_every_model_visible_message_is_logged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        async def fake_generate(_self: Any, messages: list[dict[str, Any]], **kwargs: Any):
            async for event in _fake_stream(captured, _self, messages, **kwargs):
                yield event

        monkeypatch.setattr(
            "src.infrastructure.agent.processor.processor.LLMStream.generate",
            fake_generate,
        )

        proc = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])
        session_log = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "hello"},
        ]

        events = [event async for event in proc._process_step("session-1", list(session_log))]
        assert events
        assert captured, "no model call was captured"

        for message in captured:
            if message in session_log:
                continue
            # The only non-log message allowed to reach the model is the
            # runtime-guidance system message, which is rendered from the
            # processor's logged instruction state.
            assert message["role"] == "system"
            assert message["content"].startswith("[Runtime Guidance]")

    async def test_guidance_message_derives_from_logged_instructions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[dict[str, Any]] = []

        async def fake_generate(_self: Any, messages: list[dict[str, Any]], **kwargs: Any):
            async for event in _fake_stream(captured, _self, messages, **kwargs):
                yield event

        monkeypatch.setattr(
            "src.infrastructure.agent.processor.processor.LLMStream.generate",
            fake_generate,
        )

        proc = SessionProcessor(config=ProcessorConfig(model="test-model"), tools=[])
        logged_instruction = "Always cite sources in the final answer."
        proc._session_instructions = [logged_instruction]

        _ = [
            event
            async for event in proc._process_step("session-1", [{"role": "user", "content": "hi"}])
        ]

        guidance = next(m for m in captured if m["content"].startswith("[Runtime Guidance]"))
        assert logged_instruction in guidance["content"]
