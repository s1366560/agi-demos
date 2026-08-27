"""Tests for SkillMCPManager."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.agent.mcp.skill_mcp_manager import (
    SkillMCPConfig,
    SkillMCPManager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FETCH_TOOL_RAW: dict[str, Any] = {
    "name": "fetch",
    "description": "Fetch a URL",
    "inputSchema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
}

SEARCH_TOOL_RAW: dict[str, Any] = {
    "name": "search",
    "description": "Search the web",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
    },
}


def _make_config(
    server_name: str = "fetch-server",
    command: str = "npx",
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    auto_start: bool = True,
) -> SkillMCPConfig:
    return SkillMCPConfig(
        server_name=server_name,
        command=command,
        args=args or ["-y", "@anthropic/mcp-server-fetch"],
        env=env or {},
        auto_start=auto_start,
    )


def _mock_client(
    tools: list[dict[str, Any]] | None = None,
    healthy: bool = True,
) -> MagicMock:
    """Create a mock MCPClient."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.list_tools = AsyncMock(return_value=tools or [FETCH_TOOL_RAW])
    client.health_check = AsyncMock(return_value=healthy)
    client.ping = AsyncMock(return_value=healthy)
    return client


@pytest.fixture()
def manager() -> SkillMCPManager:
    return SkillMCPManager()


@pytest.fixture()
def fetch_config() -> SkillMCPConfig:
    return _make_config()


@pytest.fixture()
def search_config() -> SkillMCPConfig:
    return _make_config(
        server_name="search-server",
        command="uvx",
        args=["mcp-server-search"],
    )


# ---------------------------------------------------------------------------
# SkillMCPConfig tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillMCPConfig:
    """Tests for the SkillMCPConfig frozen dataclass."""

    def test_create_minimal(self) -> None:
        config = SkillMCPConfig(server_name="s", command="cmd")
        assert config.server_name == "s"
        assert config.command == "cmd"
        assert config.args == []
        assert config.env == {}
        assert config.auto_start is True

    def test_create_full(self) -> None:
        config = SkillMCPConfig(
            server_name="fetch",
            command="npx",
            args=["-y", "pkg"],
            env={"KEY": "VAL"},
            auto_start=False,
        )
        assert config.server_name == "fetch"
        assert config.args == ["-y", "pkg"]
        assert config.env == {"KEY": "VAL"}
        assert config.auto_start is False

    def test_frozen(self) -> None:
        config = SkillMCPConfig(server_name="s", command="cmd")
        with pytest.raises(AttributeError):
            config.server_name = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegistration:
    """Tests for register/unregister operations."""

    def test_register_single(self, manager: SkillMCPManager, fetch_config: SkillMCPConfig) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config])
        assert "skill-a" in manager._skill_configs

    def test_register_multiple_configs(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
        search_config: SkillMCPConfig,
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config, search_config])
        assert len(manager._skill_configs["skill-a"]) == 2

    def test_register_empty_skill_id_raises(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        with pytest.raises(ValueError, match="skill_id cannot be empty"):
            manager.register_skill_mcps("", [fetch_config])

    def test_register_empty_configs_raises(self, manager: SkillMCPManager) -> None:
        with pytest.raises(ValueError, match="configs cannot be empty"):
            manager.register_skill_mcps("skill-a", [])

    def test_register_overwrites(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
        search_config: SkillMCPConfig,
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config])
        manager.register_skill_mcps("skill-a", [search_config])
        assert len(manager._skill_configs["skill-a"]) == 1
        assert manager._skill_configs["skill-a"][0].server_name == "search-server"

    def test_unregister_removes(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config])
        manager.unregister_skill_mcps("skill-a")
        assert "skill-a" not in manager._skill_configs

    def test_unregister_nonexistent_is_noop(self, manager: SkillMCPManager) -> None:
        manager.unregister_skill_mcps("no-such-skill")


