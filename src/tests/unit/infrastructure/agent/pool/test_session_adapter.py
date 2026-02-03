"""
Integration tests for PooledAgentSessionAdapter.

Tests the bridge between the new pool architecture and existing systems.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.pool import (
    AdapterConfig,
    AgentInstance,
    PoolConfig,
    PooledAgentSessionAdapter,
    ProjectTier,
    SessionRequest,
    create_pooled_adapter,
)


class TestPooledAgentSessionAdapter:
    """Tests for PooledAgentSessionAdapter."""

    @pytest.fixture
    def adapter_config(self):
        """Create adapter config."""
        return AdapterConfig(
            enable_pool_management=True,
            enable_resource_isolation=True,
            enable_health_monitoring=True,
            enable_prewarming=False,  # Disable for tests
        )

    @pytest.fixture
    def pool_config(self):
        """Create pool config."""
        return PoolConfig()

    @pytest.fixture
    def adapter(self, pool_config, adapter_config):
        """Create adapter instance."""
        return PooledAgentSessionAdapter(
            pool_config=pool_config,
            adapter_config=adapter_config,
        )

    @pytest.mark.asyncio
    async def test_adapter_start_stop(self, adapter):
        """Test adapter start and stop lifecycle."""
        # Initially not running
        assert adapter._running is False

        # Start
        await adapter.start()
        assert adapter._running is True
        assert adapter._pool_manager is not None

        # Stop
        await adapter.stop()
        assert adapter._running is False

    @pytest.mark.asyncio
    async def test_get_stats_not_running(self, adapter):
        """Test getting stats when not running."""
        stats = await adapter.get_stats()
        assert stats["running"] is False
        assert stats["mode"] == "pooled"

    @pytest.mark.asyncio
    async def test_get_stats_running(self, adapter):
        """Test getting stats when running."""
        await adapter.start()

        stats = await adapter.get_stats()
        assert stats["running"] is True
        assert stats["mode"] == "pooled"
        assert "pool" in stats
        assert stats["pool"]["total_instances"] == 0

        await adapter.stop()

    @pytest.mark.asyncio
    async def test_classify_project(self, adapter):
        """Test project classification."""
        await adapter.start()

        tier = await adapter.classify_project(
            tenant_id="tenant-1",
            project_id="project-1",
        )

        # Should return a valid tier
        assert tier in [ProjectTier.HOT, ProjectTier.WARM, ProjectTier.COLD]

        await adapter.stop()

    @pytest.mark.asyncio
    async def test_set_project_tier(self, adapter):
        """Test setting project tier."""
        await adapter.start()

        result = await adapter.set_project_tier(
            tenant_id="tenant-1",
            project_id="project-1",
            tier=ProjectTier.HOT,
        )

        assert result is True

        await adapter.stop()


class TestLegacyFallback:
    """Tests for legacy fallback mode."""

    @pytest.fixture
    def legacy_adapter(self):
        """Create adapter in legacy mode."""
        config = AdapterConfig(
            enable_pool_management=False,
        )
        return PooledAgentSessionAdapter(adapter_config=config)

    @pytest.mark.asyncio
    async def test_legacy_mode_stats(self, legacy_adapter):
        """Test stats in legacy mode."""
        await legacy_adapter.start()

        stats = await legacy_adapter.get_stats()
        assert stats["mode"] == "legacy"
        assert "pool" not in stats

        await legacy_adapter.stop()

    @pytest.mark.asyncio
    async def test_legacy_classify_project(self, legacy_adapter):
        """Test classify returns COLD in legacy mode."""
        await legacy_adapter.start()

        tier = await legacy_adapter.classify_project(
            tenant_id="tenant-1",
            project_id="project-1",
        )

        # Legacy mode should return COLD
        assert tier == ProjectTier.COLD

        await legacy_adapter.stop()


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_pooled_adapter_defaults(self):
        """Test create_pooled_adapter with defaults."""
        adapter = create_pooled_adapter()
        assert adapter.adapter_config.enable_pool_management is True
        assert adapter.adapter_config.enable_resource_isolation is True

    def test_create_pooled_adapter_custom(self):
        """Test create_pooled_adapter with custom settings."""
        adapter = create_pooled_adapter(
            enable_pool_management=False,
            enable_resource_isolation=False,
        )
        assert adapter.adapter_config.enable_pool_management is False
        assert adapter.adapter_config.enable_resource_isolation is False


class TestSessionRequest:
    """Tests for SessionRequest."""

    def test_session_request_basic(self):
        """Test basic session request creation."""
        request = SessionRequest(
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert request.tenant_id == "tenant-1"
        assert request.project_id == "project-1"
        assert request.agent_mode == "default"

    def test_session_request_with_overrides(self):
        """Test session request with LLM overrides."""
        request = SessionRequest(
            tenant_id="tenant-1",
            project_id="project-1",
            model="gpt-4",
            temperature=0.5,
            max_tokens=2048,
        )

        assert request.model == "gpt-4"
        assert request.temperature == 0.5
        assert request.max_tokens == 2048


class TestAdapterIntegration:
    """Integration tests for full adapter workflow."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test complete workflow: start -> get_session -> execute -> stop."""
        # Create adapter with mock factory
        mock_agent = MagicMock()
        mock_agent.stream = AsyncMock(return_value=iter([{"type": "done"}]))

        async def mock_factory(**kwargs):
            return mock_agent

        adapter = PooledAgentSessionAdapter(agent_factory=mock_factory)
        await adapter.start()

        try:
            # Get session
            request = SessionRequest(
                tenant_id="tenant-1",
                project_id="project-1",
            )

            instance = await adapter.get_session(request)
            assert instance is not None
            assert isinstance(instance, AgentInstance)

            # Check stats
            stats = await adapter.get_stats()
            assert stats["running"] is True

        finally:
            await adapter.stop()

    @pytest.mark.asyncio
    async def test_health_check_no_instance(self):
        """Test health check when instance doesn't exist."""
        adapter = create_pooled_adapter()
        await adapter.start()

        result = await adapter.health_check(
            tenant_id="nonexistent",
            project_id="nonexistent",
        )

        assert result is None

        await adapter.stop()
