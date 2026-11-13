"""Unpublished plugin generations stay a backend status, not an authorization denial."""

from __future__ import annotations

import json

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.system_api import make_system_api_tool
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
