"""Unit tests for MCPSandboxAdapter resource management features.

TDD: Tests written first (RED phase).
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
    MCPSandboxInstance,
)


class TestSandboxConcurrencyLimit:
    """Test sandbox concurrency limit and queue mechanism."""

    @pytest.fixture
    def adapter(self):
        """Create adapter with concurrency limit."""
        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter(
                max_concurrent_sandboxes=2,
            )
            return adapter

    def test_max_concurrent_property(self, adapter):
        """Test that max_concurrent property is set correctly."""
        assert adapter.max_concurrent == 2

    def test_active_count_returns_zero_for_new_adapter(self, adapter):
        """Test that active_count returns 0 for new adapter."""
        assert adapter.active_count == 0

    def test_active_count_increases_with_sandboxes(self, adapter):
        """Test that active_count increases when sandboxes are added."""
        # Simulate adding sandboxes
        adapter._active_sandboxes["test-1"] = Mock(
            id="test-1",
            status=SandboxStatus.RUNNING,
        )
        adapter._active_sandboxes["test-2"] = Mock(
            id="test-2",
            status=SandboxStatus.RUNNING,
        )

        assert adapter.active_count == 2

    def test_active_count_excludes_stopped_sandboxes(self, adapter):
        """Test that active_count excludes stopped sandboxes."""
        adapter._active_sandboxes["test-1"] = Mock(
            id="test-1",
            status=SandboxStatus.RUNNING,
        )
        adapter._active_sandboxes["test-2"] = Mock(
            id="test-2",
            status=SandboxStatus.STOPPED,
        )
        adapter._active_sandboxes["test-3"] = Mock(
            id="test-3",
            status=SandboxStatus.TERMINATED,
        )

        assert adapter.active_count == 1

    def test_can_create_sandbox_when_under_limit(self, adapter):
        """Test that can_create_sandbox returns True when under limit."""
        adapter._active_sandboxes["test-1"] = Mock(status=SandboxStatus.RUNNING)

        assert adapter.can_create_sandbox() is True

    def test_cannot_create_sandbox_when_at_limit(self, adapter):
        """Test that can_create_sandbox returns False when at limit."""
        adapter._active_sandboxes["test-1"] = Mock(status=SandboxStatus.RUNNING)
        adapter._active_sandboxes["test-2"] = Mock(status=SandboxStatus.RUNNING)

        assert adapter.can_create_sandbox() is False

    def test_queue_sandbox_request_adds_to_queue(self, adapter):
        """Test that queue_sandbox_request adds to pending queue."""
        # Use a real dict instead of Mock since queue_sandbox_request modifies it
        request = {
            "project_path": "/test/path",
            "config": SandboxConfig(),
        }

        result = adapter.queue_sandbox_request(request)

        assert result is True
        assert len(adapter._pending_queue) == 1
        assert adapter._pending_queue[0]["project_path"] == "/test/path"
        assert "_queued_at" in adapter._pending_queue[0]  # Check timestamp added

    def test_has_pending_requests_returns_false_when_empty(self, adapter):
        """Test that has_pending_requests returns False when queue is empty."""
        assert adapter.has_pending_requests() is False

    def test_has_pending_requests_returns_true_when_not_empty(self, adapter):
        """Test that has_pending_requests returns True when queue has items."""
        adapter._pending_queue.append(Mock())

        assert adapter.has_pending_requests() is True

    @pytest.mark.asyncio
    async def test_process_pending_queue_creates_sandbox_when_slot_available(self, adapter):
        """Test that process_pending_queue creates sandbox when slot opens."""
        # Mock the create_sandbox method
        adapter.create_sandbox = AsyncMock()

        # Use a dict as request (as expected by implementation)
        request = {
            "project_path": "/test/path",
            "config": SandboxConfig(),
            "project_id": "test-project",
            "tenant_id": "test-tenant",
        }
        adapter._pending_queue.append(request)

        await adapter.process_pending_queue()

        adapter.create_sandbox.assert_called_once_with(
            project_path="/test/path",
            config=SandboxConfig(),
            project_id="test-project",
            tenant_id="test-tenant",
        )
        assert len(adapter._pending_queue) == 0


class TestSandboxAutoCleanup:
    """Test enhanced auto cleanup mechanism."""

    @pytest.fixture
    def adapter(self):
        """Create adapter for cleanup tests."""
        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter()
            return adapter

    def test_cleanup_idle_sandboxes_removes_idle_sandboxes(self, adapter):
        """Test that cleanup_idle_sandboxes removes idle sandboxes."""
        now = datetime.now()

        # Create sandboxes with different last activity times
        adapter._active_sandboxes["active-1"] = MCPSandboxInstance(
            id="active-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/active",
            endpoint="ws://localhost:8765",
            created_at=now - timedelta(minutes=10),
            last_activity_at=now - timedelta(minutes=1),  # Recently active
        )

        adapter._active_sandboxes["idle-1"] = MCPSandboxInstance(
            id="idle-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/idle",
            endpoint="ws://localhost:8766",
            created_at=now - timedelta(minutes=30),
            last_activity_at=now - timedelta(minutes=31),  # Idle for 31 minutes
        )

        # Mock terminate_sandbox
        adapter.terminate_sandbox = AsyncMock()

        # Run cleanup (30 minute idle threshold)
        count = asyncio.run(adapter.cleanup_idle_sandboxes(max_idle_minutes=30))

        assert count == 1
        adapter.terminate_sandbox.assert_called_once_with("idle-1")

    def test_cleanup_idle_sandboxes_respects_min_age(self, adapter):
        """Test that cleanup_idle_sandboxes respects minimum age requirement."""
        now = datetime.now()

        # Create sandbox that is idle but also very young
        adapter._active_sandboxes["young-idle"] = MCPSandboxInstance(
            id="young-idle",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/young",
            endpoint="ws://localhost:8767",
            created_at=now - timedelta(minutes=5),  # Only 5 minutes old
            last_activity_at=now - timedelta(minutes=2),  # Idle for 2 minutes
        )

        adapter.terminate_sandbox = AsyncMock()

        # Run cleanup (should not remove because min_age is 10 minutes)
        count = asyncio.run(
            adapter.cleanup_idle_sandboxes(
                max_idle_minutes=1,
                min_age_minutes=10,
            )
        )

        assert count == 0
        adapter.terminate_sandbox.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_idle_sandboxes_updates_last_activity(self, adapter):
        """Test that cleanup_idle_sandboxes updates last_activity on active sandboxes."""
        now = datetime.now()

        adapter._active_sandboxes["active-1"] = MCPSandboxInstance(
            id="active-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/active",
            endpoint="ws://localhost:8765",
            created_at=now - timedelta(minutes=10),
            last_activity_at=now - timedelta(minutes=5),
        )

        # Mock health_check to return True
        adapter.health_check = AsyncMock(return_value=True)

        await adapter.cleanup_idle_sandboxes(max_idle_minutes=30)

        # Verify health_check was called (which updates activity)
        adapter.health_check.assert_called_once_with("active-1")


class TestSandboxResourceLimits:
    """Test sandbox resource limit validation."""

    @pytest.fixture
    def adapter(self):
        """Create adapter for resource limit tests."""
        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter(
                max_memory_mb=4096,
                max_cpu_cores=4,
            )
            return adapter

    def test_max_memory_property(self, adapter):
        """Test that max_memory_mb is set correctly."""
        assert adapter.max_memory_mb == 4096

    def test_max_cpu_cores_property(self, adapter):
        """Test that max_cpu_cores is set correctly."""
        assert adapter.max_cpu_cores == 4

    def test_validate_config_within_limits(self, adapter):
        """Test that validate_config passes for valid config."""
        config = SandboxConfig(
            memory_limit="1g",
            cpu_limit="1",
        )

        is_valid, errors = adapter.validate_resource_config(config)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_config_memory_exceeds_limit(self, adapter):
        """Test that validate_config fails when memory exceeds limit."""
        config = SandboxConfig(
            memory_limit="8g",  # Exceeds 4096MB limit
            cpu_limit="1",
        )

        is_valid, errors = adapter.validate_resource_config(config)

        assert is_valid is False
        assert any("memory" in str(error).lower() for error in errors)

    def test_validate_config_cpu_exceeds_limit(self, adapter):
        """Test that validate_config fails when CPU exceeds limit."""
        config = SandboxConfig(
            memory_limit="1g",
            cpu_limit="8",  # Exceeds 4 core limit
        )

        is_valid, errors = adapter.validate_resource_config(config)

        assert is_valid is False
        assert any("cpu" in str(error).lower() for error in errors)

    def test_validate_config_both_exceed_limits(self, adapter):
        """Test that validate_config fails when both exceed limits."""
        config = SandboxConfig(
            memory_limit="8g",
            cpu_limit="8",
        )

        is_valid, errors = adapter.validate_resource_config(config)

        assert is_valid is False
        assert len(errors) == 2

    def test_get_total_resource_usage(self, adapter):
        """Test getting total resource usage across all sandboxes."""
        # Mock sandbox stats
        adapter.get_sandbox_stats = AsyncMock(
            return_value={
                "memory_usage": 1024 * 1024 * 1024,  # 1GB in bytes
                "memory_limit": 2 * 1024 * 1024 * 1024,  # 2GB limit
                "cpu_percent": 50.0,
            }
        )

        adapter._active_sandboxes["test-1"] = Mock(status=SandboxStatus.RUNNING)
        adapter._active_sandboxes["test-2"] = Mock(status=SandboxStatus.RUNNING)

        total = asyncio.run(adapter.get_total_resource_usage())

        assert total["total_memory_mb"] == 2048  # 2 x 1GB
        assert total["total_cpu_percent"] == 100.0  # 2 x 50%
        assert total["sandbox_count"] == 2


class TestSandboxActivityTracking:
    """Test sandbox activity tracking for better cleanup decisions."""

    @pytest.fixture
    def adapter(self):
        """Create adapter for activity tracking tests."""
        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter()
            return adapter

    def test_update_activity_touches_last_activity(self, adapter):
        """Test that update_activity updates last_activity_at."""
        now = datetime.now()
        instance = MCPSandboxInstance(
            id="test-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/test",
            endpoint="ws://localhost:8765",
            created_at=now - timedelta(minutes=10),
            last_activity_at=now - timedelta(minutes=5),
        )

        adapter._active_sandboxes["test-1"] = instance

        before = instance.last_activity_at
        asyncio.run(adapter.update_activity("test-1"))
        after = instance.last_activity_at

        assert after > before

    def test_update_activity_is_idempotent(self, adapter):
        """Test that update_activity can be called multiple times."""
        now = datetime.now()
        instance = MCPSandboxInstance(
            id="test-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/test",
            endpoint="ws://localhost:8765",
            created_at=now,
            last_activity_at=now,
        )

        adapter._active_sandboxes["test-1"] = instance

        # Call multiple times
        asyncio.run(adapter.update_activity("test-1"))
        asyncio.run(adapter.update_activity("test-1"))
        asyncio.run(adapter.update_activity("test-1"))

        # Should still have valid instance
        assert instance.last_activity_at >= instance.created_at

    def test_update_activity_nonexistent_sandbox(self, adapter):
        """Test that update_activity handles nonexistent sandbox gracefully."""
        # Should not raise exception
        asyncio.run(adapter.update_activity("nonexistent"))

    def test_get_idle_time_returns_zero_for_new_sandbox(self, adapter):
        """Test that get_idle_time returns 0 for sandbox with no activity."""
        now = datetime.now()
        instance = MCPSandboxInstance(
            id="test-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/test",
            endpoint="ws://localhost:8765",
            created_at=now,
            last_activity_at=None,
        )

        adapter._active_sandboxes["test-1"] = instance

        idle_time = adapter.get_idle_time("test-1")

        assert idle_time == timedelta(0)

    def test_get_idle_time_calculates_correctly(self, adapter):
        """Test that get_idle_time calculates idle time correctly."""
        now = datetime.now()
        five_minutes_ago = now - timedelta(minutes=5)

        instance = MCPSandboxInstance(
            id="test-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(),
            project_path="/test",
            endpoint="ws://localhost:8765",
            created_at=now - timedelta(hours=1),
            last_activity_at=five_minutes_ago,
        )

        adapter._active_sandboxes["test-1"] = instance

        idle_time = adapter.get_idle_time("test-1")

        # Should be approximately 5 minutes (within 1 second tolerance)
        assert timedelta(minutes=4, seconds=59) <= idle_time <= timedelta(minutes=5, seconds=1)


class TestSandboxResourceMonitoring:
    """Test sandbox resource monitoring and metrics."""

    @pytest.fixture
    def adapter(self):
        """Create adapter for monitoring tests."""
        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter()
            return adapter

    @pytest.mark.asyncio
    async def test_get_resource_summary(self, adapter):
        """Test getting resource summary for all sandboxes."""
        now = datetime.now()

        adapter._active_sandboxes["test-1"] = MCPSandboxInstance(
            id="test-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(memory_limit="1g", cpu_limit="1"),
            project_path="/test1",
            endpoint="ws://localhost:8765",
            created_at=now,
        )

        adapter._active_sandboxes["test-2"] = MCPSandboxInstance(
            id="test-2",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(memory_limit="2g", cpu_limit="2"),
            project_path="/test2",
            endpoint="ws://localhost:8766",
            created_at=now,
        )

        # Mock get_sandbox_stats
        adapter.get_sandbox_stats = AsyncMock(
            side_effect=[
                {
                    "memory_usage": 512 * 1024 * 1024,  # 512MB
                    "memory_limit": 1 * 1024 * 1024 * 1024,  # 1GB
                    "cpu_percent": 25.0,
                },
                {
                    "memory_usage": 1024 * 1024 * 1024,  # 1GB
                    "memory_limit": 2 * 1024 * 1024 * 1024,  # 2GB
                    "cpu_percent": 50.0,
                },
            ]
        )

        summary = await adapter.get_resource_summary()

        assert summary["total_sandboxes"] == 2
        assert summary["total_memory_mb"] == 1536  # 512MB + 1GB = 1.5GB
        assert summary["total_cpu_percent"] == 75.0

    @pytest.mark.asyncio
    async def test_health_check_all_sandboxes(self, adapter):
        """Test health check on all sandboxes."""
        adapter._active_sandboxes["test-1"] = Mock(status=SandboxStatus.RUNNING)
        adapter._active_sandboxes["test-2"] = Mock(status=SandboxStatus.RUNNING)

        adapter.health_check = AsyncMock(side_effect=[True, False])

        results = await adapter.health_check_all()

        assert results["healthy"] == 1
        assert results["unhealthy"] == 1
        assert results["total"] == 2
