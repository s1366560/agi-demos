"""Tests for Unified Configuration Management.

Tests the centralized flat configuration system for ReActAgent.
"""

import pytest

from src.infrastructure.agent.config import (
    AgentConfig,
    ConfigManager,
    ExecutionConfig,
    get_config,
    get_default_config,
    set_config,
)


class TestAgentConfigExecution:
    """Tests for execution-related fields on flat AgentConfig."""

    def test_default_values(self) -> None:
        """Should have default values for execution fields."""
        config = AgentConfig()

        assert config.max_steps == 20
        assert config.skill_match_threshold == 0.9
        assert config.subagent_match_threshold == 0.5
        assert config.default_timeout_seconds == 30.0

    def test_custom_values(self) -> None:
        """Should accept custom values for execution fields."""
        config = AgentConfig(
            max_steps=50,
            skill_match_threshold=0.8,
            subagent_match_threshold=0.3,
        )

        assert config.max_steps == 50
        assert config.skill_match_threshold == 0.8
        assert config.subagent_match_threshold == 0.3

    def test_execution_config_alias(self) -> None:
        """ExecutionConfig should be an alias for AgentConfig."""
        assert ExecutionConfig is AgentConfig

        config = ExecutionConfig(max_steps=42)
        assert isinstance(config, AgentConfig)
        assert config.max_steps == 42

    def test_validate_max_steps(self) -> None:
        """Should validate max_steps range."""
        config = AgentConfig()

        config.validate()  # Should not raise

        config.max_steps = 0
        with pytest.raises(ValueError, match="max_steps"):
            config.validate()

        config.max_steps = 101
        with pytest.raises(ValueError, match="max_steps"):
            config.validate()

    def test_validate_thresholds(self) -> None:
        """Should validate threshold ranges."""
        config = AgentConfig()

        # Test skill_match_threshold
        config.skill_match_threshold = 1.5
        with pytest.raises(ValueError, match="skill_match_threshold"):
            config.validate()

        # Reset and test subagent_match_threshold
        config.skill_match_threshold = 0.9  # Reset to valid
        config.subagent_match_threshold = -0.1
        with pytest.raises(ValueError, match="subagent_match_threshold"):
            config.validate()


class TestAgentConfigPerformance:
    """Tests for performance-related fields on flat AgentConfig."""

    def test_default_values(self) -> None:
        """Should have default values for performance fields."""
        config = AgentConfig()

        assert config.context_limit == 128000
        assert config.max_parallel_tasks == 5
        assert config.enable_cache is True

    def test_validate_context_limit(self) -> None:
        """Should validate context_limit."""
        config = AgentConfig()

        config.context_limit = 999
        with pytest.raises(ValueError, match="context_limit"):
            config.validate()

    def test_validate_compression_threshold(self) -> None:
        """Should validate compression threshold."""
        config = AgentConfig()

        config.context_compression_threshold = 1.5
        with pytest.raises(ValueError, match="context_compression_threshold"):
            config.validate()


class TestAgentConfigCost:
    """Tests for cost-related fields on flat AgentConfig."""

    def test_default_values(self) -> None:
        """Should have default values for cost fields."""
        config = AgentConfig()

        assert config.max_cost_per_request == 1.0
        assert config.max_cost_per_session == 10.0
        assert config.cost_warning_threshold == 0.8

    def test_validate_max_cost(self) -> None:
        """Should validate cost limits."""
        config = AgentConfig()

        config.max_cost_per_request = -1.0
        with pytest.raises(ValueError, match="max_cost_per_request"):
            config.validate()

    def test_validate_warning_threshold(self) -> None:
        """Should validate warning threshold."""
        config = AgentConfig()

        config.cost_warning_threshold = 1.5
        with pytest.raises(ValueError, match="cost_warning_threshold"):
            config.validate()


