"""Unpublished plugin generations stay a backend status, not an authorization denial."""

from __future__ import annotations

import json

import pytest

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.system_api import (
    make_system_api_tool,
    openapi_for_published_generation,
)
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableRegistryV2,
    RouteTableV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


def _raise_unpublished() -> dict[str, object]:
    raise RuntimeV2Error(
        "route_generation_unavailable",
        "HTTP route table is unavailable for the pinned plugin generation",
    )


@pytest.mark.unit
async def test_system_api_reports_unpublished_generation_without_authorization_language() -> None:
    tool = make_system_api_tool(openapi_schema_provider=_raise_unpublished)
    result = await tool.execute(
        ToolContext(
            session_id="session",
            message_id="message",
            call_id="call",
            agent_name="agent",
            conversation_id="conversation",
            project_id="project",
            tenant_id="tenant",
            user_id="user",
        ),
        action="list",
    )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    payload = json.loads(result.output)
    assert payload["failure_class"] == "backend"
    assert payload["code"] == "route_generation_unavailable"
    assert payload["generation_status"] == "unpublished"
    assert "does not authorize" not in result.output


def _descriptor() -> PluginGenerationDescriptorV2:
    return PluginGenerationDescriptorV2(
        profile_id="profile",
        generation=4,
        digest="cd" * 32,
    )


def _table() -> RouteTableV2:
    async def endpoint() -> dict[str, str]:
        return {"ok": "yes"}

    return RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-http",
                path="/api/value",
                methods=("GET",),
                endpoint=endpoint,
                name="value",
                tags=("Plugin V2",),
            ),
        )
    )


@pytest.mark.unit
async def test_system_api_lists_the_published_generation_table() -> None:
    registry = RouteTableRegistryV2()
    descriptor = _descriptor()
    registry.activate(registry.stage(descriptor, _table()))
    tool = make_system_api_tool(
        openapi_schema_provider=lambda: openapi_for_published_generation(registry, descriptor)
    )
    result = await tool.execute(
        ToolContext(
            session_id="session",
            message_id="message",
            call_id="call",
            agent_name="agent",
            conversation_id="conversation",
            project_id="project",
            tenant_id="tenant",
            user_id="user",
        ),
        action="list",
    )
    payload = json.loads(result.output)
    assert result.is_error is not True
    assert any(item["path_template"] == "/api/value" for item in payload["operations"])
    with pytest.raises(RuntimeV2Error) as raised:
        openapi_for_published_generation(
            registry,
            PluginGenerationDescriptorV2(
                profile_id="profile",
                generation=5,
                digest="cd" * 32,
            ),
        )
    assert raised.value.code == "route_generation_unavailable"
