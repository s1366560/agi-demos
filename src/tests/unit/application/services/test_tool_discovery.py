"""Tests for built-in tool discovery service."""

import pytest

from src.application.services.agent.tool_discovery import ToolDiscoveryService


@pytest.mark.asyncio
async def test_tool_discovery_includes_extended_builtin_tools():
    """Discovery should expose the expanded built-in tool set."""
    service = ToolDiscoveryService()

    tools = await service.get_available_tools(
        project_id="proj-test",
        tenant_id="tenant-test",
    )

    names = {tool["name"] for tool in tools}

    assert "web_search" in names
    assert "web_scrape" in names
    assert "skill_installer" in names
    assert "session_status" in names
    assert "list_available_models" in names
