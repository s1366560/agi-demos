"""Tests for inject_discovered_mcp_tools_into_cache in agent_worker_state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)

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


@pytest.fixture
async def generation_host() -> AsyncIterator[PlatformPluginRuntimeHostV2]:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=7,
        version=7,
        nonce="mcp-injection-generation-7",
    )
    try:
        yield host
    finally:
        await host.close()


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

    async def test_explicit_descriptor_without_lease_does_not_inject(
        self,
        generation_host: PlatformPluginRuntimeHostV2,
    ) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        distribution = generation_host.current_distribution
        assert distribution is not None
        mod._mcp_sandbox_adapter = MagicMock()

        with patch(
            "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
            new_callable=AsyncMock,
            return_value="sandbox-123",
        ) as resolve_sandbox:
            result = await inject_discovered_mcp_tools_into_cache(
                project_id="proj-1",
                server_name="test-server",
                discovered_tools=_make_discovered_tools(["tool_a"]),
                generation_descriptor=distribution.descriptor,
            )

        assert result == 0
        assert mod._tools_cache == {}
        resolve_sandbox.assert_not_awaited()

    async def test_returns_zero_when_no_sandbox_id(
        self,
        generation_host: PlatformPluginRuntimeHostV2,
    ) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()

        async with pin_operation_context_v2(
            generation_host,
            operation_id="mcp-injection-no-sandbox",
            scope=_ROOT_SCOPE,
        ) as operation:
            with patch(
                "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await inject_discovered_mcp_tools_into_cache(
                    project_id="proj-1",
                    server_name="test-server",
                    discovered_tools=_make_discovered_tools(["tool_a"]),
                    generation_descriptor=operation.descriptor,
                )
        assert result == 0

    async def test_injects_tools_into_empty_cache(
        self,
        generation_host: PlatformPluginRuntimeHostV2,
    ) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_session_pool import generation_cache_key_v2
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()
        async with pin_operation_context_v2(
            generation_host,
            operation_id="mcp-injection-empty-cache",
            scope=_ROOT_SCOPE,
        ) as operation:
            cache_key = generation_cache_key_v2(
                "proj-1",
                generation_descriptor=operation.descriptor,
            )
            mod._tools_cache.pop(cache_key, None)

            with patch(
                "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
                new_callable=AsyncMock,
                return_value="sandbox-123",
            ):
                result = await inject_discovered_mcp_tools_into_cache(
                    project_id="proj-1",
                    server_name="chrome-devtools",
                    discovered_tools=_make_discovered_tools(["navigate", "click"]),
                    generation_descriptor=operation.descriptor,
                )

            assert result == 2
            assert cache_key in mod._tools_cache
            cache = mod._tools_cache[cache_key]
            # Names follow mcp__{server}__{tool} convention with dashes replaced
            assert "mcp__chrome_devtools__navigate" in cache
            assert "mcp__chrome_devtools__click" in cache

    async def test_merges_with_existing_cache(
        self,
        generation_host: PlatformPluginRuntimeHostV2,
    ) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_session_pool import generation_cache_key_v2
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()
        async with pin_operation_context_v2(
            generation_host,
            operation_id="mcp-injection-merge-cache",
            scope=_ROOT_SCOPE,
        ) as operation:
            cache_key = generation_cache_key_v2(
                "proj-1",
                generation_descriptor=operation.descriptor,
            )
            existing_tool = MagicMock()
            existing_tool.name = "existing_tool"
            mod._tools_cache[cache_key] = {"existing_tool": existing_tool}

            with patch(
                "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
                new_callable=AsyncMock,
                return_value="sandbox-123",
            ):
                result = await inject_discovered_mcp_tools_into_cache(
                    project_id="proj-1",
                    server_name="my-server",
                    discovered_tools=_make_discovered_tools(["new_tool"]),
                    generation_descriptor=operation.descriptor,
                )

            assert result == 1
            cache = mod._tools_cache[cache_key]
            # Existing tool preserved
            assert "existing_tool" in cache
            assert cache["existing_tool"] is existing_tool
            # New tool added
            assert "mcp__my_server__new_tool" in cache

    async def test_skips_tools_with_empty_name(
        self,
        generation_host: PlatformPluginRuntimeHostV2,
    ) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_session_pool import generation_cache_key_v2
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )

        mod._mcp_sandbox_adapter = MagicMock()
        tools = [
            {"name": "valid_tool", "description": "ok", "inputSchema": {}},
            {"name": "", "description": "empty name", "inputSchema": {}},
            {"description": "no name key", "inputSchema": {}},
        ]

        async with pin_operation_context_v2(
            generation_host,
            operation_id="mcp-injection-empty-name",
            scope=_ROOT_SCOPE,
        ) as operation:
            cache_key = generation_cache_key_v2(
                "proj-1",
                generation_descriptor=operation.descriptor,
            )
            with patch(
                "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
                new_callable=AsyncMock,
                return_value="sandbox-123",
            ):
                result = await inject_discovered_mcp_tools_into_cache(
                    project_id="proj-1",
                    server_name="srv",
                    discovered_tools=tools,
                    generation_descriptor=operation.descriptor,
                )

            assert result == 1
            cache = mod._tools_cache[cache_key]
            assert "mcp__srv__valid_tool" in cache

    async def test_adapter_instances_are_correct_type(
        self,
        generation_host: PlatformPluginRuntimeHostV2,
    ) -> None:
        import src.infrastructure.agent.state.agent_worker_state as mod
        from src.infrastructure.agent.state.agent_session_pool import generation_cache_key_v2
        from src.infrastructure.agent.state.agent_worker_state import (
            inject_discovered_mcp_tools_into_cache,
        )
        from src.infrastructure.mcp.sandbox_tool_adapter import SandboxMCPServerToolAdapter

        mod._mcp_sandbox_adapter = MagicMock()

        async with pin_operation_context_v2(
            generation_host,
            operation_id="mcp-injection-adapter-type",
            scope=_ROOT_SCOPE,
        ) as operation:
            cache_key = generation_cache_key_v2(
                "proj-1",
                generation_descriptor=operation.descriptor,
            )
            with patch(
                "src.infrastructure.agent.state.agent_worker_state._resolve_project_sandbox_id",
                new_callable=AsyncMock,
                return_value="sandbox-123",
            ):
                await inject_discovered_mcp_tools_into_cache(
                    project_id="proj-1",
                    server_name="test-srv",
                    discovered_tools=_make_discovered_tools(["my_tool"]),
                    generation_descriptor=operation.descriptor,
                )

            cache = mod._tools_cache[cache_key]
            adapter = cache["mcp__test_srv__my_tool"]
            assert isinstance(adapter, SandboxMCPServerToolAdapter)
