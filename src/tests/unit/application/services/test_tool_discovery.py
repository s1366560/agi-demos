"""Tests for pinned V2 ToolSet discovery projection."""

from types import MappingProxyType, SimpleNamespace

import pytest

from src.application.services.agent.tool_discovery import ToolDiscoveryService
from src.infrastructure.plugins.v2.tool_set import ToolSetV2


@pytest.mark.unit
async def test_tool_discovery_projects_only_the_explicit_turn_tool_set() -> None:
    service = ToolDiscoveryService()
    names = (
        "web_search",
        "web_scrape",
        "skill_installer",
        "session_status",
        "list_available_models",
    )
    tool_set = ToolSetV2(
        tools=MappingProxyType({name: object() for name in names}),
        definitions=tuple(
            SimpleNamespace(name=name, description=f"{name} description") for name in names
        ),
    )

    tools = await service.get_available_tools(
        project_id="proj-test",
        tenant_id="tenant-test",
        tool_set=tool_set,
    )

    assert [tool["name"] for tool in tools] == list(names)
