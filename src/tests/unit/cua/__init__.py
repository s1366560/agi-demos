"""
Unit tests for CUA configuration module.
"""

import os
from unittest.mock import patch

from src.infrastructure.agent.cua.config import (
    CUAConfig,
    CUADockerConfig,
    CUAOSType,
    CUAPermissionConfig,
    CUAProviderType,
    CUASkillConfig,
    CUASubAgentConfig,
)


class TestCUAConfig:
    """Tests for CUAConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CUAConfig()

        assert config.enabled is False
        assert config.model == "anthropic/claude-sonnet-4-20250514"
        assert config.temperature == 0.0
        assert config.max_steps == 20
        assert config.provider == CUAProviderType.DOCKER
        assert config.os_type == CUAOSType.LINUX

    def test_docker_config_defaults(self):
        """Test Docker configuration defaults."""
        config = CUADockerConfig()

        assert config.image == "ghcr.io/trycua/cua-desktop:latest"
        assert config.display == "1920x1080"
        assert config.memory == "4GB"
        assert config.cpu == "2"
        assert config.vnc_port == 5900
        assert config.novnc_port == 6080

    def test_permission_config_defaults(self):
        """Test permission configuration defaults."""
        config = CUAPermissionConfig()

        assert config.allow_screenshot is True
        assert config.allow_mouse_click is True
        assert config.allow_keyboard_input is True
        assert config.allow_browser_navigation is True
        assert config.allow_file_operations is False
        assert config.allow_command_execution is False

    def test_subagent_config_defaults(self):
        """Test SubAgent configuration defaults."""
        config = CUASubAgentConfig()

        assert config.enabled is True
        assert config.match_threshold == 0.7
        assert len(config.triggers) > 0
        assert "操作电脑" in config.triggers
        assert "use computer" in config.triggers

    def test_skill_config_defaults(self):
        """Test Skill configuration defaults."""
        config = CUASkillConfig()

        assert config.enabled is True
        assert config.match_threshold == 0.8
        assert "web_search" in config.builtin_skills
        assert "form_fill" in config.builtin_skills

    def test_from_env_disabled(self):
        """Test configuration from environment variables with CUA disabled."""
        with patch.dict(os.environ, {"CUA_ENABLED": "false"}, clear=False):
            config = CUAConfig.from_env()
            assert config.enabled is False

    def test_from_env_enabled(self):
        """Test configuration from environment variables with CUA enabled."""
        env_vars = {
            "CUA_ENABLED": "true",
            "CUA_MODEL": "test-model",
            "CUA_TEMPERATURE": "0.5",
            "CUA_MAX_STEPS": "30",
            "CUA_PROVIDER": "docker",
            "CUA_DOCKER_IMAGE": "test-image:latest",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = CUAConfig.from_env()

            assert config.enabled is True
            assert config.model == "test-model"
            assert config.temperature == 0.5
            assert config.max_steps == 30
            assert config.provider == CUAProviderType.DOCKER
            assert config.docker.image == "test-image:latest"

    def test_to_dict(self):
        """Test configuration to dictionary conversion."""
        config = CUAConfig()
        config_dict = config.to_dict()

        assert "enabled" in config_dict
        assert "model" in config_dict
        assert "provider" in config_dict
        assert "docker" in config_dict
        assert "permissions" in config_dict
        assert "subagent" in config_dict
        assert "skill" in config_dict

    def test_provider_type_enum(self):
        """Test CUAProviderType enum values."""
        assert CUAProviderType.LOCAL.value == "local"
        assert CUAProviderType.DOCKER.value == "docker"
        assert CUAProviderType.CLOUD.value == "cloud"

    def test_os_type_enum(self):
        """Test CUAOSType enum values."""
        assert CUAOSType.LINUX.value == "linux"
        assert CUAOSType.MACOS.value == "macos"
        assert CUAOSType.WINDOWS.value == "windows"


class TestCUAProviderConfig:
    """Tests for provider-specific configurations."""

    def test_docker_provider_config(self):
        """Test Docker provider configuration."""
        config = CUAConfig(
            provider=CUAProviderType.DOCKER,
            docker=CUADockerConfig(
                image="custom-image:v1",
                memory="8GB",
                cpu="4",
            ),
        )

        assert config.provider == CUAProviderType.DOCKER
        assert config.docker.image == "custom-image:v1"
        assert config.docker.memory == "8GB"
        assert config.docker.cpu == "4"

    def test_local_provider_config(self):
        """Test local provider configuration."""
        config = CUAConfig(provider=CUAProviderType.LOCAL)
        assert config.provider == CUAProviderType.LOCAL

    def test_cloud_provider_config(self):
        """Test cloud provider configuration."""
        config = CUAConfig(provider=CUAProviderType.CLOUD)
        assert config.provider == CUAProviderType.CLOUD
