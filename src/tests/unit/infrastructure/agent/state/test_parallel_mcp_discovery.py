"""Unit tests for parallel MCP tool discovery.

These tests verify that MCP server tool discovery happens in parallel
using asyncio.gather for improved performance.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestParallelMCPToolDiscovery:
    """Test suite for parallel MCP tool discovery."""

    @pytest.mark.asyncio
    async def test_discover_tools_parallel_timing(self):
        """Test that tools are discovered in parallel for multiple servers.

        This test verifies that the discovery is parallel by checking timing:
        - If serial, 3 servers x 0.1s = 0.3s
        - If parallel, should be ~0.1s
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        # Mock sandbox adapter
        mock_adapter = MagicMock()

        servers = [
            {"name": "server1", "status": "running"},
            {"name": "server2", "status": "running"},
            {"name": "server3", "status": "running"},
        ]

        call_count = 0

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            nonlocal call_count
            call_count += 1
            # Simulate network delay
            await asyncio.sleep(0.1)
            return [{"name": f"{server_name}_tool1", "description": "Test tool"}]

        # Run discovery
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

        # All 3 servers should have been processed
        assert call_count == 3

        # If parallel, should take ~0.1s; if serial, ~0.3s
        assert duration < 0.25, f"Discovery took {duration:.2f}s - likely not parallel"

        # All results should be present
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_discover_tools_handles_partial_failure(self):
        """Test that partial failures don't prevent other servers from being discovered.

        Using return_exceptions=True in asyncio.gather ensures that one failure
        doesn't stop other discoveries.
        """
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        servers = [
            {"name": "server1", "status": "running"},
            {"name": "server2", "status": "running"},
            {"name": "server3", "status": "running"},
        ]

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            if server_name == "server2":
                raise Exception("Connection failed for server2")
            return [{"name": f"{server_name}_tool1", "description": "Test tool"}]

        # Run discovery
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            results = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
            )

        # Should have results from server1 and server3 (server2 failed)
        assert len(results) == 2, f"Expected 2 results, got {len(results)}"

        # Verify the results are from non-failed servers
        all_tool_names = []
        for result in results:
            for tool in result:
                all_tool_names.append(tool.get("name", ""))

        assert "server1_tool1" in all_tool_names
        assert "server3_tool1" in all_tool_names

    @pytest.mark.asyncio
    async def test_discover_tools_empty_server_list(self):
        """Test handling of empty server list."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()
        servers = []

        results = await _discover_tools_for_servers_parallel(
            sandbox_adapter=mock_adapter,
            sandbox_id="test-sandbox",
            servers=servers,
        )

        # Should return empty list
        assert results == []

    @pytest.mark.asyncio
    async def test_discover_tools_skips_non_running_servers(self):
        """Test that non-running servers are skipped."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_tools_for_servers_parallel,
        )

        mock_adapter = MagicMock()

        servers = [
            {"name": "running_server", "status": "running"},
            {"name": "stopped_server", "status": "stopped"},
            {"name": "error_server", "status": "error"},
        ]

        discover_calls = []

        async def mock_discover_single(sandbox_adapter, sandbox_id, server_name):
            discover_calls.append(server_name)
            return [{"name": f"{server_name}_tool1", "description": "Test"}]

        # Run discovery
        with patch(
            "src.infrastructure.agent.state.agent_worker_state._discover_single_server_tools",
            side_effect=mock_discover_single,
        ):
            results = await _discover_tools_for_servers_parallel(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                servers=servers,
            )

        # Should only discover tools from running_server
        assert discover_calls == ["running_server"], (
            f"Should only discover from running server, got: {discover_calls}"
        )


