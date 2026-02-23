"""Tests for unified cache invalidation functionality.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that cache invalidation cascades properly when
MCP tools are registered or updated.
"""

from unittest.mock import MagicMock

import pytest


class TestUnifiedCacheInvalidation:
    """Test unified cache invalidation for project-level caches."""

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_for_project_clears_tools_cache(self):
        """
        RED Test: Verify that invalidate_all_caches_for_project clears tools_cache.

        When a new MCP server is registered, the old tools cache for that project
        should be invalidated so the new tools are loaded on next request.
        """
        from src.infrastructure.agent.state import agent_worker_state

        # Setup: Populate tools_cache with an entry for the project
        project_id = "test-project-123"
        agent_worker_state._tools_cache[project_id] = {
            "tool1": MagicMock(),
            "tool2": MagicMock(),
        }

        # Act: Call the unified invalidation function
        result = agent_worker_state.invalidate_all_caches_for_project(project_id)

        # Assert: tools_cache should be cleared for this project
        assert project_id not in agent_worker_state._tools_cache
        assert "tools_cache" in result["invalidated"]
        assert result["invalidated"]["tools_cache"] == 1

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_for_project_clears_agent_sessions(self):
        """
        RED Test: Verify that invalidate_all_caches_for_project clears agent sessions.

        Agent sessions cache tool_definitions derived from tools, so they must
        be invalidated when tools change.
        """
        from src.infrastructure.agent.state import agent_worker_state
        from src.infrastructure.agent.state.agent_session_pool import (
            AgentSessionContext,
            _agent_session_pool,
        )

        # Setup: Populate agent session pool with sessions for the project
        tenant_id = "test-tenant"
        project_id = "test-project-456"

        # Create mock session context
        session_key = f"{tenant_id}:{project_id}:default"
        mock_session = AgentSessionContext(
            session_key=session_key,
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode="default",
            tool_definitions=[],
            raw_tools={"tool1": MagicMock()},
        )

        # Add to session pool directly
        _agent_session_pool[session_key] = mock_session

        # Act: Call the unified invalidation function
        result = agent_worker_state.invalidate_all_caches_for_project(
            project_id, tenant_id=tenant_id
        )

        # Assert: Agent session should be cleared
        assert session_key not in _agent_session_pool
        assert "agent_sessions" in result["invalidated"]
        assert result["invalidated"]["agent_sessions"] >= 1

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_for_project_clears_tool_definitions(self):
        """
        RED Test: Verify that invalidate_all_caches_for_project clears tool definitions.

        Tool definitions cache is keyed by tools_hash, which changes when new
        tools are registered. All entries should be cleared when tools change.
        """
        from src.infrastructure.agent.state import agent_worker_state
        from src.infrastructure.agent.state.agent_session_pool import (
            _tool_definitions_cache,
        )

        # Setup: Populate tool_definitions_cache with entries
        _tool_definitions_cache["hash1"] = (
            [MagicMock()],  # definitions
            1234567890.0,  # cached_at
        )
        _tool_definitions_cache["hash2"] = (
            [MagicMock()],
            1234567891.0,
        )

        # Act: Call the unified invalidation function
        result = agent_worker_state.invalidate_all_caches_for_project(
            "test-project", clear_tool_definitions=True
        )

        # Assert: Tool definitions cache should be cleared
        assert len(_tool_definitions_cache) == 0
        assert "tool_definitions" in result["invalidated"]
        assert result["invalidated"]["tool_definitions"] == 2

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_for_project_clears_mcp_tools_cache(self):
        """
        RED Test: Verify that invalidate_all_caches_for_project clears MCP tools cache.

        When MCP tools change, the mcp_tools_cache should be invalidated for
        the tenant associated with the project.
        """
        from src.infrastructure.agent.state import agent_worker_state
        from src.infrastructure.agent.state.agent_session_pool import (
            MCPToolsCacheEntry,
            _mcp_tools_cache,
        )

        # Setup: Populate mcp_tools_cache with entry for tenant
        tenant_id = "test-tenant-789"

        _mcp_tools_cache[tenant_id] = MCPToolsCacheEntry(
            tools={"mcp_tool1": MagicMock()},
            fetched_at=1234567890.0,
            tenant_id=tenant_id,
        )

        # Act: Call the unified invalidation function
        result = agent_worker_state.invalidate_all_caches_for_project(
            "test-project", tenant_id=tenant_id
        )

        # Assert: MCP tools cache should be cleared for this tenant
        assert tenant_id not in _mcp_tools_cache
        assert "mcp_tools" in result["invalidated"]
        assert result["invalidated"]["mcp_tools"] == 1

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_for_project_returns_summary(self):
        """
        RED Test: Verify that invalidate_all_caches_for_project returns a summary.

        The return value should show which caches were invalidated and how many
        entries were affected.
        """
        from src.infrastructure.agent.state import agent_worker_state

        project_id = "test-project-summary"
        tenant_id = "test-tenant-summary"

        # Setup: Populate some caches
        agent_worker_state._tools_cache[project_id] = {"tool1": MagicMock()}

        # Act
        result = agent_worker_state.invalidate_all_caches_for_project(
            project_id, tenant_id=tenant_id
        )

        # Assert: Result should have the expected structure
        assert "project_id" in result
        assert result["project_id"] == project_id
        assert "tenant_id" in result
        assert result["tenant_id"] == tenant_id
        assert "invalidated" in result
        assert isinstance(result["invalidated"], dict)

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_handles_missing_tenant_gracefully(self):
        """
        RED Test: Verify that invalidation works without tenant_id.

        When tenant_id is not provided, only project-scoped caches should be
        invalidated.
        """
        from src.infrastructure.agent.state import agent_worker_state

        project_id = "test-project-no-tenant"

        # Setup: Populate tools_cache only
        agent_worker_state._tools_cache[project_id] = {"tool1": MagicMock()}

        # Act: Call without tenant_id
        result = agent_worker_state.invalidate_all_caches_for_project(project_id)

        # Assert: Should still clear tools_cache
        assert project_id not in agent_worker_state._tools_cache
        assert result["invalidated"]["tools_cache"] == 1
        # mcp_tools should be 0 since no tenant_id was provided
        assert result["invalidated"].get("mcp_tools", 0) == 0

    @pytest.mark.asyncio
    async def test_invalidate_all_caches_clears_all_agent_modes(self):
        """
        RED Test: Verify that invalidation clears all agent modes for a project.

        A project can have multiple sessions (default, plan, etc.) and all
        should be invalidated.
        """
        from src.infrastructure.agent.state import agent_worker_state
        from src.infrastructure.agent.state.agent_session_pool import (
            AgentSessionContext,
            _agent_session_pool,
        )

        tenant_id = "test-tenant-modes"
        project_id = "test-project-modes"

        # Setup: Create sessions for multiple agent modes
        for mode in ["default", "plan", "analyze"]:
            session_key = f"{tenant_id}:{project_id}:{mode}"
            mock_session = AgentSessionContext(
                session_key=session_key,
                tenant_id=tenant_id,
                project_id=project_id,
                agent_mode=mode,
                tool_definitions=[],
                raw_tools={},
            )
            _agent_session_pool[session_key] = mock_session

        # Act
        result = agent_worker_state.invalidate_all_caches_for_project(
            project_id, tenant_id=tenant_id
        )

        # Assert: All sessions should be cleared
        assert result["invalidated"]["agent_sessions"] == 3
        for mode in ["default", "plan", "analyze"]:
            session_key = f"{tenant_id}:{project_id}:{mode}"
            assert session_key not in _agent_session_pool


