"""Tests for inject_discovered_mcp_tools_into_cache in agent_worker_state."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discovered_tools(names: list[str]) -> list[dict[str, Any]]:
    """Create minimal discovered_tools payloads matching MCP discovery format."""
    return [
        {
            "name": name,
            "description": f"Tool {name}",
            "inputSchema": {"type": "object", "properties": {}},
        }
        for name in names
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInjectDiscoveredMCPToolsIntoCache:
    """Test suite for inject_discovered_mcp_tools_into_cache."""

    @pytest.fixture(autouse=True)
    def _clean_module_state(self) -> Any:
        """Reset module-level caches before each test."""
        import src.infrastructure.agent.state.agent_worker_state as mod

        original_cache = mod._tools_cache.copy()
        original_adapter = mod._mcp_sandbox_adapter
        yield
        mod._tools_cache.clear()
        mod._tools_cache.update(original_cache)
        mod._mcp_sandbox_adapter = original_adapter

    async def test_returns_zero_when_no_discovered_tools(self) -> None:
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        result = await inject_discovered_mcp_tools_into_cache(
            project_id="proj-1",
            server_name="test-server",
            discovered_tools=[],
        )
        assert result == 0

    async def test_returns_zero_when_no_sandbox_adapter(self) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = None
        result = await inject_discovered_mcp_tools_into_cache(
            project_id="proj-1",
            server_name="test-server",
            discovered_tools=_make_discovered_tools(["tool_a"]),
        )
        assert result == 0

    async def test_returns_zero_when_no_sandbox_id(self) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()

        with patch(
            "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await inject_discovered_mcp_tools_into_cache(
                project_id="proj-1",
                server_name="test-server",
                discovered_tools=_make_discovered_tools(["tool_a"]),
            )
        assert result == 0

    async def test_injects_tools_into_empty_cache(self) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()
        mod._tools_cache.pop("proj-1", None)

        with patch(
            "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
            new_callable=AsyncMock,
            return_value="sandbox-123",
        ):
            result = await inject_discovered_mcp_tools_into_cache(
                project_id="proj-1",
                server_name="chrome-devtools",
                discovered_tools=_make_discovered_tools(["navigate", "click"]),
            )

        assert result == 2
        assert "proj-1" in mod._tools_cache
        cache = mod._tools_cache["proj-1"]
        # Names follow mcp__{server}__{tool} convention with dashes replaced
        assert "mcp__chrome_devtools__navigate" in cache
        assert "mcp__chrome_devtools__click" in cache

    async def test_merges_with_existing_cache(self) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()
        existing_tool = MagicMock()
        existing_tool.name = "existing_tool"
        mod._tools_cache["proj-1"] = {"existing_tool": existing_tool}

        with patch(
            "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
            new_callable=AsyncMock,
            return_value="sandbox-123",
        ):
            result = await inject_discovered_mcp_tools_into_cache(
                project_id="proj-1",
                server_name="my-server",
                discovered_tools=_make_discovered_tools(["new_tool"]),
            )

        assert result == 1
        cache = mod._tools_cache["proj-1"]
        # Existing tool preserved
        assert "existing_tool" in cache
        assert cache["existing_tool"] is existing_tool
        # New tool added
        assert "mcp__my_server__new_tool" in cache

    async def test_skips_tools_with_empty_name(self) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()
        tools = [
            {"name": "valid_tool", "description": "ok", "inputSchema": {}},
            {"name": "", "description": "empty name", "inputSchema": {}},
            {"description": "no name key", "inputSchema": {}},
        ]

        with patch(
            "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
            new_callable=AsyncMock,
            return_value="sandbox-123",
        ):
            result = await inject_discovered_mcp_tools_into_cache(
                project_id="proj-1",
                server_name="srv",
                discovered_tools=tools,
            )

        assert result == 1
        cache = mod._tools_cache["proj-1"]
        assert "mcp__srv__valid_tool" in cache

    async def test_adapter_instances_are_correct_type(self) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mod._mcp_sandbox_adapter = MagicMock()

        with patch(
            "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
            new_callable=AsyncMock,
            return_value="sandbox-123",
        ):
            await inject_discovered_mcp_tools_into_cache(
                project_id="proj-1",
                server_name="test-srv",
                discovered_tools=_make_discovered_tools(["my_tool"]),
            )

        cache = mod._tools_cache["proj-1"]
        adapter = cache["mcp__test_srv__my_tool"]
        assert isinstance(adapter, SandboxMCPServerToolAdapter)
