"""
Tests for Pool Orchestrator.
"""

import pytest

from src.infrastructure.agent.pool.config import PoolConfig
from src.infrastructure.agent.pool.orchestrator import (
    OrchestratorConfig,
    PoolOrchestrator,
    create_orchestrator,
)


class TestOrchestratorConfig:
    """Tests for OrchestratorConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = OrchestratorConfig()

        assert config.enable_health_monitor is True
        assert config.enable_failure_recovery is True
        assert config.enable_auto_scaling is False
        assert config.enable_state_recovery is True
        assert config.enable_metrics is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = OrchestratorConfig(
            enable_health_monitor=False,
            enable_auto_scaling=True,
            health_check_interval_seconds=60,
        )

        assert config.enable_health_monitor is False
        assert config.enable_auto_scaling is True
        assert config.health_check_interval_seconds == 60


class TestPoolOrchestrator:
    """Tests for PoolOrchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with minimal config."""
        config = OrchestratorConfig(
            enable_health_monitor=False,
            enable_failure_recovery=False,
            enable_auto_scaling=False,
            enable_state_recovery=False,
            enable_metrics=False,
        )
        return PoolOrchestrator(config)

    async def test_start_stop(self, orchestrator):
        """Test orchestrator start and stop."""
        assert not orchestrator.is_running

        await orchestrator.start()
        assert orchestrator.is_running
        assert orchestrator.pool_manager is not None

        await orchestrator.stop()
        assert not orchestrator.is_running

    async def test_start_already_running(self, orchestrator):
        """Test starting already running orchestrator."""
        await orchestrator.start()
        await orchestrator.start()  # Should not raise
        assert orchestrator.is_running
        await orchestrator.stop()

    async def test_stop_not_running(self, orchestrator):
        """Test stopping non-running orchestrator."""
        await orchestrator.stop()  # Should not raise

    async def test_get_status(self, orchestrator):
        """Test getting orchestrator status."""
        await orchestrator.start()

        status = await orchestrator.get_status()

        assert status["running"] is True
        assert "services" in status
        assert "config" in status
        assert status["services"]["pool_manager"] is True

        await orchestrator.stop()

    async def test_get_status_not_running(self, orchestrator):
        """Test getting status when not running."""
        status = await orchestrator.get_status()

        assert status["running"] is False


class TestOrchestratorWithServices:
    """Tests for orchestrator with HA services enabled."""

    @pytest.fixture
    def orchestrator_with_ha(self):
        """Create orchestrator with HA services."""
        config = OrchestratorConfig(
            enable_health_monitor=True,
            enable_failure_recovery=True,
            enable_auto_scaling=False,
            enable_state_recovery=True,
            enable_metrics=True,
        )
        return PoolOrchestrator(config)

    async def test_start_with_services(self, orchestrator_with_ha):
        """Test orchestrator start with HA services."""
        await orchestrator_with_ha.start()

        status = await orchestrator_with_ha.get_status()

        assert status["services"]["health_monitor"] is True
        assert status["services"]["failure_recovery"] is True
        assert status["services"]["state_recovery"] is True
        assert status["services"]["metrics_collector"] is True
        assert status["services"]["auto_scaling"] is False

        await orchestrator_with_ha.stop()

    async def test_status_includes_stats(self, orchestrator_with_ha):
        """Test status includes stats from services."""
        await orchestrator_with_ha.start()

        status = await orchestrator_with_ha.get_status()

        assert "pool_stats" in status
        assert "failure_stats" in status
        assert "checkpoint_stats" in status

        await orchestrator_with_ha.stop()


class TestCreateOrchestrator:
    """Tests for create_orchestrator factory."""

    def test_create_default(self):
        """Test creating default orchestrator."""
        orchestrator = create_orchestrator()

        assert orchestrator is not None
        assert orchestrator.config.enable_health_monitor is True
        assert orchestrator.config.enable_auto_scaling is False

    def test_create_with_ha(self):
        """Test creating orchestrator with HA."""
        orchestrator = create_orchestrator(enable_ha=True)

        assert orchestrator.config.enable_health_monitor is True
        assert orchestrator.config.enable_failure_recovery is True
        assert orchestrator.config.enable_state_recovery is True

    def test_create_with_scaling(self):
        """Test creating orchestrator with scaling."""
        orchestrator = create_orchestrator(enable_scaling=True)

        assert orchestrator.config.enable_auto_scaling is True

    def test_create_without_ha(self):
        """Test creating orchestrator without HA."""
        orchestrator = create_orchestrator(enable_ha=False)

        assert orchestrator.config.enable_health_monitor is False
        assert orchestrator.config.enable_failure_recovery is False
        assert orchestrator.config.enable_state_recovery is False

    def test_create_with_custom_pool_config(self):
        """Test creating orchestrator with custom pool config."""
        pool_config = PoolConfig(health_check_interval_seconds=120)
        orchestrator = create_orchestrator(pool_config=pool_config)

        assert orchestrator.config.pool_config.health_check_interval_seconds == 120