class TestCacheInvalidationIntegration:
    """Integration tests for cache invalidation with RegisterMCPServerTool."""

    @pytest.mark.asyncio
    async def test_register_mcp_server_invalidates_all_caches(self):
        """
        Verify RegisterMCPServerTool calls unified invalidation.

        After registering a new MCP server, all relevant caches should be
        invalidated so the new tools are immediately available.
        """
        from src.infrastructure.agent.state import agent_worker_state
        from src.infrastructure.agent.tools.register_mcp_server import (
            RegisterMCPServerTool,
        )

        # Setup: Mock sandbox adapter and tools
        tenant_id = "test-tenant-reg"
        project_id = "test-project-reg"

        mock_adapter = MagicMock()

        # Populate caches before registration
        agent_worker_state._tools_cache[project_id] = {"old_tool": MagicMock()}

        tool = RegisterMCPServerTool(
            tenant_id=tenant_id,
            project_id=project_id,
            sandbox_adapter=mock_adapter,
            sandbox_id="test-sandbox",
            session_factory=None,
        )

        # Mock the sandbox adapter responses
        async def mock_call_tool(**kwargs):
            tool_name = kwargs.get("tool_name", "")
            if tool_name == "mcp_server_install" or tool_name == "mcp_server_start":
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            elif tool_name == "mcp_server_discover_tools":
                return {"content": [{"type": "text", "text": "[]"}]}
            return {"content": []}

        mock_adapter.call_tool = mock_call_tool

        # Act: Execute the tool (this should call the real invalidate function)
        await tool.execute(
            server_name="test-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )

        # Assert: Caches should be invalidated
        # tools_cache for this project should be cleared
        assert project_id not in agent_worker_state._tools_cache