# ---------------------------------------------------------------------------
# Activation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestActivation:
    """Tests for skill activation."""

    async def test_activate_starts_server(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client()
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            tools = await manager.activate_skill("skill-a")

        mock.connect.assert_awaited_once()
        mock.list_tools.assert_awaited_once()
        assert "skill-a" in manager.active_skills
        assert "fetch-server" in manager.active_servers
        assert len(tools) == 1
        assert tools[0].name == "fetch"

    async def test_activate_unregistered_raises(self, manager: SkillMCPManager) -> None:
        with pytest.raises(ValueError, match="No MCP configs registered"):
            await manager.activate_skill("unknown")

    async def test_activate_idempotent(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client()
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")
            tools = await manager.activate_skill("skill-a")

        # connect called only once
        mock.connect.assert_awaited_once()
        assert len(tools) == 1

    async def test_activate_skips_non_auto_start(self, manager: SkillMCPManager) -> None:
        config = _make_config(auto_start=False)
        manager.register_skill_mcps("skill-a", [config])

        tools = await manager.activate_skill("skill-a")

        assert "skill-a" in manager.active_skills
        assert "fetch-server" not in manager.active_servers
        assert tools == []

    async def test_activate_shared_server_increments_ref(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
    ) -> None:
        """Two skills share the same server -- refcount goes to 2."""
        config_b = _make_config(server_name="fetch-server")
        manager.register_skill_mcps("skill-a", [fetch_config])
        manager.register_skill_mcps("skill-b", [config_b])

        mock = _mock_client()
        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")
            await manager.activate_skill("skill-b")

        # connect called only once (shared server)
        mock.connect.assert_awaited_once()
        assert manager.get_server_refcount("fetch-server") == 2

    async def test_activate_rejects_conflicting_shared_server_configuration(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
    ) -> None:
        conflicting_config = _make_config(
            server_name="fetch-server",
            command="different-command",
            args=["--different"],
        )
        manager.register_skill_mcps("skill-a", [fetch_config])
        manager.register_skill_mcps("skill-b", [conflicting_config])
        client = _mock_client()

        with patch.object(manager, "_create_client", return_value=client):
            await manager.activate_skill("skill-a")
            with pytest.raises(RuntimeError, match="different configuration"):
                await manager.activate_skill("skill-b")

        client.connect.assert_awaited_once()
        assert manager.active_skills == frozenset({"skill-a"})
        assert manager.get_server_refcount("fetch-server") == 1

    async def test_activate_tool_discovery_failure_releases_client_and_propagates(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config])
        client = _mock_client()
        client.list_tools = AsyncMock(side_effect=RuntimeError("discovery failed"))

        with (
            patch.object(manager, "_create_client", return_value=client),
            pytest.raises(RuntimeError, match="discovery failed"),
        ):
            await manager.activate_skill("skill-a")

        client.disconnect.assert_awaited_once()
        assert manager.active_skills == frozenset()
        assert manager.active_servers == frozenset()
        assert manager.get_server_refcount("fetch-server") == 0
        assert "fetch-server" not in manager._server_tools

    async def test_activate_rollback_on_failure(self, manager: SkillMCPManager) -> None:
        """If a server fails to start, previous servers' refcounts roll back."""
        good_config = _make_config(server_name="good-server")
        bad_config = _make_config(server_name="bad-server", command="bad")

        manager.register_skill_mcps("skill-a", [good_config, bad_config])

        good_client = _mock_client()
        bad_client = _mock_client()
        bad_client.connect = AsyncMock(side_effect=RuntimeError("boom"))

        call_count = 0

        def create_client_side_effect(_config: SkillMCPConfig) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return good_client
            return bad_client

        with (
            patch.object(manager, "_create_client", side_effect=create_client_side_effect),
            pytest.raises(RuntimeError, match="boom"),
        ):
            await manager.activate_skill("skill-a")

        assert "skill-a" not in manager.active_skills
        good_client.disconnect.assert_awaited_once()
        assert manager.get_server_refcount("good-server") == 0
        assert "good-server" not in manager.active_servers

    async def test_activate_cancellation_during_tool_discovery_releases_client(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config])
        client = _mock_client()
        client.list_tools = AsyncMock(side_effect=asyncio.CancelledError())

        with (
            patch.object(manager, "_create_client", return_value=client),
            pytest.raises(asyncio.CancelledError),
        ):
            await manager.activate_skill("skill-a")

        client.disconnect.assert_awaited_once()
        assert manager.active_skills == frozenset()
        assert manager.active_servers == frozenset()
        assert manager.get_server_refcount("fetch-server") == 0

    async def test_activate_cancellation_rolls_back_prior_server_in_reverse_order(
        self,
        manager: SkillMCPManager,
    ) -> None:
        first_config = _make_config(server_name="first-server")
        second_config = _make_config(server_name="second-server")
        manager.register_skill_mcps("skill-a", [first_config, second_config])
        first_client = _mock_client()
        second_client = _mock_client()
        second_client.connect = AsyncMock(side_effect=asyncio.CancelledError())
        disconnect_order: list[str] = []

        async def disconnect_first() -> None:
            disconnect_order.append("first-server")

        async def disconnect_second() -> None:
            disconnect_order.append("second-server")

        first_client.disconnect = AsyncMock(side_effect=disconnect_first)
        second_client.disconnect = AsyncMock(side_effect=disconnect_second)
        clients = iter((first_client, second_client))

        with (
            patch.object(manager, "_create_client", side_effect=lambda _config: next(clients)),
            pytest.raises(asyncio.CancelledError),
        ):
            await manager.activate_skill("skill-a")

        first_client.disconnect.assert_awaited_once()
        second_client.disconnect.assert_awaited_once()
        assert disconnect_order == ["second-server", "first-server"]
        assert manager.active_servers == frozenset()
        assert manager.get_server_refcount("first-server") == 0
        assert manager.get_server_refcount("second-server") == 0

    async def test_activate_multiple_servers(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
        search_config: SkillMCPConfig,
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config, search_config])

        mock_fetch = _mock_client(tools=[FETCH_TOOL_RAW])
        mock_search = _mock_client(tools=[SEARCH_TOOL_RAW])

        call_count = 0

        def create_side_effect(_: SkillMCPConfig) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return mock_fetch if call_count == 1 else mock_search

        with patch.object(manager, "_create_client", side_effect=create_side_effect):
            tools = await manager.activate_skill("skill-a")

        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"fetch", "search"}