class TestAgentConfigPermission:
    """Tests for permission-related fields on flat AgentConfig."""

    def test_default_values(self) -> None:
        """Should have default values for permission fields."""
        config = AgentConfig()

        assert config.permission_default_mode == "ask"
        assert config.auto_approve_safe_tools is True
        assert "read_file" in config.safe_tools

    def test_validate_default_mode(self) -> None:
        """Should validate permission_default_mode."""
        config = AgentConfig()

        config.permission_default_mode = "invalid"
        with pytest.raises(ValueError, match="default_mode"):
            config.validate()

        config.permission_default_mode = "allow"
        config.validate()  # Should not raise


class TestAgentConfigMonitoring:
    """Tests for monitoring-related fields on flat AgentConfig."""

    def test_default_values(self) -> None:
        """Should have default values for monitoring fields."""
        config = AgentConfig()

        assert config.log_level == "INFO"
        assert config.enable_metrics is True
        assert config.enable_doom_loop_detection is True

    def test_validate_log_level(self) -> None:
        """Should validate log level."""
        config = AgentConfig()

        config.log_level = "INVALID"
        with pytest.raises(ValueError, match="log_level"):
            config.validate()

    def test_validate_trace_sample_rate(self) -> None:
        """Should validate trace sample rate."""
        config = AgentConfig()

        config.trace_sample_rate = 1.5
        with pytest.raises(ValueError, match="trace_sample_rate"):
            config.validate()


class TestAgentConfig:
    """Tests for AgentConfig backward-compat shims and serialization."""

    def test_backward_compat_shims(self) -> None:
        """Backward-compat properties should return self (AgentConfig)."""
        config = AgentConfig()

        assert isinstance(config.execution, AgentConfig)
        assert isinstance(config.performance, AgentConfig)
        assert isinstance(config.cost, AgentConfig)
        assert isinstance(config.permission, AgentConfig)
        assert isinstance(config.monitoring, AgentConfig)

    def test_backward_compat_field_access(self) -> None:
        """Should access fields through backward-compat shim chains."""
        config = AgentConfig(
            max_steps=42,
            context_limit=200000,
            max_cost_per_request=5.0,
            permission_default_mode="allow",
            log_level="DEBUG",
        )

        assert config.execution.max_steps == 42
        assert config.performance.context_limit == 200000
        assert config.cost.max_cost_per_request == 5.0
        assert config.permission.default_mode == "allow"
        assert config.monitoring.log_level == "DEBUG"

    def test_backward_compat_shims_are_same_object(self) -> None:
        """Shim properties should return self, not copies."""
        config = AgentConfig()

        assert config.execution is config
        assert config.performance is config
        assert config.cost is config
        assert config.permission is config
        assert config.monitoring is config

    def test_validate_all_sections(self) -> None:
        """Should validate all configuration sections."""
        config = AgentConfig()

        config.validate()  # Should not raise

    def test_to_dict(self) -> None:
        """Should convert to dictionary."""
        config = AgentConfig()

        result = config.to_dict()

        assert "execution" in result
        assert "performance" in result
        assert "cost" in result
        assert "permission" in result
        assert "monitoring" in result

    def test_from_dict(self) -> None:
        """Should create from dictionary."""
        data = {
            "execution": {
                "max_steps": 50,
                "skill_match_threshold": 0.8,
            },
            "performance": {
                "context_limit": 256000,
            },
        }

        config = AgentConfig.from_dict(data)

        assert config.max_steps == 50
        assert config.skill_match_threshold == 0.8
        assert config.context_limit == 256000
        # Also works through backward-compat shims
        assert config.execution.max_steps == 50
        assert config.performance.context_limit == 256000

    def test_from_dict_with_invalid_value(self) -> None:
        """Should handle invalid values in from_dict."""
        data = {
            "execution": {
                "max_steps": 999,  # Invalid
            },
        }

        with pytest.raises(ValueError, match="max_steps"):
            AgentConfig.from_dict(data).validate()

    def test_get_default(self) -> None:
        """Should get default configuration."""
        config = AgentConfig.get_default()

        assert isinstance(config, AgentConfig)

    def test_with_tenant_override(self) -> None:
        """Should apply tenant-specific overrides."""
        config = AgentConfig()

        overridden = config.with_tenant_override(
            {
                "execution": {"max_steps": 50},
            }
        )

        assert overridden.max_steps == 50
        assert overridden.execution.max_steps == 50
        assert overridden.skill_match_threshold == 0.9  # Unchanged


