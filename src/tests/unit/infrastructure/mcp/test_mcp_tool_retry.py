"""
Unit tests for MCP tool loading retry logic.

Tests the retry mechanism that handles the startup race condition
where Agent Worker starts before MCP servers are fully initialized.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPToolRetry:
    """Test MCP tool loading retry logic."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for get_or_create_tools."""
        return {
            "graph_service": MagicMock(
                neo4j_client=MagicMock(),
                _neo4j_client=MagicMock(),
            ),
            "redis_client": MagicMock(),
            "project_id": "test-project",
            "tenant_id": "test-tenant",
        }

    @pytest.mark.asyncio
    async def test_mcp_tools_retry_on_empty_first_load(
        self, mock_dependencies
    ):
        """Test that MCP tools are retried when first load returns empty."""

        # Mock the loader
        mock_loader = MagicMock()
        call_count_loader = 0

        async def mock_load_all(refresh=False):
            nonlocal call_count_loader
            call_count_loader += 1
            if call_count_loader == 1:
                return {}
            else:
                return {"mcp__test_server__test_tool": MagicMock()}

        mock_loader.load_all_tools = AsyncMock(side_effect=mock_load_all)

        # Patch at the import location (inside the function)
        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_worker_state._mcp_temporal_adapter",
            MagicMock(),
        ):
            with patch(
                "src.infrastructure.mcp.temporal_tool_loader.MCPTemporalToolLoader",
                return_value=mock_loader,
            ):
                with patch(
                    "src.infrastructure.adapters.secondary.temporal.agent_worker_state.get_mcp_tools_from_cache",
                    return_value=None,  # Cache miss
                ):
                    with patch(
                        "src.infrastructure.adapters.secondary.temporal.agent_worker_state.update_mcp_tools_cache"
                    ):
                        # Import here to get fresh module state
                        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                            get_or_create_tools,
                        )

                        # Call get_or_create_tools with retry enabled
                        tools = await get_or_create_tools(
                            project_id=mock_dependencies["project_id"],
                            tenant_id=mock_dependencies["tenant_id"],
                            graph_service=mock_dependencies["graph_service"],
                            redis_client=mock_dependencies["redis_client"],
                            mcp_retry_on_empty=True,
                        )

                        # Verify retry happened (loader called more than once)
                        assert mock_loader.load_all_tools.call_count == 2
                        # Verify tools were loaded after retry
                        assert "mcp__test_server__test_tool" in tools

    @pytest.mark.asyncio
    async def test_mcp_tools_no_retry_when_disabled(
        self, mock_dependencies
    ):
        """Test that MCP tools are not retried when retry is disabled."""

        # Mock the loader
        mock_loader = MagicMock()
        mock_loader.load_all_tools = AsyncMock(return_value={})

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_worker_state._mcp_temporal_adapter",
            MagicMock(),
        ):
            with patch(
                "src.infrastructure.mcp.temporal_tool_loader.MCPTemporalToolLoader",
                return_value=mock_loader,
            ):
                with patch(
                    "src.infrastructure.adapters.secondary.temporal.agent_worker_state.get_mcp_tools_from_cache",
                    return_value=None,  # Cache miss
                ):
                    with patch(
                        "src.infrastructure.adapters.secondary.temporal.agent_worker_state.update_mcp_tools_cache"
                    ):
                        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                            get_or_create_tools,
                        )

                        # Call get_or_create_tools with retry disabled
                        tools = await get_or_create_tools(
                            project_id=mock_dependencies["project_id"],
                            tenant_id=mock_dependencies["tenant_id"],
                            graph_service=mock_dependencies["graph_service"],
                            redis_client=mock_dependencies["redis_client"],
                            mcp_retry_on_empty=False,
                        )

                        # Verify no retry happened (loader called only once)
                        assert mock_loader.load_all_tools.call_count == 1

    @pytest.mark.asyncio
    async def test_mcp_tools_no_retry_when_tools_loaded(
        self, mock_dependencies
    ):
        """Test that retry is skipped when tools are loaded on first attempt."""

        # Mock the loader
        mock_loader = MagicMock()
        mock_loader.load_all_tools = AsyncMock(
            return_value={"mcp__test_server__test_tool": MagicMock()}
        )

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_worker_state._mcp_temporal_adapter",
            MagicMock(),
        ):
            with patch(
                "src.infrastructure.mcp.temporal_tool_loader.MCPTemporalToolLoader",
                return_value=mock_loader,
            ):
                with patch(
                    "src.infrastructure.adapters.secondary.temporal.agent_worker_state.get_mcp_tools_from_cache",
                    return_value=None,  # Cache miss
                ):
                    with patch(
                        "src.infrastructure.adapters.secondary.temporal.agent_worker_state.update_mcp_tools_cache"
                    ):
                        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                            get_or_create_tools,
                        )

                        # Call get_or_create_tools with retry enabled
                        tools = await get_or_create_tools(
                            project_id=mock_dependencies["project_id"],
                            tenant_id=mock_dependencies["tenant_id"],
                            graph_service=mock_dependencies["graph_service"],
                            redis_client=mock_dependencies["redis_client"],
                            mcp_retry_on_empty=True,
                        )

                        # Verify no retry happened (loader called only once)
                        assert mock_loader.load_all_tools.call_count == 1
                        # Verify tools were loaded
                        assert "mcp__test_server__test_tool" in tools

    @pytest.mark.asyncio
    async def test_mcp_tools_exponential_backoff(
        self, mock_dependencies
    ):
        """Test that retry uses exponential backoff."""

        # Mock the loader
        mock_loader = MagicMock()
        mock_loader.load_all_tools = AsyncMock(return_value={})

        with patch(
            "src.infrastructure.adapters.secondary.temporal.agent_worker_state._mcp_temporal_adapter",
            MagicMock(),
        ):
            with patch(
                "src.infrastructure.mcp.temporal_tool_loader.MCPTemporalToolLoader",
                return_value=mock_loader,
            ):
                with patch(
                    "src.infrastructure.adapters.secondary.temporal.agent_worker_state.get_mcp_tools_from_cache",
                    return_value=None,  # Cache miss
                ):
                    with patch(
                        "src.infrastructure.adapters.secondary.temporal.agent_worker_state.update_mcp_tools_cache"
                    ):
                        # Mock asyncio.sleep to verify delays
                        sleep_delays = []

                        async def mock_sleep(delay):
                            sleep_delays.append(delay)

                        with patch(
                            "asyncio.sleep", side_effect=mock_sleep
                        ):
                            from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
                                get_or_create_tools,
                            )

                            # Call get_or_create_tools with retry enabled
                            tools = await get_or_create_tools(
                                project_id=mock_dependencies["project_id"],
                                tenant_id=mock_dependencies["tenant_id"],
                                graph_service=mock_dependencies["graph_service"],
                                redis_client=mock_dependencies["redis_client"],
                                mcp_retry_on_empty=True,
                            )

                            # Verify exponential backoff: 2s, 4s (for 3 retries total)
                            assert len(sleep_delays) == 2
                            assert sleep_delays[0] == 2.0
                            assert sleep_delays[1] == 4.0