# ---------------------------------------------------------------------------
# Deactivation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeactivation:
    """Tests for skill deactivation."""

    async def test_deactivate_stops_server(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client()
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")
            await manager.deactivate_skill("skill-a")

        mock.disconnect.assert_awaited_once()
        assert "skill-a" not in manager.active_skills
        assert "fetch-server" not in manager.active_servers

    async def test_deactivate_inactive_is_noop(self, manager: SkillMCPManager) -> None:
        await manager.deactivate_skill("nonexistent")
        # No error raised

    async def test_deactivate_shared_server_keeps_running(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
    ) -> None:
        """Deactivating one skill doesn't stop a shared server."""
        config_b = _make_config(server_name="fetch-server")
        manager.register_skill_mcps("skill-a", [fetch_config])
        manager.register_skill_mcps("skill-b", [config_b])

        mock = _mock_client()
        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")
            await manager.activate_skill("skill-b")
            await manager.deactivate_skill("skill-a")

        # Server still running (refcount=1)
        mock.disconnect.assert_not_awaited()
        assert manager.get_server_refcount("fetch-server") == 1
        assert "fetch-server" in manager.active_servers

        # Deactivate second skill
        await manager.deactivate_skill("skill-b")
        mock.disconnect.assert_awaited_once()
        assert manager.get_server_refcount("fetch-server") == 0

    async def test_deactivate_non_auto_start_config(self, manager: SkillMCPManager) -> None:
        """Deactivating a skill with auto_start=False is clean."""
        config = _make_config(auto_start=False)
        manager.register_skill_mcps("skill-a", [config])
        await manager.activate_skill("skill-a")
        await manager.deactivate_skill("skill-a")
        assert "skill-a" not in manager.active_skills

    async def test_deactivate_cancellation_cleans_all_servers_in_reverse_order(
        self,
        manager: SkillMCPManager,
    ) -> None:
        first_config = _make_config(server_name="first-server")
        second_config = _make_config(server_name="second-server")
        manager.register_skill_mcps("skill-a", [first_config, second_config])
        first_client = _mock_client()
        second_client = _mock_client()
        disconnect_order: list[str] = []

        async def disconnect_first() -> None:
            disconnect_order.append("first-server")

        async def cancel_second() -> None:
            disconnect_order.append("second-server")
            raise asyncio.CancelledError

        first_client.disconnect = AsyncMock(side_effect=disconnect_first)
        second_client.disconnect = AsyncMock(side_effect=cancel_second)
        clients = iter((first_client, second_client))
        with patch.object(
            manager,
            "_create_client",
            side_effect=lambda _config: next(clients),
        ):
            await manager.activate_skill("skill-a")

        with pytest.raises(asyncio.CancelledError):
            await manager.deactivate_skill("skill-a")

        assert disconnect_order == ["second-server", "first-server"]
        assert manager.active_skills == frozenset()
        assert manager.active_servers == frozenset()
        assert manager.get_server_refcount("first-server") == 0
        assert manager.get_server_refcount("second-server") == 0


# ---------------------------------------------------------------------------
# get_skill_tools tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSkillTools:
    """Tests for get_skill_tools."""

    def test_no_configs_returns_empty(self, manager: SkillMCPManager) -> None:
        assert manager.get_skill_tools("no-such") == []

    async def test_returns_cached_tools(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client(tools=[FETCH_TOOL_RAW, SEARCH_TOOL_RAW])
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")

        tools = manager.get_skill_tools("skill-a")
        assert len(tools) == 2


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthCheck:
    """Tests for health_check and restart_server."""

    async def test_health_check_all_healthy(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client(healthy=True)
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")

        results = await manager.health_check()
        assert results == {"fetch-server": True}

    async def test_health_check_unhealthy(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client(healthy=False)
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")

        results = await manager.health_check()
        assert results == {"fetch-server": False}

    async def test_health_check_exception(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        mock = _mock_client()
        mock.health_check = AsyncMock(side_effect=RuntimeError("gone"))
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=mock):
            await manager.activate_skill("skill-a")

        results = await manager.health_check()
        assert results == {"fetch-server": False}

    async def test_health_check_empty(self, manager: SkillMCPManager) -> None:
        results = await manager.health_check()
        assert results == {}

    async def test_restart_server(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        old_mock = _mock_client()
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=old_mock):
            await manager.activate_skill("skill-a")

        new_mock = _mock_client(tools=[SEARCH_TOOL_RAW])
        with patch.object(manager, "_create_client", return_value=new_mock):
            result = await manager.restart_server("fetch-server")

        assert result is True
        old_mock.disconnect.assert_awaited_once()
        new_mock.connect.assert_awaited_once()
        # Tools should be refreshed
        tools = manager.get_skill_tools("skill-a")
        assert len(tools) == 1
        assert tools[0].name == "search"

    async def test_restart_nonexistent_returns_false(self, manager: SkillMCPManager) -> None:
        assert await manager.restart_server("nope") is False

    async def test_restart_failure_cleans_up(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        old_mock = _mock_client()
        manager.register_skill_mcps("skill-a", [fetch_config])

        with patch.object(manager, "_create_client", return_value=old_mock):
            await manager.activate_skill("skill-a")

        bad_mock = _mock_client()
        bad_mock.connect = AsyncMock(side_effect=RuntimeError("fail"))
        with patch.object(manager, "_create_client", return_value=bad_mock):
            result = await manager.restart_server("fetch-server")

        assert result is False
        assert "fetch-server" not in manager.active_servers

    async def test_restart_discovery_failure_disconnects_new_client(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
    ) -> None:
        old_client = _mock_client()
        manager.register_skill_mcps("skill-a", [fetch_config])
        with patch.object(manager, "_create_client", return_value=old_client):
            await manager.activate_skill("skill-a")

        new_client = _mock_client()
        new_client.list_tools = AsyncMock(side_effect=RuntimeError("discovery failed"))
        with patch.object(manager, "_create_client", return_value=new_client):
            result = await manager.restart_server("fetch-server")

        assert result is False
        old_client.disconnect.assert_awaited_once()
        new_client.disconnect.assert_awaited_once()
        assert "fetch-server" not in manager.active_servers
        assert "fetch-server" not in manager._active_server_configs


# ---------------------------------------------------------------------------
# Shutdown tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShutdown:
    """Tests for the shutdown method."""

    async def test_shutdown_disconnects_all(
        self,
        manager: SkillMCPManager,
        fetch_config: SkillMCPConfig,
        search_config: SkillMCPConfig,
    ) -> None:
        mock_fetch = _mock_client()
        mock_search = _mock_client()

        manager.register_skill_mcps("skill-a", [fetch_config])
        manager.register_skill_mcps("skill-b", [search_config])

        call_count = 0

        def create_side_effect(_: SkillMCPConfig) -> MagicMock:
            nonlocal call_count
            call_count += 1
            return mock_fetch if call_count == 1 else mock_search

        with patch.object(manager, "_create_client", side_effect=create_side_effect):
            await manager.activate_skill("skill-a")
            await manager.activate_skill("skill-b")

        await manager.shutdown()

        mock_fetch.disconnect.assert_awaited_once()
        mock_search.disconnect.assert_awaited_once()
        assert len(manager.active_skills) == 0
        assert len(manager.active_servers) == 0

    async def test_shutdown_empty_is_noop(self, manager: SkillMCPManager) -> None:
        await manager.shutdown()


# ---------------------------------------------------------------------------
# Internal helper tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInternalHelpers:
    """Tests for private helper methods."""

    def test_create_client_builds_stdio(self, manager: SkillMCPManager) -> None:
        config = _make_config(
            command="npx",
            args=["-y", "pkg"],
            env={"FOO": "bar"},
        )
        client = manager._create_client(config)
        assert client.server_type == "stdio"
        assert client.transport_config["command"] == "npx"
        assert client.transport_config["args"] == ["-y", "pkg"]
        assert client.transport_config["env"] == {"FOO": "bar"}

    def test_create_client_no_env(self, manager: SkillMCPManager) -> None:
        config = _make_config(env={})
        client = manager._create_client(config)
        assert "env" not in client.transport_config

    def test_find_config_for_server(
        self, manager: SkillMCPManager, fetch_config: SkillMCPConfig
    ) -> None:
        manager.register_skill_mcps("skill-a", [fetch_config])
        found = manager._find_config_for_server("fetch-server")
        assert found is not None
        assert found.server_name == "fetch-server"

    def test_find_config_for_server_not_found(self, manager: SkillMCPManager) -> None:
        assert manager._find_config_for_server("nope") is None

    async def test_safe_disconnect_suppresses_error(self, manager: SkillMCPManager) -> None:
        mock = _mock_client()
        mock.disconnect = AsyncMock(side_effect=RuntimeError("fail"))
        # Should not raise
        await manager._safe_disconnect(mock)

    async def test_cache_server_tools_propagates_error(self, manager: SkillMCPManager) -> None:
        mock = _mock_client()
        mock.list_tools = AsyncMock(side_effect=RuntimeError("no tools"))
        with pytest.raises(RuntimeError, match="no tools"):
            await manager._cache_server_tools("test-server", mock)
        assert "test-server" not in manager._server_tools

    def test_get_server_refcount_default(self, manager: SkillMCPManager) -> None:
        assert manager.get_server_refcount("nonexistent") == 0

    def test_properties_initial_state(self, manager: SkillMCPManager) -> None:
        assert manager.active_skills == frozenset()
        assert manager.active_servers == frozenset()
