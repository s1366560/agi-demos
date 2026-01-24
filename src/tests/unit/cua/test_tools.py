"""
Unit tests for CUA tools module.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.cua.tools.computer_action import (
    CUAClickTool,
    CUAScrollTool,
    CUATypeTool,
)
from src.infrastructure.agent.cua.tools.screenshot import CUAScreenshotTool


class TestCUAClickTool:
    """Tests for CUAClickTool."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.click = AsyncMock(return_value=True)
        return adapter

    @pytest.fixture
    def tool(self, mock_adapter):
        """Create a click tool with mock adapter."""
        return CUAClickTool(mock_adapter)

    def test_name(self, tool):
        """Test tool name."""
        assert tool.name == "cua_click"

    def test_description(self, tool):
        """Test tool has description."""
        assert len(tool.description) > 0
        assert "click" in tool.description.lower()

    def test_parameters_schema(self, tool):
        """Test parameters schema."""
        schema = tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]
        assert "x" in schema["required"]
        assert "y" in schema["required"]

    @pytest.mark.asyncio
    async def test_execute_success(self, tool, mock_adapter):
        """Test successful click execution."""
        result = await tool.execute(x=100, y=200)
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["action"] == "click"
        assert result_data["coordinates"]["x"] == 100
        assert result_data["coordinates"]["y"] == 200

        mock_adapter.click.assert_called_once_with(x=100, y=200)

    @pytest.mark.asyncio
    async def test_execute_missing_coords(self, tool):
        """Test click with missing coordinates."""
        result = await tool.execute()
        result_data = json.loads(result)

        assert result_data["success"] is False
        assert "required" in result_data["error"]

    @pytest.mark.asyncio
    async def test_execute_failure(self, tool, mock_adapter):
        """Test click failure."""
        mock_adapter.click = AsyncMock(return_value=False)

        result = await tool.execute(x=100, y=200)
        result_data = json.loads(result)

        assert result_data["success"] is False


class TestCUATypeTool:
    """Tests for CUATypeTool."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.type_text = AsyncMock(return_value=True)
        return adapter

    @pytest.fixture
    def tool(self, mock_adapter):
        """Create a type tool with mock adapter."""
        return CUATypeTool(mock_adapter)

    def test_name(self, tool):
        """Test tool name."""
        assert tool.name == "cua_type"

    def test_parameters_schema(self, tool):
        """Test parameters schema."""
        schema = tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "text" in schema["properties"]
        assert "text" in schema["required"]

    @pytest.mark.asyncio
    async def test_execute_success(self, tool, mock_adapter):
        """Test successful type execution."""
        result = await tool.execute(text="hello world")
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["action"] == "type"
        assert result_data["text_length"] == 11

        mock_adapter.type_text.assert_called_once_with("hello world")

    @pytest.mark.asyncio
    async def test_execute_missing_text(self, tool):
        """Test type with missing text."""
        result = await tool.execute()
        result_data = json.loads(result)

        assert result_data["success"] is False


class TestCUAScrollTool:
    """Tests for CUAScrollTool."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.scroll = AsyncMock(return_value=True)
        return adapter

    @pytest.fixture
    def tool(self, mock_adapter):
        """Create a scroll tool with mock adapter."""
        return CUAScrollTool(mock_adapter)

    def test_name(self, tool):
        """Test tool name."""
        assert tool.name == "cua_scroll"

    def test_parameters_schema(self, tool):
        """Test parameters schema."""
        schema = tool.get_parameters_schema()

        assert "x" in schema["properties"]
        assert "y" in schema["properties"]
        assert "delta_x" in schema["properties"]
        assert "delta_y" in schema["properties"]

    @pytest.mark.asyncio
    async def test_execute_success(self, tool, mock_adapter):
        """Test successful scroll execution."""
        result = await tool.execute(x=100, y=200, delta_y=100)
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["action"] == "scroll"


class TestCUAScreenshotTool:
    """Tests for CUAScreenshotTool."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock adapter."""
        adapter = MagicMock()
        adapter.take_screenshot = AsyncMock(return_value="base64_image_data")
        return adapter

    @pytest.fixture
    def tool(self, mock_adapter):
        """Create a screenshot tool with mock adapter."""
        return CUAScreenshotTool(mock_adapter)

    def test_name(self, tool):
        """Test tool name."""
        assert tool.name == "cua_screenshot"

    def test_parameters_schema(self, tool):
        """Test parameters schema."""
        schema = tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "region" in schema["properties"]
        assert "format" in schema["properties"]

    @pytest.mark.asyncio
    async def test_execute_success(self, tool, mock_adapter):
        """Test successful screenshot execution."""
        result = await tool.execute()
        result_data = json.loads(result)

        assert result_data["success"] is True
        assert result_data["action"] == "screenshot"
        assert result_data["image_base64"] == "base64_image_data"

        mock_adapter.take_screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_failure(self, tool, mock_adapter):
        """Test screenshot failure."""
        mock_adapter.take_screenshot = AsyncMock(return_value=None)

        result = await tool.execute()
        result_data = json.loads(result)

        assert result_data["success"] is False

    def test_output_schema(self, tool):
        """Test output schema for composition."""
        schema = tool.get_output_schema()

        assert schema["type"] == "object"
        assert "image_base64" in schema["properties"]

    def test_can_compose_with(self, tool):
        """Test tool composition compatibility."""
        other_tool = MagicMock()
        assert tool.can_compose_with(other_tool) is True
