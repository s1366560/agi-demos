"""Unit tests for SandboxToolRegistry.

TDD Phase 2: Write failing tests first (RED).
Tests the sandbox tool registry for managing dynamic tool registration.
"""

import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.application.services.sandbox_tool_registry import (
    SandboxToolRegistration,
    SandboxToolRegistry,
)


class TestSandboxToolRegistration:
    """Test SandboxToolRegistration dataclass."""

    def test_creation(self):
        """Test registration creation."""
        now = datetime.now()
        registration = SandboxToolRegistration(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tool_names=["bash", "file_read"],
            registered_at=now,
        )

        assert registration.sandbox_id == "abc123"
        assert registration.project_id == "proj-1"
        assert registration.tenant_id == "tenant-1"
        assert registration.tool_names == ["bash", "file_read"]
        assert registration.registered_at == now

    def test_age_seconds(self):
        """Test age calculation."""
        now = datetime.now()
        registration = SandboxToolRegistration(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            registered_at=now - timedelta(seconds=30),
        )

        # Allow for small timing differences
        age = registration.age_seconds()
        assert 29 <= age <= 31

    def test_age_seconds_zero(self):
        """Test age calculation for fresh registration."""
        registration = SandboxToolRegistration(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
        )

        # Fresh registration should have age close to 0
        age = registration.age_seconds()
        assert age >= 0
        assert age < 1  # Less than 1 second


