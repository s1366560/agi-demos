"""Tests for parallel tool discovery timeout isolation.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that parallel tool discovery has proper timeout isolation
to prevent slow servers from blocking the entire discovery process.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestParallelDiscoveryTimeout:
    """Test timeout isolation for parallel tool discovery."""

    @pytest.mark.asyncio
    async def test_discover_tools_parallel_respects_overall_timeout(self):
        """
        RED Test: Parallel discovery should respect an overall timeout.

        If the entire discovery operation takes longer than the timeout,
        it should return empty results (timeout protection).
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        # Create servers that will take longer than timeout
        servers = [
            {"name": "slow-server", "status": "running"},
        ]

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            # This would exceed a 0.1s timeout
            await asyncio.sleep(1.0)
            return [{"name": "slow_tool"}]

        # Act: Run with short timeout, measure duration
        start = time.time()
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            results = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
                overall_timeout_seconds=0.1,  # Short timeout
            )
        duration = time.time() - start

        # Assert: Should timeout quickly, not wait 1s
        assert duration < 0.3, f"Should timeout quickly, took {duration:.2f}s"
        # Results are empty because timeout occurred
        assert results == []

    @pytest.mark.asyncio
    async def test_discover_tools_parallel_returns_results_if_fast_enough(self):
        """
        Test that discovery completes if servers are fast enough.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        servers = [
            {"name": "server1", "status": "running"},
            {"name": "server2", "status": "running"},
        ]

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            await asyncio.sleep(0.02)
            return [{"name": f"{server_name}_tool"}]

        # Act: Run with timeout that allows completion
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            results = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
                overall_timeout_seconds=0.5,  # Generous timeout
            )

        # Assert: Should have both results
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_discover_tools_parallel_no_timeout_default(self):
        """
        Test that default behavior (no timeout) still works.

        When no timeout is specified, the function should wait for all
        servers to complete.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        servers = [
            {"name": "server1", "status": "running"},
            {"name": "server2", "status": "running"},
        ]

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            await asyncio.sleep(0.05)
            return [{"name": f"{server_name}_tool"}]

        # Act: Run without timeout (default)
        start = time.time()
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            results = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
            )
        duration = time.time() - start

        # Assert: All servers should complete (parallel, ~0.05s not ~0.1s)
        assert len(results) == 2
        assert duration < 0.15, f"Should be parallel, took {duration:.2f}s"

    @pytest.mark.asyncio
    async def test_discover_tools_parallel_timeout_returns_empty_on_no_results(self):
        """
        RED Test: Very short timeout should return empty list if no results yet.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        servers = [
            {"name": "slow-server", "status": "running"},
        ]

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            await asyncio.sleep(1.0)  # Very slow
            return [{"name": "tool"}]

        # Act: Run with very short timeout
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            results = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
                overall_timeout_seconds=0.01,  # Very short
            )

        # Assert: Should return empty list (no results in time)
        assert results == []

    @pytest.mark.asyncio
    async def test_discover_tools_parallel_timeout_is_configurable(self):
        """
        RED Test: Timeout should be configurable via parameter.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        servers = [
            {"name": "server1", "status": "running"},
        ]

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            await asyncio.sleep(0.1)
            return [{"name": "tool"}]

        # Act: Run with different timeout values
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            # With long timeout - should complete
            results_long = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
                overall_timeout_seconds=1.0,
            )

            # With short timeout - should timeout
            results_short = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
                overall_timeout_seconds=0.01,
            )

        # Assert: Long timeout should get results, short should not
        assert len(results_long) == 1
        assert len(results_short) == 0
