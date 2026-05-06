"""Tests for ``SessionProcessor.add_runtime_guidance``."""

from __future__ import annotations

import asyncio

import pytest

from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
)


def _make_processor() -> SessionProcessor:
    config = ProcessorConfig(model="gpt-4", api_key="x", base_url="http://x")
    return SessionProcessor(config, tools=[])


@pytest.mark.asyncio
async def test_add_runtime_guidance_appends_once() -> None:
    proc = _make_processor()
    appended = await proc.add_runtime_guidance("Lane Todo received the card.")
    assert appended is True
    assert proc._session_instructions == ["Lane Todo received the card."]


@pytest.mark.asyncio
async def test_add_runtime_guidance_is_idempotent() -> None:
    proc = _make_processor()
    assert await proc.add_runtime_guidance("X")
    assert (await proc.add_runtime_guidance("X")) is False
    assert (await proc.add_runtime_guidance("  X  ")) is False  # stripped match
    assert proc._session_instructions == ["X"]


@pytest.mark.asyncio
async def test_add_runtime_guidance_rejects_blank() -> None:
    proc = _make_processor()
    assert (await proc.add_runtime_guidance("")) is False
    assert (await proc.add_runtime_guidance("   ")) is False
    assert proc._session_instructions == []


@pytest.mark.asyncio
async def test_add_runtime_guidance_concurrent_safe() -> None:
    """Concurrent injectors must not duplicate the same block."""
    proc = _make_processor()
    text = "Concurrent guidance block"
    results = await asyncio.gather(
        *(proc.add_runtime_guidance(text) for _ in range(20))
    )
    assert sum(1 for r in results if r) == 1
    assert proc._session_instructions == [text]


@pytest.mark.asyncio
async def test_add_runtime_guidance_distinct_blocks_all_appended() -> None:
    proc = _make_processor()
    blocks = [f"block-{i}" for i in range(5)]
    for b in blocks:
        assert await proc.add_runtime_guidance(b)
    assert proc._session_instructions == blocks