class TestDiscoverSingleServerTools:
    """Test discovering tools from a single server."""

    @pytest.mark.asyncio
    async def test_discover_single_server_tools_success(self):
        """Test successful tool discovery from a single server."""
        import json

        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_single_server_tools,
        )

        mock_adapter = MagicMock()

        # Use JSON format that _parse_discovered_tools expects
        tools_data = [{"name": "test_tool", "description": "Test tool"}]

        async def mock_call_tool(*args, **kwargs):
            return {
                "content": [{"type": "text", "text": json.dumps(tools_data)}],
                "is_error": False,
            }

        mock_adapter.call_tool = mock_call_tool

        tools = await _discover_single_server_tools(
            sandbox_adapter=mock_adapter,
            sandbox_id="test-sandbox",
            server_name="test_server",
        )

        # Should return list of tool info dicts
        assert isinstance(tools, list)
        assert len(tools) >= 1

    @pytest.mark.asyncio
    async def test_discover_single_server_tools_handles_exception(self):
        """Test that exceptions in single server discovery are handled."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_single_server_tools,
        )

        mock_adapter = MagicMock()

        async def mock_call_tool(*args, **kwargs):
            raise Exception("Connection failed")

        mock_adapter.call_tool = mock_call_tool

        tools = await _discover_single_server_tools(
            sandbox_adapter=mock_adapter,
            sandbox_id="test-sandbox",
            server_name="test_server",
        )

        # Should return empty list on error
        assert tools == []

    @pytest.mark.asyncio
    async def test_discover_single_server_tools_handles_error_response(self):
        """Test that error responses are handled."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _discover_single_server_tools,
        )

        mock_adapter = MagicMock()

        async def mock_call_tool(*args, **kwargs):
            return {
                "content": [{"type": "text", "text": "Error: Failed to connect"}],
                "is_error": True,
            }

        mock_adapter.call_tool = mock_call_tool

        tools = await _discover_single_server_tools(
            sandbox_adapter=mock_adapter,
            sandbox_id="test-sandbox",
            server_name="test_server",
        )

        # Should return empty list on error response
        assert tools == []


class TestLoadUserMCPServerToolsIntegration:
    """Integration tests for the full _load_user_mcp_server_tools function."""

    @pytest.mark.asyncio
    async def test_parallel_discovery_is_used(self):
        """Test that _discover_tools_for_servers_parallel is called.

        This test verifies that the parallel discovery function is called
        when loading user MCP server tools by mocking the parser and adapter.
        """
        import json

        from src.infrastructure.agent.state.agent_worker_state import (
            _load_user_mcp_server_tools,
        )

        mock_adapter = MagicMock()

        async def mock_call_tool(*args, **kwargs):
            tool_name = kwargs.get("tool_name", args[1] if len(args) > 1 else "")

            if tool_name == "mcp_server_list":
                return {
                    "content": [{"type": "text", "text": "some text"}],
                    "is_error": False,
                }
            elif tool_name == "mcp_server_discover_tools":
                await asyncio.sleep(0.05)
                server_name = kwargs.get("arguments", {}).get("name", "")
                tools_data = [
                    {"name": f"{server_name}_tool1", "description": "Test tool", "inputSchema": {}}
                ]
                return {
                    "content": [{"type": "text", "text": json.dumps(tools_data)}],
                    "is_error": False,
                }
            return {"content": [], "is_error": False}

        mock_adapter.call_tool = mock_call_tool

        # Track if parallel function was called with correct args
        captured_args = None

        async def mock_parallel(sandbox_adapter, sandbox_id, servers):
            nonlocal captured_args
            captured_args = {
                "sandbox_adapter": sandbox_adapter,
                "sandbox_id": sandbox_id,
                "servers": servers,
            }
            return []

        # Mock the parser to return our test servers
        def mock_parse(content):
            return [
                {"name": "server1", "status": "running"},
                {"name": "server2", "status": "running"},
            ]

        # Mock _auto_restore_mcp_servers to avoid DB dependency
        with (
            patch(
                "src.infrastructure.agent.state.agent_worker_state._auto_restore_mcp_servers",
                new_callable=AsyncMock,
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._parse_mcp_server_list",
                side_effect=mock_parse,
            ),
            patch(
                "src.infrastructure.agent.state.agent_worker_state._discover_tools_for_servers_parallel",
                side_effect=mock_parallel,
            ),
        ):
            await _load_user_mcp_server_tools(
                sandbox_adapter=mock_adapter,
                sandbox_id="test-sandbox",
                project_id="test-project",
            )

        # Verify parallel function was called with correct arguments
        assert captured_args is not None, "Parallel function should have been called"
        assert captured_args["sandbox_id"] == "test-sandbox"
        # Should have 2 running servers
        assert len(captured_args["servers"]) == 2
        server_names = [s["name"] for s in captured_args["servers"]]
        assert "server1" in server_names
        assert "server2" in server_names