class TestConfigManager:
    """Tests for ConfigManager."""

    def test_get_default_config(self) -> None:
        """Should return default config when no tenant specified."""
        manager = ConfigManager()

        config = manager.get_config()

        assert isinstance(config, AgentConfig)

    def test_get_default_config_with_tenant(self) -> None:
        """Should return default config for unknown tenant."""
        manager = ConfigManager()

        config = manager.get_config(tenant_id="unknown")

        assert isinstance(config, AgentConfig)

    def test_set_tenant_config(self) -> None:
        """Should set tenant-specific config."""
        manager = ConfigManager()
        tenant_config = AgentConfig(max_steps=50)

        manager.set_tenant_config("tenant-123", tenant_config)

        retrieved = manager.get_config("tenant-123")
        assert retrieved.max_steps == 50
        assert retrieved.execution.max_steps == 50

    def test_set_invalid_tenant_config(self) -> None:
        """Should reject invalid tenant config."""
        manager = ConfigManager()
        invalid_config = AgentConfig(max_steps=0)  # Invalid

        with pytest.raises(ValueError, match="max_steps"):
            manager.set_tenant_config("tenant-123", invalid_config)

    def test_update_default(self) -> None:
        """Should update default configuration."""
        manager = ConfigManager()

        manager.update_default(execution={"max_steps": 30})

        config = manager.get_config()
        assert config.max_steps == 30
        assert config.execution.max_steps == 30

    def test_change_callback(self) -> None:
        """Should notify listeners of configuration changes."""
        manager = ConfigManager()
        calls: list[tuple[str | None, AgentConfig]] = []

        def callback(tenant_id: str | None, config: AgentConfig) -> None:
            calls.append((tenant_id, config))

        manager.register_change_callback(callback)
        manager.update_default(execution={"max_steps": 30})

        assert len(calls) == 1
        assert calls[0][0] is None  # None = default config changed
        assert calls[0][1].max_steps == 30

    def test_change_callback_for_tenant(self) -> None:
        """Should notify on tenant config changes."""
        manager = ConfigManager()
        calls: list[tuple[str | None, AgentConfig]] = []

        def callback(tenant_id: str | None, config: AgentConfig) -> None:
            calls.append((tenant_id, config))

        manager.register_change_callback(callback)
        tenant_config = AgentConfig(max_steps=50)
        manager.set_tenant_config("tenant-123", tenant_config)

        assert len(calls) == 1
        assert calls[0][0] == "tenant-123"

    def test_unregister_callback(self) -> None:
        """Should stop notifying unregistered callbacks."""
        manager = ConfigManager()
        calls: list[str | None] = []

        def callback(tenant_id: str | None, config: AgentConfig) -> None:
            calls.append(tenant_id)

        manager.register_change_callback(callback)
        manager.unregister_change_callback(callback)
        manager.update_default(execution={"max_steps": 30})

        assert len(calls) == 0


class TestGlobalConfig:
    """Tests for global configuration functions."""

    def test_get_config_default(self) -> None:
        """Should get default global config."""
        config = get_config()

        assert isinstance(config, AgentConfig)

    def test_get_config_with_tenant(self) -> None:
        """Should get config for specific tenant."""
        config = get_config("tenant-123")

        assert isinstance(config, AgentConfig)

    def test_get_default_config(self) -> None:
        """Should get default configuration."""
        config = get_default_config()

        assert isinstance(config, AgentConfig)

    def test_set_config(self) -> None:
        """Should set global configuration manager."""
        custom_manager = ConfigManager(
            default_config=AgentConfig(max_steps=100),
        )

        set_config(custom_manager)

        config = get_config()
        assert config.max_steps == 100
        assert config.execution.max_steps == 100

        # Reset to default for other tests
        set_config(ConfigManager())
