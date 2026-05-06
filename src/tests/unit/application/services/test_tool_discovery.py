"""Tests for built-in tool discovery service."""

import importlib

import pytest

from src.application.services.agent.tool_discovery import ToolDiscoveryService
from src.infrastructure.agent.tools.define import _TOOL_REGISTRY


@pytest.fixture(autouse=True)
def _ensure_tool_registry_populated():
    """Other unit tests may call ``clear_registry()``; reload tool modules
    so module-level ``@tool_define`` decorators repopulate the registry."""
    if not _TOOL_REGISTRY:
        for modname in (
            "src.infrastructure.agent.tools.clarification",
            "src.infrastructure.agent.tools.decision",
            "src.infrastructure.agent.tools.model_availability_tool",
            "src.infrastructure.agent.tools.multi_agent_action_tools",
            "src.infrastructure.agent.tools.session_status",
            "src.infrastructure.agent.tools.skill_installer",
            "src.infrastructure.agent.tools.web_scrape",
            "src.infrastructure.agent.tools.web_search",
        ):
            mod = importlib.import_module(modname)
            importlib.reload(mod)
    yield


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
