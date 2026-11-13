"""Credential checks name only the variables a tool actually declares."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.env_var_tools import make_env_var_tools


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="session",
        message_id="message",
        call_id="call",
        agent_name="agent",
        conversation_id="conversation",
        project_id="project",
        tenant_id="tenant",
        user_id="user",
    )


@pytest.mark.unit
async def test_github_does_not_require_anthropic_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    repository = SimpleNamespace(
        get=AsyncMock(return_value=None),
        get_for_tool=AsyncMock(return_value=[]),
    )
    tools = make_env_var_tools(repository=repository, encryption_service=SimpleNamespace())

    checked = await tools["check_env_vars"].execute(
        _ctx(),
        tool_name="github",
        required_vars=["GITHUB_TOKEN", "ANTHROPIC_API_KEY"],
    )
    payload = json.loads(checked.output)
    assert payload["declared_required"] == ["GITHUB_TOKEN"]
    assert payload["declared_missing"] == ["GITHUB_TOKEN"]
    assert payload["not_declared"] == ["ANTHROPIC_API_KEY"]
    assert "sk-test" not in checked.output

    looked_up = await tools["get_env_var"].execute(
        _ctx(),
        tool_name="bash",
        variable_name="PATH",
    )
    missing = json.loads(looked_up.output)
    assert missing["status"] == "not_found"
    assert missing["source"] == "managed_tool_config"
    assert missing["exists"] is False
    assert missing["process_environment"] == "not_consulted"
    assert "/usr/bin" not in looked_up.output
