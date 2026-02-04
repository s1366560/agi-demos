"""
Tests for Feature Flags.
"""

import pytest

from src.infrastructure.agent.pool.feature_flags import (
    FeatureFlagConfig,
    FeatureFlags,
    RolloutStrategy,
    get_feature_flags,
    reset_feature_flags,
)


class TestFeatureFlagConfig:
    """Tests for FeatureFlagConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = FeatureFlagConfig(name="test_flag")

        assert config.name == "test_flag"
        assert config.enabled is False
        assert config.strategy == RolloutStrategy.NONE
        assert config.percentage == 0.0

    def test_custom_config(self):
        """Test custom configuration."""
        config = FeatureFlagConfig(
            name="custom_flag",
            description="Test flag",
            enabled=True,
            strategy=RolloutStrategy.PERCENTAGE,
            percentage=50.0,
        )

        assert config.name == "custom_flag"
        assert config.enabled is True
        assert config.strategy == RolloutStrategy.PERCENTAGE
        assert config.percentage == 50.0


class TestFeatureFlags:
    """Tests for FeatureFlags."""

    @pytest.fixture
    def flags(self):
        """Create feature flags instance."""
        return FeatureFlags()

    async def test_default_flags_exist(self, flags):
        """Test default flags are present."""
        all_flags = await flags.get_all_flags()

        assert "agent_pool_enabled" in all_flags
        assert "agent_pool_hot_tier" in all_flags
        assert "agent_pool_warm_tier" in all_flags
        assert "agent_pool_cold_tier" in all_flags

    async def test_is_enabled_disabled_flag(self, flags):
        """Test disabled flag returns False."""
        result = await flags.is_enabled("agent_pool_enabled")
        assert result is False

    async def test_is_enabled_all_strategy(self, flags):
        """Test ALL strategy returns True."""
        result = await flags.is_enabled("agent_pool_warm_tier")
        assert result is True

    async def test_is_enabled_unknown_flag(self, flags):
        """Test unknown flag returns False."""
        result = await flags.is_enabled("nonexistent_flag")
        assert result is False

    async def test_set_flag(self, flags):
        """Test setting a flag."""
        config = FeatureFlagConfig(
            name="test_flag",
            enabled=True,
            strategy=RolloutStrategy.ALL,
        )
        flags.set_flag(config)

        result = await flags.is_enabled("test_flag")
        assert result is True

    async def test_allowlist_strategy(self, flags):
        """Test allowlist strategy."""
        config = FeatureFlagConfig(
            name="allowlist_test",
            enabled=True,
            strategy=RolloutStrategy.ALLOWLIST,
            tenant_allowlist={"tenant-1", "tenant-2"},
        )
        flags.set_flag(config)

        # Tenant in allowlist
        assert await flags.is_enabled("allowlist_test", tenant_id="tenant-1") is True
        assert await flags.is_enabled("allowlist_test", tenant_id="tenant-2") is True

        # Tenant not in allowlist
        assert await flags.is_enabled("allowlist_test", tenant_id="tenant-3") is False

    async def test_denylist_strategy(self, flags):
        """Test denylist strategy."""
        config = FeatureFlagConfig(
            name="denylist_test",
            enabled=True,
            strategy=RolloutStrategy.DENYLIST,
            tenant_denylist={"tenant-blocked"},
        )
        flags.set_flag(config)

        # Tenant not in denylist
        assert await flags.is_enabled("denylist_test", tenant_id="tenant-1") is True

        # Tenant in denylist
        assert await flags.is_enabled("denylist_test", tenant_id="tenant-blocked") is False

    async def test_percentage_strategy_100(self, flags):
        """Test percentage strategy at 100%."""
        config = FeatureFlagConfig(
            name="percentage_100",
            enabled=True,
            strategy=RolloutStrategy.PERCENTAGE,
            percentage=100.0,
        )
        flags.set_flag(config)

        result = await flags.is_enabled("percentage_100", tenant_id="any")
        assert result is True

    async def test_percentage_strategy_0(self, flags):
        """Test percentage strategy at 0%."""
        config = FeatureFlagConfig(
            name="percentage_0",
            enabled=True,
            strategy=RolloutStrategy.PERCENTAGE,
            percentage=0.0,
        )
        flags.set_flag(config)

        result = await flags.is_enabled("percentage_0", tenant_id="any")
        assert result is False

    async def test_percentage_strategy_deterministic(self, flags):
        """Test percentage strategy is deterministic."""
        config = FeatureFlagConfig(
            name="percentage_50",
            enabled=True,
            strategy=RolloutStrategy.PERCENTAGE,
            percentage=50.0,
        )
        flags.set_flag(config)

        # Same tenant should always get same result
        result1 = await flags.is_enabled("percentage_50", tenant_id="test-tenant")
        result2 = await flags.is_enabled("percentage_50", tenant_id="test-tenant")
        assert result1 == result2

    async def test_enable_for_tenant(self, flags):
        """Test enabling flag for specific tenant."""
        config = FeatureFlagConfig(
            name="tenant_test",
            enabled=True,
            strategy=RolloutStrategy.ALLOWLIST,
        )
        flags.set_flag(config)

        # Initially not enabled
        assert await flags.is_enabled("tenant_test", tenant_id="t1") is False

        # Enable for tenant
        await flags.enable_for_tenant("tenant_test", "t1")
        assert await flags.is_enabled("tenant_test", tenant_id="t1") is True

    async def test_disable_for_tenant(self, flags):
        """Test disabling flag for specific tenant."""
        config = FeatureFlagConfig(
            name="disable_test",
            enabled=True,
            strategy=RolloutStrategy.ALLOWLIST,
            tenant_allowlist={"t1"},
        )
        flags.set_flag(config)

        # Initially enabled
        assert await flags.is_enabled("disable_test", tenant_id="t1") is True

        # Disable for tenant
        await flags.disable_for_tenant("disable_test", "t1")
        assert await flags.is_enabled("disable_test", tenant_id="t1") is False

    async def test_enable_for_project(self, flags):
        """Test enabling flag for specific project."""
        config = FeatureFlagConfig(
            name="project_test",
            enabled=True,
            strategy=RolloutStrategy.ALLOWLIST,
        )
        flags.set_flag(config)

        # Enable for project
        await flags.enable_for_project("project_test", "tenant-1", "project-1")

        # Project enabled
        assert (
            await flags.is_enabled(
                "project_test", tenant_id="tenant-1", project_id="project-1"
            )
            is True
        )

        # Other project not enabled
        assert (
            await flags.is_enabled(
                "project_test", tenant_id="tenant-1", project_id="project-2"
            )
            is False
        )

    async def test_set_percentage(self, flags):
        """Test setting rollout percentage."""
        config = FeatureFlagConfig(
            name="set_percentage_test",
            enabled=True,
            strategy=RolloutStrategy.NONE,
        )
        flags.set_flag(config)

        await flags.set_percentage("set_percentage_test", 75.0)

        flag = flags.get_flag("set_percentage_test")
        assert flag.percentage == 75.0
        assert flag.strategy == RolloutStrategy.PERCENTAGE

    async def test_set_percentage_clamped(self, flags):
        """Test percentage is clamped to 0-100."""
        config = FeatureFlagConfig(
            name="clamp_test",
            enabled=True,
            strategy=RolloutStrategy.NONE,
        )
        flags.set_flag(config)

        await flags.set_percentage("clamp_test", 150.0)
        flag = flags.get_flag("clamp_test")
        assert flag.percentage == 100.0

        await flags.set_percentage("clamp_test", -50.0)
        flag = flags.get_flag("clamp_test")
        assert flag.percentage == 0.0

    async def test_start_gradual_rollout(self, flags):
        """Test starting gradual rollout."""
        config = FeatureFlagConfig(
            name="gradual_test",
            enabled=False,
            strategy=RolloutStrategy.NONE,
        )
        flags.set_flag(config)

        result = await flags.start_gradual_rollout(
            "gradual_test",
            start_percentage=10.0,
            end_percentage=90.0,
            duration_days=7,
        )

        assert result is True
        flag = flags.get_flag("gradual_test")
        assert flag.enabled is True
        assert flag.strategy == RolloutStrategy.GRADUAL
        assert flag.start_percentage == 10.0
        assert flag.end_percentage == 90.0
        assert flag.start_date is not None
        assert flag.end_date is not None


class TestGetFeatureFlags:
    """Tests for global feature flags."""

    def test_get_feature_flags_singleton(self):
        """Test get_feature_flags returns singleton."""
        reset_feature_flags()

        flags1 = get_feature_flags()
        flags2 = get_feature_flags()

        assert flags1 is flags2

    def test_reset_feature_flags(self):
        """Test resetting feature flags."""
        flags1 = get_feature_flags()
        reset_feature_flags()
        flags2 = get_feature_flags()

        assert flags1 is not flags2
