"""Tests for MCP tool discovery retry mechanism.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that tool discovery uses exponential backoff retry
when transient failures occur.
"""

from unittest.mock import AsyncMock

import pytest


class TestToolDiscoveryRetry:
    """Test tool discovery retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_discover_tools_retries_on_transient_error(self):
        """
        RED Test: Verify that discover_tools_with_retry retries on transient errors.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            discover_tools_with_retry,
        )

        # Mock sandbox adapter
        mock_adapter = AsyncMock()

        # First two calls fail, third succeeds
        call_count = [0]

        async def mock_call_tool(**kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                # Transient error
                return {"is_error": True, "content": [{"type": "text", "text": "Connection reset"}]}
            else:
                # Success
                return {
                    "is_error": False,
                    "content": [{"type": "text", "text": '[{"name": "tool1"}]'}],
                }

        mock_adapter.call_tool = mock_call_tool

        # Act: Call with retry
        result = await discover_tools_with_retry(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            max_retries=3,
        )

        # Assert: Should have retried and eventually succeeded
        assert result is not None
        assert call_count[0] == 3, f"Expected 3 calls, got {call_count[0]}"

    @pytest.mark.asyncio
    async def test_discover_tools_returns_none_after_max_retries(self):
        """
        Test that discover_tools_with_retry returns None after max retries exhausted.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            discover_tools_with_retry,
        )

        mock_adapter = AsyncMock()

        # All calls fail with transient error pattern
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "is_error": True,
                "content": [{"type": "text", "text": "Connection reset by peer"}],
            }
        )

        # Act: Call with max 2 retries
        result = await discover_tools_with_retry(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            max_retries=2,
            base_delay_ms=10,  # Use short delay for testing
        )

        # Assert: Should return None after exhausting retries
        assert result is None
        # Should have made initial + 2 retries = 3 calls
        assert mock_adapter.call_tool.call_count == 3

    @pytest.mark.asyncio
    async def test_discover_tools_succeeds_immediately(self):
        """
        Test that discover_tools_with_retry returns immediately on success.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            discover_tools_with_retry,
        )

        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "is_error": False,
                "content": [{"type": "text", "text": '[{"name": "tool1"}]'}],
            }
        )

        # Act
        result = await discover_tools_with_retry(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            max_retries=3,
        )

        # Assert: Should succeed immediately without retries
        assert result is not None
        assert mock_adapter.call_tool.call_count == 1

    @pytest.mark.asyncio
    async def test_discover_tools_uses_exponential_backoff(self):
        """
        Test that discover_tools_with_retry uses exponential backoff between retries.
        """
        import time

        from src.infrastructure.agent.state.agent_worker_state import (
            discover_tools_with_retry,
        )

        mock_adapter = AsyncMock()

        call_times = []

        async def mock_call_tool(**kwargs):
            call_times.append(time.time())
            # Use a transient error pattern
            return {
                "is_error": True,
                "content": [{"type": "text", "text": "Connection timeout"}],
            }

        mock_adapter.call_tool = mock_call_tool

        # Act with short delays for testing
        result = await discover_tools_with_retry(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            max_retries=2,
            base_delay_ms=50,  # 50ms base delay for faster testing
            max_delay_ms=500,
        )

        # Assert: Should have used exponential backoff
        assert result is None
        assert len(call_times) == 3  # Initial + 2 retries

        # Check delays between calls
        if len(call_times) >= 2:
            first_delay = (call_times[1] - call_times[0]) * 1000  # ms
            # First delay should be around base_delay (50ms)
            assert first_delay >= 40, f"First delay too short: {first_delay}ms"

        if len(call_times) >= 3:
            second_delay = (call_times[2] - call_times[1]) * 1000  # ms
            # Second delay should be around 2x base_delay (100ms)
            assert second_delay >= 80, f"Second delay too short: {second_delay}ms"

    @pytest.mark.asyncio
    async def test_discover_tools_respects_max_delay(self):
        """
        Test that discover_tools_with_retry caps delay at max_delay_ms.
        """
        import time

        from src.infrastructure.agent.state.agent_worker_state import (
            discover_tools_with_retry,
        )

        mock_adapter = AsyncMock()

        call_times = []
        call_count = [0]

        async def mock_call_tool(**kwargs):
            call_count[0] += 1
            call_times.append(time.time())
            return {"is_error": True, "content": [{"type": "text", "text": "Error"}]}

        mock_adapter.call_tool = mock_call_tool

        # Act with very high base delay but low max delay
        await discover_tools_with_retry(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            server_name="test-server",
            max_retries=2,
            base_delay_ms=1000,  # Would give 1s, 2s delays without cap
            max_delay_ms=100,  # Cap at 100ms
        )

        # Assert: Delays should be capped at max_delay
        if len(call_times) >= 2:
            first_delay = (call_times[1] - call_times[0]) * 1000  # ms
            # Should be capped at max_delay (100ms) with some tolerance
            assert first_delay <= 150, f"Delay exceeded max: {first_delay}ms > 100ms"
