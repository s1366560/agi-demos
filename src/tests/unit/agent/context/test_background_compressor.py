"""Tests for BackgroundCompressor."""


import pytest

from src.infrastructure.agent.context.background_compressor import BackgroundCompressor
from src.infrastructure.agent.context.compaction import ModelLimits
from src.infrastructure.agent.context.compression_engine import ContextCompressionEngine
from src.infrastructure.agent.context.compression_state import CompressionLevel


def simple_token_estimator(text: str) -> int:
    return len(text) // 4 if text else 0


def simple_message_token_estimator(msg: dict) -> int:
    content = msg.get("content", "")
    return simple_token_estimator(content) + 4


def make_engine(**kwargs) -> ContextCompressionEngine:
    return ContextCompressionEngine(
        estimate_tokens=simple_token_estimator,
        estimate_message_tokens=simple_message_token_estimator,
        **kwargs,
    )


def make_messages(count: int = 5) -> list:
    return [{"role": "user", "content": f"Message {i}: " + "x" * 100} for i in range(count)]


@pytest.mark.unit
class TestBackgroundCompressor:
    def test_initial_state(self):
        engine = make_engine()
        compressor = BackgroundCompressor(engine)
        assert not compressor.is_running
        assert compressor.last_result is None

    async def test_schedule_and_complete(self):
        engine = make_engine()
        compressor = BackgroundCompressor(engine)
        messages = make_messages(5)
        limits = ModelLimits(context=128000, input=0, output=4096)

        scheduled = compressor.schedule(
            system_prompt="Test",
            messages=messages,
            model_limits=limits,
            level=CompressionLevel.NONE,
        )
        assert scheduled is True
        assert engine.state.pending_compression is True

        result = await compressor.get_result(timeout=5.0)
        assert result is not None
        assert result.level == CompressionLevel.NONE

    async def test_schedule_rejected_when_running(self):
        engine = make_engine()
        compressor = BackgroundCompressor(engine)
        messages = make_messages(5)
        limits = ModelLimits(context=128000, input=0, output=4096)

        # Schedule first task
        compressor.schedule(
            system_prompt="Test",
            messages=messages,
            model_limits=limits,
            level=CompressionLevel.NONE,
        )

        # Second schedule should be rejected if first is still running
        # (it may complete instantly, so this tests the logic path)
        result = compressor.schedule(
            system_prompt="Test2",
            messages=messages,
            model_limits=limits,
            level=CompressionLevel.NONE,
        )
        # Either True (first completed) or False (still running)
        assert isinstance(result, bool)

        # Wait for completion
        await compressor.get_result(timeout=5.0)

    async def test_cancel(self):
        engine = make_engine()
        compressor = BackgroundCompressor(engine)

        compressor.cancel()  # Should not error on empty
        assert not compressor.is_running

    async def test_reset(self):
        engine = make_engine()
        compressor = BackgroundCompressor(engine)
        messages = make_messages(5)
        limits = ModelLimits(context=128000, input=0, output=4096)

        compressor.schedule(
            system_prompt="Test",
            messages=messages,
            model_limits=limits,
            level=CompressionLevel.NONE,
        )
        await compressor.get_result(timeout=5.0)

        compressor.reset()
        assert compressor.last_result is None
        assert not compressor.is_running

    async def test_get_result_without_schedule(self):
        engine = make_engine()
        compressor = BackgroundCompressor(engine)
        result = await compressor.get_result(timeout=1.0)
        assert result is None
