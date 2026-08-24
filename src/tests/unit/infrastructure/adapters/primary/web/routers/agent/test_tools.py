from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers.agent import tools
from src.infrastructure.plugins.v2.agent_tool_capability_projection import (
    AgentToolCapabilityProjectionV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


async def test_list_tools_omits_memory_tools_when_provider_globally_disabled() -> None:
    with patch.object(
        tools,
        "get_settings",
        return_value=SimpleNamespace(
            agent_memory_runtime_mode="plugin",
            agent_memory_tool_provider_mode="disabled",
        ),
    ):
        response = await tools.list_tools(
            current_user=SimpleNamespace(tenant_id="tenant-1"),
        )

    tool_names = {tool.name for tool in response.tools}
    assert "memory_search" not in tool_names
    assert "memory_create" not in tool_names
    assert {"entity_lookup", "episode_retrieval", "graph_query", "summary"}.issubset(tool_names)


async def test_get_tool_capabilities_projects_pinned_v2_generation() -> None:
    generation = object()
    projection = AgentToolCapabilityProjectionV2(
        plugins_total=3,
        plugins_enabled=2,
        tool_contributions=1,
        channel_types=2,
        hook_handlers=4,
        commands=0,
        services=8,
        service_provider_effects=5,
    )

    with (
        patch.object(
            tools,
            "get_settings",
            return_value=SimpleNamespace(
                agent_memory_runtime_mode="plugin",
                agent_memory_tool_provider_mode="plugin",
            ),
        ),
        patch(
            "src.infrastructure.plugins.v2.boundary.current_generation_v2",
            return_value=generation,
        ),
        patch(
            "src.infrastructure.plugins.v2.agent_tool_capability_projection."
            "project_agent_tool_capabilities_v2",
            return_value=projection,
        ) as project_capabilities,
    ):
        response = await tools.get_tool_capabilities(
            current_user=SimpleNamespace(tenant_id="tenant-1"),
        )

    project_capabilities.assert_called_once_with(generation)
    assert response.total_tools == 6
    assert response.core_tools == 6
    assert [(row.domain, row.tool_count) for row in response.domain_breakdown] == [
        ("graph", 1),
        ("memory", 4),
        ("reasoning", 1),
    ]
    assert response.plugin_runtime.model_dump() == {
        "plugins_total": 3,
        "plugins_enabled": 2,
        "tool_factories": 1,
        "registered_tool_factories": 1,
        "channel_types": 2,
        "hook_handlers": 4,
        "commands": 0,
        "services": 8,
        "providers": 5,
    }


async def test_get_tool_capabilities_uses_structured_generation_failure() -> None:
    def _not_pinned() -> None:
        raise RuntimeV2Error(
            "generation_not_pinned",
            "plugin generation is not pinned to the current operation",
        )

    with (
        patch(
            "src.infrastructure.plugins.v2.boundary.current_generation_v2",
            _not_pinned,
        ),
        pytest.raises(HTTPException) as error,
    ):
        await tools.get_tool_capabilities(
            current_user=SimpleNamespace(tenant_id="tenant-1"),
        )

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "generation_not_pinned"


async def test_tool_domains_remain_static_when_memory_provider_is_disabled() -> None:
    generation = object()
    projection = AgentToolCapabilityProjectionV2(
        plugins_total=1,
        plugins_enabled=1,
        tool_contributions=1,
        channel_types=0,
        hook_handlers=0,
        commands=0,
        services=1,
        service_provider_effects=1,
    )
    with (
        patch.object(
            tools,
            "get_settings",
            return_value=SimpleNamespace(
                agent_memory_runtime_mode="plugin",
                agent_memory_tool_provider_mode="disabled",
            ),
        ),
        patch(
            "src.infrastructure.plugins.v2.boundary.current_generation_v2",
            return_value=generation,
        ),
        patch(
            "src.infrastructure.plugins.v2.agent_tool_capability_projection."
            "project_agent_tool_capabilities_v2",
            return_value=projection,
        ),
    ):
        response = await tools.get_tool_capabilities(
            current_user=SimpleNamespace(tenant_id="tenant-1"),
        )

    assert response.total_tools == 4
    assert [(row.domain, row.tool_count) for row in response.domain_breakdown] == [
        ("graph", 1),
        ("memory", 2),
        ("reasoning", 1),
    ]


def test_tool_routes_have_no_v1_runtime_or_subjective_keyword_classifier() -> None:
    source = inspect.getsource(tools)

    assert "get_plugin_runtime_manager" not in source
    assert "get_plugin_registry" not in source
    assert "_classify_domain" not in source
