"""
Unit tests for TenantAgentConfig entity (T088).

Tests the tenant-level agent configuration entity that controls
agent behavior at the tenant level.
"""

from datetime import UTC, datetime

import pytest

from src.domain.model.agent.tenant_agent_config import (
    ConfigType,
    TenantAgentConfig,
)


class TestTenantAgentConfig:
    """Unit tests for TenantAgentConfig entity."""

    def test_create_default_config(self):
        """Test creating default configuration."""
        config = TenantAgentConfig.create_default(tenant_id="tenant-1")

        assert config.tenant_id == "tenant-1"
        assert config.config_type == ConfigType.DEFAULT
        assert config.pattern_learning_enabled is True
        assert config.multi_level_thinking_enabled is True
        assert config.max_work_plan_steps == 10
        assert config.tool_timeout_seconds == 30

    def test_create_custom_config(self):
        """Test creating custom configuration."""
        config = TenantAgentConfig(
            id="config-1",
            tenant_id="tenant-1",
            config_type=ConfigType.CUSTOM,
            llm_model="gpt-4",
            llm_temperature=0.7,
            pattern_learning_enabled=False,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=15,
            tool_timeout_seconds=60,
            enabled_tools=["memory_search", "entity_lookup"],
            disabled_tools=["episode_retrieval"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        assert config.id == "config-1"
        assert config.tenant_id == "tenant-1"
        assert config.config_type == ConfigType.CUSTOM
        assert config.llm_model == "gpt-4"
        assert config.llm_temperature == 0.7
        assert config.pattern_learning_enabled is False
        assert config.multi_level_thinking_enabled is True
        assert config.max_work_plan_steps == 15
        assert config.tool_timeout_seconds == 60
        assert "memory_search" in config.enabled_tools
        assert "episode_retrieval" in config.disabled_tools

    def test_validation_max_steps_positive(self):
        """Test that max_work_plan_steps must be positive."""
        with pytest.raises(ValueError, match="max_work_plan_steps must be positive"):
            TenantAgentConfig(
                id="config-1",
                tenant_id="tenant-1",
                config_type=ConfigType.DEFAULT,
                llm_model="default",
                llm_temperature=0.7,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=0,
                tool_timeout_seconds=30,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_timeout_positive(self):
        """Test that tool_timeout_seconds must be positive."""
        with pytest.raises(ValueError, match="tool_timeout_seconds must be positive"):
            TenantAgentConfig(
                id="config-1",
                tenant_id="tenant-1",
                config_type=ConfigType.DEFAULT,
                llm_model="default",
                llm_temperature=0.7,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=10,
                tool_timeout_seconds=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_temperature_range(self):
        """Test that llm_temperature must be between 0 and 2."""
        with pytest.raises(ValueError, match="llm_temperature must be between 0 and 2"):
            TenantAgentConfig(
                id="config-1",
                tenant_id="tenant-1",
                config_type=ConfigType.DEFAULT,
                llm_model="default",
                llm_temperature=2.5,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=10,
                tool_timeout_seconds=30,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_validation_tenant_id_required(self):
        """Test that tenant_id is required."""
        with pytest.raises(ValueError, match="tenant_id cannot be empty"):
            TenantAgentConfig(
                id="config-1",
                tenant_id="",
                config_type=ConfigType.DEFAULT,
                llm_model="default",
                llm_temperature=0.7,
                pattern_learning_enabled=True,
                multi_level_thinking_enabled=True,
                max_work_plan_steps=10,
                tool_timeout_seconds=30,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

    def test_is_tool_enabled(self):
        """Test checking if a tool is enabled."""
        config = TenantAgentConfig(
            id="config-1",
            tenant_id="tenant-1",
            config_type=ConfigType.CUSTOM,
            llm_model="default",
            llm_temperature=0.7,
            pattern_learning_enabled=True,
            multi_level_thinking_enabled=True,
            max_work_plan_steps=10,
            tool_timeout_seconds=30,
            enabled_tools=["memory_search", "entity_lookup"],
            disabled_tools=["episode_retrieval"],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        # Tool in enabled list
        assert config.is_tool_enabled("memory_search") is True

        # Tool in disabled list
        assert config.is_tool_enabled("episode_retrieval") is False

        # Tool not in either list (enabled_tools is non-empty, so defaults to disabled)
        assert config.is_tool_enabled("graph_query") is False

    def test_update_llm_settings(self):
        """Test updating LLM settings."""
        config = TenantAgentConfig.create_default(tenant_id="tenant-1")

        updated = config.update_llm_settings(
            model="gpt-4",
            temperature=0.8,
        )

        assert updated.llm_model == "gpt-4"
        assert updated.llm_temperature == 0.8
        assert updated.id == config.id  # ID preserved
        assert updated.tenant_id == config.tenant_id  # Tenant preserved

    def test_update_pattern_learning(self):
        """Test updating pattern learning setting."""
        config = TenantAgentConfig.create_default(tenant_id="tenant-1")

        updated = config.update_pattern_learning(enabled=False)

        assert updated.pattern_learning_enabled is False

    def test_update_tool_settings(self):
        """Test updating tool settings."""
        config = TenantAgentConfig.create_default(tenant_id="tenant-1")

        updated = config.update_tool_settings(
            enabled_tools=["memory_search"],
            disabled_tools=["episode_retrieval"],
            timeout_seconds=60,
        )

        assert updated.enabled_tools == ["memory_search"]
        assert updated.disabled_tools == ["episode_retrieval"]
        assert updated.tool_timeout_seconds == 60

    def test_to_dict(self):
        """Test converting to dictionary."""
        config = TenantAgentConfig.create_default(tenant_id="tenant-1")

        data = config.to_dict()

        assert data["tenant_id"] == "tenant-1"
        assert data["pattern_learning_enabled"] is True
        assert data["multi_level_thinking_enabled"] is True
        assert "created_at" in data
        assert "updated_at" in data

    def test_from_dict(self):
        """Test creating from dictionary."""
        data = {
            "id": "config-1",
            "tenant_id": "tenant-1",
            "config_type": "custom",
            "llm_model": "gpt-4",
            "llm_temperature": 0.7,
            "pattern_learning_enabled": True,
            "multi_level_thinking_enabled": True,
            "max_work_plan_steps": 15,
            "tool_timeout_seconds": 60,
            "enabled_tools": ["memory_search"],
            "disabled_tools": ["episode_retrieval"],
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        config = TenantAgentConfig.from_dict(data)

        assert config.id == "config-1"
        assert config.tenant_id == "tenant-1"
        assert config.llm_model == "gpt-4"
        assert config.max_work_plan_steps == 15
