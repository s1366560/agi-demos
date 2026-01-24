"""
Unit tests for CUA adapter module.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.agent.cua.adapter import CUAAdapter
from src.infrastructure.agent.cua.config import CUAConfig, CUAProviderType


class TestCUAAdapter:
    """Tests for CUAAdapter class."""

    @pytest.fixture
    def config(self):
        """Create a test configuration."""
        return CUAConfig(
            enabled=True,
            model="test-model",
            provider=CUAProviderType.DOCKER,
        )

    @pytest.fixture
    def disabled_config(self):
        """Create a disabled configuration."""
        return CUAConfig(enabled=False)

    @pytest.fixture
    def adapter(self, config):
        """Create a test adapter."""
        return CUAAdapter(config)

    def test_init(self, adapter, config):
        """Test adapter initialization."""
        assert adapter.config == config
        assert adapter.is_enabled is True
        assert adapter.is_initialized is False

    def test_init_disabled(self, disabled_config):
        """Test adapter initialization with disabled config."""
        adapter = CUAAdapter(disabled_config)
        assert adapter.is_enabled is False

    def test_create_tools_disabled(self, disabled_config):
        """Test create_tools returns empty dict when disabled."""
        adapter = CUAAdapter(disabled_config)
        tools = adapter.create_tools()
        assert tools == {}

    def test_create_tools_enabled(self, config):
        """Test create_tools returns tools when enabled."""
        adapter = CUAAdapter(config)

        # Mock the tool imports
        with patch.object(adapter, "create_tools") as mock_create:
            mock_create.return_value = {
                "cua_screenshot": MagicMock(),
                "cua_click": MagicMock(),
            }
            tools = adapter.create_tools()

            assert "cua_screenshot" in tools
            assert "cua_click" in tools

    def test_create_skills_disabled(self, disabled_config):
        """Test create_skills returns empty list when disabled."""
        adapter = CUAAdapter(disabled_config)
        adapter._config.skill.enabled = False
        skills = adapter.create_skills()
        assert skills == []

    def test_create_subagent_disabled(self, disabled_config):
        """Test create_subagent returns None when disabled."""
        adapter = CUAAdapter(disabled_config)
        adapter._config.subagent.enabled = False
        subagent = adapter.create_subagent()
        assert subagent is None

    def test_get_status(self, adapter):
        """Test get_status returns correct information."""
        status = adapter.get_status()

        assert "enabled" in status
        assert "initialized" in status
        assert "provider" in status
        assert "model" in status
        assert "permissions" in status

        assert status["enabled"] is True
        assert status["initialized"] is False
        assert status["provider"] == "docker"

    @pytest.mark.asyncio
    async def test_initialize_when_disabled(self, disabled_config):
        """Test initialize does nothing when disabled."""
        adapter = CUAAdapter(disabled_config)
        await adapter.initialize()
        assert adapter.is_initialized is False

    @pytest.mark.asyncio
    async def test_shutdown(self, adapter):
        """Test shutdown cleans up resources."""
        # Adapter not initialized, should complete without error
        await adapter.shutdown()
        assert adapter.is_initialized is False

    @pytest.mark.asyncio
    async def test_execute_when_disabled(self, disabled_config):
        """Test execute yields error when disabled."""
        adapter = CUAAdapter(disabled_config)

        events = []
        async for event in adapter.execute("test instruction"):
            events.append(event)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert events[0]["data"]["code"] == "CUA_DISABLED"


class TestCUAAdapterOperations:
    """Tests for CUA adapter operations (click, type, screenshot)."""

    @pytest.fixture
    def adapter(self):
        """Create a test adapter."""
        config = CUAConfig(enabled=True)
        return CUAAdapter(config)

    @pytest.mark.asyncio
    async def test_take_screenshot_not_initialized(self, adapter):
        """Test take_screenshot returns None when not initialized."""
        result = await adapter.take_screenshot()
        assert result is None

    @pytest.mark.asyncio
    async def test_click_not_initialized(self, adapter):
        """Test click returns False when not initialized."""
        result = await adapter.click(100, 200)
        assert result is False

    @pytest.mark.asyncio
    async def test_type_text_not_initialized(self, adapter):
        """Test type_text returns False when not initialized."""
        result = await adapter.type_text("hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_scroll_not_initialized(self, adapter):
        """Test scroll returns False when not initialized."""
        result = await adapter.scroll(100, 200, 0, 100)
        assert result is False
