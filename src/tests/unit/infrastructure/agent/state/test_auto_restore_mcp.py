"""
Tests for _auto_restore_mcp_servers with distributed lock.

Tests the P1 fix: Auto-restore race condition using Redis distributed lock.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Test fixtures and helpers
@dataclass
class MockMCPServer:
    """Mock MCP server entity."""

    id: str
    name: str
    project_id: str
    server_type: str = "stdio"
    transport_config: Dict[str, Any] = None
    enabled: bool = True

    def __post_init__(self):
        if self.transport_config is None:
            self.transport_config = {}


@dataclass
class MockLockHandle:
    """Mock lock handle for testing."""

    key: str
    owner: str
    acquired_at: float
    ttl: int


# Patch paths for imports inside the function
REPO_PATCH_PATH = "src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository.SqlMCPServerRepository"
SESSION_FACTORY_PATCH_PATH = "src.infrastructure.adapters.secondary.persistence.database.async_session_factory"


class TestAutoRestoreMCPServersWithLock:
    """Test _auto_restore_mcp_servers with distributed lock protection."""

    @pytest.fixture
    def mock_sandbox_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client for lock operations."""
        client = AsyncMock()
        # Mock SET NX EX for lock acquisition
        client.set = AsyncMock(return_value=True)
        # Mock Lua script execution for release
        client.evalsha = AsyncMock(return_value=1)
        client.register_script = MagicMock(return_value=MagicMock())
        return client

    @pytest.fixture
    def mock_lock_adapter(self, mock_redis_client):
        """Create a mock distributed lock adapter."""
        from src.domain.ports.services.distributed_lock_port import LockHandle
        from src.infrastructure.adapters.secondary.cache.redis_lock_adapter import (
            RedisDistributedLockAdapter,
        )

        adapter = RedisDistributedLockAdapter(
            redis=mock_redis_client,
            namespace="memstack:lock",
            default_ttl=60,
        )
        return adapter

    @pytest.fixture
    def db_servers(self):
        """Sample MCP servers from DB."""
        return [
            MockMCPServer(
                id="server-1",
                name="filesystem-server",
                project_id="proj-1",
                server_type="stdio",
                transport_config={"command": "mcp-filesystem"},
            ),
            MockMCPServer(
                id="server-2",
                name="git-server",
                project_id="proj-1",
                server_type="stdio",
                transport_config={"command": "mcp-git"},
            ),
        ]

    @pytest.mark.unit
    async def test_auto_restore_with_lock_skips_if_cannot_acquire(
        self, mock_sandbox_adapter, mock_redis_client, db_servers
    ):
        """Test that auto-restore skips a server if lock cannot be acquired."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        # Setup: Lock acquisition fails (another worker holds it)
        mock_redis_client.set = AsyncMock(return_value=None)  # SET NX returns None

        # Mock DB repository - patch where it's imported (inside the function)
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                # Execute - with no running servers, should try to restore both
                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-1",
                    running_names=set(),
                    redis_client=mock_redis_client,
                )

        # Verify: No install/start calls because lock acquisition failed
        assert mock_sandbox_adapter.call_tool.call_count == 0

    @pytest.mark.unit
    async def test_auto_restore_with_lock_success(
        self, mock_sandbox_adapter, mock_redis_client, db_servers
    ):
        """Test that auto-restore proceeds when lock is acquired."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        # Setup: Lock acquisition succeeds
        mock_redis_client.set = AsyncMock(return_value=True)  # SET NX returns OK
        mock_redis_client.get = AsyncMock(return_value=None)  # No existing lock

        # Mock call_tool responses:
        # - mcp_server_list (for double-check) - no servers running
        # - install server 1
        # - start server 1
        # - mcp_server_list (for double-check of server 2) - no servers running
        # - install server 2
        # - start server 2
        empty_list_response = {
            "is_error": False,
            "content": [{"type": "text", "text": json.dumps({"servers": []})}],
        }
        mock_sandbox_adapter.call_tool = AsyncMock(
            side_effect=[
                empty_list_response,  # double-check for server 1
                {"is_error": False, "content": [{"type": "text", "text": "installed"}]},
                {"is_error": False, "content": [{"type": "text", "text": "started"}]},
                empty_list_response,  # double-check for server 2
                {"is_error": False, "content": [{"type": "text", "text": "installed"}]},
                {"is_error": False, "content": [{"type": "text", "text": "started"}]},
            ]
        )

        # Mock DB repository - patch where it's imported
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                # Execute
                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-1",
                    running_names=set(),
                    redis_client=mock_redis_client,
                )

        # Verify install calls
        install_calls = [
            c
            for c in mock_sandbox_adapter.call_tool.call_args_list
            if c.kwargs.get("tool_name") == "mcp_server_install"
        ]
        assert len(install_calls) == 2

        # Verify start calls
        start_calls = [
            c
            for c in mock_sandbox_adapter.call_tool.call_args_list
            if c.kwargs.get("tool_name") == "mcp_server_start"
        ]
        assert len(start_calls) == 2

    @pytest.mark.unit
    async def test_auto_restore_double_check_skips_running_server(
        self, mock_sandbox_adapter, mock_redis_client
    ):
        """Test that server already in running_names is skipped (no restore needed)."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        # Server in DB but already running
        db_servers = [
            MockMCPServer(
                id="server-1",
                name="filesystem-server",
                project_id="proj-1",
            )
        ]

        # Setup: Lock acquisition succeeds
        mock_redis_client.set = AsyncMock(return_value=True)

        # Mock DB repository
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                # Execute - server is in running_names (no restore needed)
                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-1",
                    running_names={"filesystem-server"},  # Already running
                    redis_client=mock_redis_client,
                )

        # Verify: No install/start calls because server is already in running_names
        install_start_calls = [
            c
            for c in mock_sandbox_adapter.call_tool.call_args_list
            if c.kwargs.get("tool_name") in ["mcp_server_install", "mcp_server_start"]
        ]
        # Server is already in running_names, so it's filtered out before lock attempt
        assert len(install_start_calls) == 0

    @pytest.mark.unit
    async def test_auto_restore_without_lock_fallback(self, mock_sandbox_adapter, db_servers):
        """Test that auto-restore works without redis_client (backward compatible)."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        # Mock successful install and start
        mock_sandbox_adapter.call_tool = AsyncMock(
            return_value={"is_error": False, "content": [{"type": "text", "text": "ok"}]}
        )

        # Mock DB repository
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                # Execute WITHOUT redis_client (fallback mode)
                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-1",
                    running_names=set(),
                    redis_client=None,  # No lock - backward compatible
                )

        # Verify: Install and start were called (fallback without lock)
        assert mock_sandbox_adapter.call_tool.call_count == 4  # 2 servers * 2 calls each

    @pytest.mark.unit
    async def test_auto_restore_lock_key_format(self, mock_sandbox_adapter, mock_redis_client):
        """Test that lock key has correct format: memstack:lock:mcp_restore:{project_id}:{server_name}."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        db_servers = [
            MockMCPServer(id="server-1", name="my-server", project_id="proj-123")
        ]

        # Track lock key used
        lock_keys_used = []

        async def mock_set(key, value, nx=None, ex=None):
            lock_keys_used.append(key)
            return True

        mock_redis_client.set = mock_set

        # Mock successful calls
        mock_sandbox_adapter.call_tool = AsyncMock(
            return_value={"is_error": False, "content": [{"type": "text", "text": "ok"}]}
        )

        # Mock DB repository
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-123",
                    running_names=set(),
                    redis_client=mock_redis_client,
                )

        # Verify lock key format
        assert len(lock_keys_used) == 1
        expected_key = "memstack:lock:mcp_restore:proj-123:my-server"
        assert lock_keys_used[0] == expected_key

    @pytest.mark.unit
    async def test_auto_restore_lock_ttl_is_60_seconds(
        self, mock_sandbox_adapter, mock_redis_client
    ):
        """Test that lock TTL is 60 seconds as specified."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        db_servers = [
            MockMCPServer(id="server-1", name="test-server", project_id="proj-1")
        ]

        # Track TTL used
        ttl_used = []

        async def mock_set(key, value, nx=None, ex=None):
            ttl_used.append(ex)
            return True

        mock_redis_client.set = mock_set

        # Mock successful calls
        mock_sandbox_adapter.call_tool = AsyncMock(
            return_value={"is_error": False, "content": [{"type": "text", "text": "ok"}]}
        )

        # Mock DB repository
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-1",
                    running_names=set(),
                    redis_client=mock_redis_client,
                )

        # Verify TTL is 60 seconds
        assert len(ttl_used) == 1
        assert ttl_used[0] == 60

    @pytest.mark.unit
    async def test_auto_restore_partial_failure_continues(
        self, mock_sandbox_adapter, mock_redis_client
    ):
        """Test that failure to restore one server doesn't block others."""
        from src.infrastructure.agent.state.agent_worker_state import (
            _auto_restore_mcp_servers,
        )

        db_servers = [
            MockMCPServer(id="server-1", name="failing-server", project_id="proj-1"),
            MockMCPServer(id="server-2", name="working-server", project_id="proj-1"),
        ]

        # Lock acquisition succeeds for both
        mock_redis_client.set = AsyncMock(return_value=True)

        # Track calls
        install_calls_made = []

        # Create a mock that tracks calls and returns appropriate responses
        async def mock_call_tool(**kwargs):
            tool_name = kwargs.get("tool_name")
            if tool_name == "mcp_server_install":
                server_name = kwargs.get("arguments", {}).get("name")
                install_calls_made.append(server_name)
                if server_name == "failing-server":
                    return {"is_error": True, "content": [{"type": "text", "text": "error"}]}
            if tool_name == "mcp_server_list":
                return {"is_error": False, "content": [{"type": "text", "text": json.dumps({"servers": []})}]}
            return {"is_error": False, "content": [{"type": "text", "text": "ok"}]}

        mock_sandbox_adapter.call_tool = AsyncMock(side_effect=mock_call_tool)

        # Mock DB repository
        with patch(REPO_PATCH_PATH) as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_project = AsyncMock(return_value=db_servers)
            mock_repo_class.return_value = mock_repo

            with patch(SESSION_FACTORY_PATCH_PATH) as mock_session_factory:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_session_factory.return_value = mock_session

                await _auto_restore_mcp_servers(
                    sandbox_adapter=mock_sandbox_adapter,
                    sandbox_id="sandbox-1",
                    project_id="proj-1",
                    running_names=set(),
                    redis_client=mock_redis_client,
                )

        # Verify: Both servers were attempted (partial failure continues)
        assert len(install_calls_made) == 2
        assert "failing-server" in install_calls_made
        assert "working-server" in install_calls_made
