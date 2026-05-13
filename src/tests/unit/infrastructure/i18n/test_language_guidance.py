"""Tests for the language guidance helper used by the ReAct stream mixin.

The actual injection happens inside ``react_agent_stream_mixin.stream`` after
processor creation. To avoid the heavy fixture cost of building a full
ReActAgent, these tests exercise the public surface that the injection relies
on:

  * ``SessionProcessor.add_runtime_guidance`` accepts the language block
    idempotently.
  * ``SessionProcessor._build_runtime_guidance_message`` renders the language
    block into the ``[Runtime Guidance]`` system message that goes to the LLM.

If the wording in the stream mixin changes, update ``LANGUAGE_GUIDANCE_TEXT``
here too.
"""

from __future__ import annotations

import pytest

from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor

LANGUAGE_GUIDANCE_TEXT_ZH = (
    "Respond to the user in Chinese (Simplified) (zh-CN) "
    "unless they explicitly request another language. "
    "Keep tool arguments, code, and identifiers in their "
    "original form; only the natural-language portions of "
    "your reply should follow this language preference."
)

LANGUAGE_GUIDANCE_TEXT_EN = (
    "Respond to the user in English (en-US) "
    "unless they explicitly request another language. "
    "Keep tool arguments, code, and identifiers in their "
    "original form; only the natural-language portions of "
    "your reply should follow this language preference."
)


def _make_processor() -> SessionProcessor:
    config = ProcessorConfig(model="gpt-4o-mini")
    return SessionProcessor(config=config, tools=[])


@pytest.mark.asyncio
async def test_language_guidance_is_added_once() -> None:
    processor = _make_processor()
    first = await processor.add_runtime_guidance(LANGUAGE_GUIDANCE_TEXT_ZH)
    second = await processor.add_runtime_guidance(LANGUAGE_GUIDANCE_TEXT_ZH)
    assert first is True
    assert second is False  # idempotent


@pytest.mark.asyncio
async def test_language_guidance_renders_into_runtime_guidance_message() -> None:
    processor = _make_processor()
    await processor.add_runtime_guidance(LANGUAGE_GUIDANCE_TEXT_EN)
    message = processor._build_runtime_guidance_message()
    assert message is not None
    assert message["role"] == "system"
    assert "[Runtime Guidance]" in message["content"]
    assert "English (en-US)" in message["content"]


@pytest.mark.asyncio
async def test_language_guidance_blank_is_ignored() -> None:
    processor = _make_processor()
    added = await processor.add_runtime_guidance("   ")
    assert added is False
    assert processor._build_runtime_guidance_message() is None