class TestSandboxToolRegistry:
    """Test SandboxToolRegistry service."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        redis.sadd = AsyncMock()
        redis.srem = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        return redis

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock MCP adapter."""
        adapter = AsyncMock()
        adapter.list_tools = AsyncMock(
            return_value=[
                {"name": "bash", "description": "Execute bash"},
                {"name": "file_read", "description": "Read file"},
            ]
        )
        return adapter

    @pytest.fixture
    def registry(self, mock_redis, mock_adapter):
        """Create registry with mocked dependencies."""
        return SandboxToolRegistry(
            redis_client=mock_redis,
            mcp_adapter=mock_adapter,
        )

    @pytest.mark.asyncio
    async def test_register_sandbox_tools_with_tools(self, registry, mock_adapter):
        """Test registering tools with provided tool list."""
        tools = await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash", "file_read"],
        )

        assert tools == ["bash", "file_read"]
        assert "abc123" in registry._registrations
        assert registry._registrations["abc123"].tool_names == ["bash", "file_read"]

    @pytest.mark.asyncio
    async def test_register_sandbox_tools_fetch_from_adapter(self, registry, mock_adapter):
        """Test registering tools fetches from adapter when not provided."""
        mock_adapter.list_tools.return_value = [
            {"name": "bash", "description": "Execute bash"},
            {"name": "file_write", "description": "Write file"},
        ]

        tools = await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=None,  # Should fetch from adapter
        )

        assert tools == ["bash", "file_write"]
        mock_adapter.list_tools.assert_called_once_with("abc123")

    @pytest.mark.asyncio
    async def test_register_sandbox_tools_adapter_error(self, registry, mock_adapter, caplog):
        """Test handling adapter error gracefully."""
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")
        mock_adapter.list_tools.side_effect = Exception("secret connection token")

        tools = await registry.register_sandbox_tools(
            sandbox_id="secret-sandbox-id",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=None,
        )

        assert tools is None or tools == []
        # Registration should not be created on error
        assert "secret-sandbox-id" not in registry._registrations

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "Failed to fetch tools" in message
        assert "secret-sandbox-id" not in message
        assert "secret connection token" not in message
        assert "has_sandbox_id=True" in message
        assert "error_type=Exception" in message

    @pytest.mark.asyncio
    async def test_register_sandbox_tools_no_tools_log_omits_sandbox_id(self, registry, caplog):
        """Test no-tools warning does not expose sandbox identifiers."""
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")

        tools = await registry.register_sandbox_tools(
            sandbox_id="secret-sandbox-id",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=[],
        )

        assert tools == []
        assert "secret-sandbox-id" not in registry._registrations

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "No tools to register" in message
        assert "secret-sandbox-id" not in message
        assert "has_sandbox_id=True" in message

    @pytest.mark.asyncio
    async def test_unregister_sandbox_tools(self, registry):
        """Test unregistering sandbox tools."""
        # First register
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        # Then unregister
        result = await registry.unregister_sandbox_tools("abc123")

        assert result is True
        assert "abc123" not in registry._registrations

    @pytest.mark.asyncio
    async def test_unregister_sandbox_tools_not_found(self, registry, caplog):
        """Test unregistering non-existent sandbox."""
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")

        result = await registry.unregister_sandbox_tools("secret-missing-sandbox")

        assert result is False

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "not found in registry" in message
        assert "secret-missing-sandbox" not in message
        assert "has_sandbox_id=True" in message

    @pytest.mark.asyncio
    async def test_get_sandbox_tools(self, registry):
        """Test getting tools for a sandbox."""
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash", "file_read"],
        )

        tools = await registry.get_sandbox_tools("abc123")

        assert tools == ["bash", "file_read"]

    @pytest.mark.asyncio
    async def test_get_sandbox_tools_not_found(self, registry):
        """Test getting tools for non-existent sandbox."""
        tools = await registry.get_sandbox_tools("nonexistent")

        assert tools is None

    @pytest.mark.asyncio
    async def test_get_project_sandboxes(self, registry):
        """Test getting all sandboxes for a project."""
        # Register multiple sandboxes for same project
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )
        await registry.register_sandbox_tools(
            sandbox_id="def456",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )
        # Different project
        await registry.register_sandbox_tools(
            sandbox_id="xyz789",
            project_id="proj-2",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        sandboxes = await registry.get_project_sandboxes("proj-1")

        assert set(sandboxes) == {"abc123", "def456"}

    @pytest.mark.asyncio
    async def test_is_sandbox_active(self, registry):
        """Test checking if sandbox is active."""
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        # Fresh registration should be active
        assert registry.is_sandbox_active("abc123") is True

        # Non-existent sandbox should be inactive
        assert registry.is_sandbox_active("nonexistent") is False

    def test_is_sandbox_active_expired(self, registry):
        """Test checking if sandbox registration is expired."""
        # Create expired registration manually
        old_time = datetime.now() - timedelta(seconds=3700)  # > 1 hour
        registry._registrations["old_sandbox"] = SandboxToolRegistration(
            sandbox_id="old_sandbox",
            project_id="proj-1",
            tenant_id="tenant-1",
            registered_at=old_time,
        )

        assert registry.is_sandbox_active("old_sandbox", max_age_seconds=3600) is False
        assert registry.is_sandbox_active("old_sandbox", max_age_seconds=4000) is True

    @pytest.mark.asyncio
    async def test_cleanup_expired_registrations(self, registry):
        """Test automatic cleanup of expired registrations."""
        # Add an expired registration
        old_time = datetime.now() - timedelta(seconds=3700)
        registry._registrations["expired"] = SandboxToolRegistration(
            sandbox_id="expired",
            project_id="proj-1",
            tenant_id="tenant-1",
            registered_at=old_time,
        )
        # Add a fresh registration
        await registry.register_sandbox_tools(
            sandbox_id="fresh",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        count = await registry.cleanup_expired_registrations(max_age_seconds=3600)

        assert count == 1
        assert "expired" not in registry._registrations
        assert "fresh" in registry._registrations

    @pytest.mark.asyncio
    async def test_save_to_redis(self, registry, mock_redis):
        """Test saving registration to Redis."""
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        # Verify Redis calls
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert "sandbox:tools:abc123" in call_args[0][0]
        mock_redis.sadd.assert_called()  # Called for tracking and project index

    @pytest.mark.asyncio
    async def test_save_to_redis_failure_log_omits_identifiers(
        self, registry, mock_redis, caplog
    ):
        """Test Redis save failures do not log sensitive registration details."""
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")
        mock_redis.set.side_effect = RuntimeError(
            "redis save failed secret-sandbox-id secret-project-id secret-tool-name"
        )

        tools = await registry.register_sandbox_tools(
            sandbox_id="secret-sandbox-id",
            project_id="secret-project-id",
            tenant_id="tenant-1",
            tools=["secret-tool-name"],
        )

        assert tools == ["secret-tool-name"]

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "Failed to save to Redis" in message
        assert "secret-sandbox-id" not in message
        assert "secret-project-id" not in message
        assert "secret-tool-name" not in message
        assert "redis save failed" not in message
        assert "has_sandbox_id=True" in message
        assert "has_project_id=True" in message
        assert "error_type=RuntimeError" in message

    @pytest.mark.asyncio
    async def test_clear_from_redis(self, registry, mock_redis):
        """Test clearing registration from Redis."""
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        # Clear the registration
        await registry.unregister_sandbox_tools("abc123")

        # Verify Redis cleanup
        mock_redis.delete.assert_called_once()
        assert "sandbox:tools:abc123" in mock_redis.delete.call_args[0][0]
        mock_redis.srem.assert_called()  # Called for tracking and project index

    @pytest.mark.asyncio
    async def test_clear_from_redis_failure_log_omits_identifiers(
        self, registry, mock_redis, caplog
    ):
        """Test Redis clear failures do not log sandbox or project identifiers."""
        await registry.register_sandbox_tools(
            sandbox_id="secret-sandbox-id",
            project_id="secret-project-id",
            tenant_id="tenant-1",
            tools=["bash"],
        )
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")
        caplog.clear()
        mock_redis.delete.side_effect = RuntimeError(
            "redis clear failed secret-sandbox-id secret-project-id"
        )

        result = await registry.unregister_sandbox_tools("secret-sandbox-id")

        assert result is True

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "Failed to clear from Redis" in message
        assert "secret-sandbox-id" not in message
        assert "secret-project-id" not in message
        assert "redis clear failed" not in message
        assert "has_sandbox_id=True" in message
        assert "has_project_id=True" in message
        assert "error_type=RuntimeError" in message

    @pytest.mark.asyncio
    async def test_restore_from_redis(self, registry, mock_redis):
        """Test restoring registration from Redis."""
        # First register to save to Redis
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash", "file_read"],
        )

        # Clear from memory but keep in Redis mock
        registry._registrations.clear()

        # Mock Redis get to return registration data
        import json
        from datetime import datetime

        registration_data = {
            "sandbox_id": "abc123",
            "project_id": "proj-1",
            "tenant_id": "tenant-1",
            "tool_names": ["bash", "file_read"],
            "registered_at": datetime.now().isoformat(),
        }

        async def mock_get(key):
            if "abc123" in key:
                return json.dumps(registration_data)
            return None

        mock_redis.get = mock_get

        # Restore from Redis
        result = await registry.restore_from_redis("abc123")

        assert result is True
        assert "abc123" in registry._registrations
        assert registry._registrations["abc123"].tool_names == ["bash", "file_read"]

    @pytest.mark.asyncio
    async def test_restore_from_redis_not_found(self, registry, mock_redis):
        """Test restoring when registration not in Redis."""
        mock_redis.get = AsyncMock(return_value=None)

        result = await registry.restore_from_redis("nonexistent")

        assert result is False
        assert "nonexistent" not in registry._registrations

    @pytest.mark.asyncio
    async def test_load_from_redis_failure_log_omits_identifier(self, registry, mock_redis, caplog):
        """Test Redis load failures do not log sandbox IDs or exception text."""
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")
        mock_redis.get.side_effect = RuntimeError("redis load failed secret-sandbox-id")

        registration = await registry.load_from_redis("secret-sandbox-id")

        assert registration is None

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "Failed to load from Redis" in message
        assert "secret-sandbox-id" not in message
        assert "redis load failed" not in message
        assert "has_sandbox_id=True" in message
        assert "error_type=RuntimeError" in message

    @pytest.mark.asyncio
    async def test_restore_already_in_memory(self, registry):
        """Test restoring when already in memory."""
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        # Should return True even without Redis
        result = await registry.restore_from_redis("abc123")

        assert result is True

    @pytest.mark.asyncio
    async def test_refresh_all_from_redis(self, registry, mock_redis):
        """Test refreshing all registrations from Redis."""
        import json
        from datetime import datetime

        # Mock smembers to return sandbox IDs
        mock_redis.smembers = AsyncMock(return_value={"abc123", "def456"})

        registration_data = {
            "sandbox_id": "abc123",
            "project_id": "proj-1",
            "tenant_id": "tenant-1",
            "tool_names": ["bash"],
            "registered_at": datetime.now().isoformat(),
        }

        async def mock_get(key):
            if "abc123" in key:
                return json.dumps(registration_data)
            return None

        mock_redis.get = mock_get

        # Refresh all
        count = await registry.refresh_all_from_redis()

        # Only abc123 will be restored (def456 not in Redis)
        assert count == 1
        assert "abc123" in registry._registrations

    @pytest.mark.asyncio
    async def test_refresh_all_from_redis_failure_log_omits_exception_text(
        self, registry, mock_redis, caplog
    ):
        """Test Redis refresh failures log only structural error details."""
        caplog.set_level(logging.WARNING, logger="src.application.services.sandbox_tool_registry")
        mock_redis.smembers.side_effect = RuntimeError("redis refresh failed secret-tracking-key")

        count = await registry.refresh_all_from_redis()

        assert count == 0

        message = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name == "src.application.services.sandbox_tool_registry"
        )
        assert "Failed to refresh from Redis" in message
        assert "secret-tracking-key" not in message
        assert "redis refresh failed" not in message
        assert "error_type=RuntimeError" in message

    @pytest.mark.asyncio
    async def test_get_or_restore_registration_from_memory(self, registry):
        """Test get_or_restore returns from memory when available."""
        await registry.register_sandbox_tools(
            sandbox_id="abc123",
            project_id="proj-1",
            tenant_id="tenant-1",
            tools=["bash"],
        )

        registration = await registry.get_or_restore_registration("abc123")

        assert registration is not None
        assert registration.sandbox_id == "abc123"

    @pytest.mark.asyncio
    async def test_get_or_restore_registration_from_redis(self, registry, mock_redis):
        """Test get_or_restore loads from Redis when not in memory."""
        import json
        from datetime import datetime

        registration_data = {
            "sandbox_id": "abc123",
            "project_id": "proj-1",
            "tenant_id": "tenant-1",
            "tool_names": ["bash"],
            "registered_at": datetime.now().isoformat(),
        }

        async def mock_get(key):
            if "abc123" in key:
                return json.dumps(registration_data)
            return None

        mock_redis.get = mock_get

        # Not in memory, should restore from Redis
        registration = await registry.get_or_restore_registration("abc123")

        assert registration is not None
        assert registration.sandbox_id == "abc123"
        assert "abc123" in registry._registrations
