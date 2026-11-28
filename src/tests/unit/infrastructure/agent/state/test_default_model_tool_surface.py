"""Default model tool names after removing the Python AST and pytest agent tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from plugins.business.agent.engine.react.react_agent_tool_policy import (
    filter_non_workspace_conversation_tools,
)
from src.application.services.chat_run_tool_permission_v2 import ChatRunToolPermissionV2
from src.infrastructure.agent.permission.rules import classify_sandbox_tool_permission
from src.infrastructure.agent.state import agent_worker_state as worker
from src.infrastructure.plugins.v2.agent_canvas_tools import AGENT_CANVAS_TOOL_NAMES_V2
from src.infrastructure.plugins.v2.agent_hitl_tools import AGENT_HITL_TOOL_NAMES_V2
from src.infrastructure.plugins.v2.agent_memory_tools import AGENT_MEMORY_TOOL_NAMES_V2
from src.infrastructure.plugins.v2.agent_model_awareness_tools import (
    AGENT_MODEL_AWARENESS_TOOL_NAMES_V2,
)
from src.infrastructure.plugins.v2.agent_orchestration_tools import _AGENT_ORCHESTRATION_TOOLS_V2
from src.infrastructure.plugins.v2.agent_runtime_utility_tools import (
    AGENT_ENV_VAR_TOOL_NAMES_V2,
    AGENT_MCP_REGISTRATION_TOOL_NAMES_V2,
    AGENT_SKILL_MANAGEMENT_TOOL_NAMES_V2,
    AGENT_WEB_TOOL_NAMES_V2,
)
from src.infrastructure.plugins.v2.agent_system_api_tool import AGENT_SYSTEM_API_TOOL_NAME_V2
from src.infrastructure.plugins.v2.agent_task_session_tools import (
    AGENT_CRON_TOOL_NAMES_V2,
    AGENT_PEER_SESSION_TOOL_NAMES_V2,
    AGENT_SESSION_STATUS_TOOL_NAMES_V2,
    AGENT_TODO_TOOL_NAMES_V2,
)

pytestmark = pytest.mark.unit

REMOVED_AGENT_TOOLS = frozenset(
    {
        "analyze_coverage",
        "ast_extract_function",
        "ast_find_symbols",
        "ast_get_imports",
        "ast_parse",
        "edit_by_ast",
        "generate_tests",
        "run_tests",
    }
)

PLATFORM_MCP_TOOLS = frozenset(
    {
        "mcp_server_call_tool",
        "mcp_server_discover_tools",
        "mcp_server_install",
        "mcp_server_list",
        "mcp_server_list_prompts",
        "mcp_server_set_log_level",
        "mcp_server_start",
        "mcp_server_stop",
    }
)

SANDBOX_MODEL_TOOLS = frozenset(
    {
        "bash",
        "batch_edit",
        "batch_export_artifacts",
        "batch_read",
        "call_graph",
        "change_resolution",
        "code_index_build",
        "dependency_graph",
        "deps_check",
        "deps_install",
        "edit",
        "export_artifact",
        "find_definition",
        "find_references",
        "generate_commit",
        "get_desktop_status",
        "get_terminal_status",
        "git_diff",
        "git_log",
        "glob",
        "grep",
        "import_file",
        "import_files_batch",
        "list",
        "list_artifacts",
        "patch",
        "platform_download_workspace_file",
        "platform_list_workspace_files",
        "platform_read_workspace_file",
        "plugin_tool_exec",
        "preview_edit",
        "read",
        "restart_desktop",
        "restart_terminal",
        "start_desktop",
        "start_terminal",
        "stop_desktop",
        "stop_terminal",
        "write",
    }
)

HOST_MODEL_TOOLS = frozenset(
    {
        "agent_definition_manage",
        "agent_history",
        "agent_list",
        "agent_send",
        "agent_sessions",
        "agent_spawn",
        "agent_stop",
        "ask_clarification",
        "canvas_create",
        "canvas_create_interactive",
        "canvas_delete",
        "canvas_update",
        "check_env_vars",
        "cron",
        "get_env_var",
        "list_available_models",
        "memory_create",
        "memory_delete",
        "memory_get",
        "memory_search",
        "memory_update",
        "peer_sessions_history",
        "peer_sessions_list",
        "peer_sessions_send",
        "register_mcp_server",
        "request_decision",
        "request_env_var",
        "session_status",
        "skill_installer",
        "skill_loader",
        "skill_sync",
        "switch_model_next_turn",
        "system_api",
        "todoread",
        "todowrite",
        "web_scrape",
        "web_search",
        "workspace_assign_task",
        "workspace_cancel_task",
        "workspace_health_verdict",
        "workspace_report_blocked",
        "workspace_report_complete",
        "workspace_report_progress",
        "workspace_request_clarification",
        "workspace_respond_clarification",
    }
)


def _host_contribution_names() -> frozenset[str]:
    names = set()
    names |= AGENT_HITL_TOOL_NAMES_V2
    names |= AGENT_MEMORY_TOOL_NAMES_V2
    names |= AGENT_CANVAS_TOOL_NAMES_V2
    names |= AGENT_MODEL_AWARENESS_TOOL_NAMES_V2
    names |= AGENT_WEB_TOOL_NAMES_V2
    names |= AGENT_SKILL_MANAGEMENT_TOOL_NAMES_V2
    names |= AGENT_ENV_VAR_TOOL_NAMES_V2
    names |= AGENT_MCP_REGISTRATION_TOOL_NAMES_V2
    names |= AGENT_TODO_TOOL_NAMES_V2
    names |= AGENT_PEER_SESSION_TOOL_NAMES_V2
    names |= AGENT_SESSION_STATUS_TOOL_NAMES_V2
    names |= AGENT_CRON_TOOL_NAMES_V2
    names.add(AGENT_SYSTEM_API_TOOL_NAME_V2)
    names.update(tool.name for tool in _AGENT_ORCHESTRATION_TOOLS_V2)
    return frozenset(names)


def test_host_contribution_names_match_the_fixed_contract() -> None:
    assert _host_contribution_names() == HOST_MODEL_TOOLS
    assert len(HOST_MODEL_TOOLS) == 45
    assert HOST_MODEL_TOOLS.isdisjoint(REMOVED_AGENT_TOOLS)


def test_workspace_binding_changes_only_workspace_tools() -> None:
    tools = [SimpleNamespace(name=name) for name in HOST_MODEL_TOOLS | SANDBOX_MODEL_TOOLS]
    bound = filter_non_workspace_conversation_tools(tools, is_workspace_conversation=True)
    unbound = filter_non_workspace_conversation_tools(tools, is_workspace_conversation=False)
    assert {tool.name for tool in bound} == HOST_MODEL_TOOLS | SANDBOX_MODEL_TOOLS
    assert len(bound) == 84
    dropped = {tool.name for tool in bound} - {tool.name for tool in unbound}
    assert dropped == {name for name in HOST_MODEL_TOOLS if name.startswith("workspace_")}
    assert len(unbound) == 76


def test_wrap_exposes_sandbox_tools_and_hides_platform_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "current_mcp_sandbox_adapter_v2", lambda: object())
    listed = [
        {"name": name, "description": name, "input_schema": {"type": "object"}}
        for name in sorted(SANDBOX_MODEL_TOOLS | PLATFORM_MCP_TOOLS)
    ]
    wrapped = worker._wrap_sandbox_tools("sandbox-1", listed)

    assert set(wrapped) == SANDBOX_MODEL_TOOLS
    assert SANDBOX_MODEL_TOOLS.isdisjoint(REMOVED_AGENT_TOOLS)
    assert len(SANDBOX_MODEL_TOOLS) == 39
    assert wrapped["bash"].permission == "bash"
    assert wrapped["read"].permission == "read"
    assert wrapped["edit"].permission == "edit"
    assert wrapped["glob"].permission == "read"
    assert wrapped["grep"].permission == "read"
    assert wrapped["code_index_build"].permission == "write"
    assert wrapped["find_definition"].permission == "read"
    monkeypatch.setattr(worker, "current_mcp_sandbox_adapter_v2", lambda: None)
    assert worker._wrap_sandbox_tools("sandbox-1", listed) == {}


def test_removed_names_are_not_granted_and_bash_stays_a_mutation() -> None:
    assert classify_sandbox_tool_permission("bash") == "bash"
    assert classify_sandbox_tool_permission("read") == "read"
    assert classify_sandbox_tool_permission("mcp_server_list_prompts") == "read"
    assert classify_sandbox_tool_permission("mcp_server_set_log_level") == "mcp"
    for name in REMOVED_AGENT_TOOLS:
        assert classify_sandbox_tool_permission(name) == "ask"


def _guard(mode: str) -> ChatRunToolPermissionV2:
    guard = ChatRunToolPermissionV2(
        operation=object(),  # type: ignore[arg-type]
        run_id="run-1",
        identity=("tenant", "project", "conversation", "user"),
        mode=mode,
        sessions=object(),  # type: ignore[arg-type]
    )
    object.__setattr__(guard, "revalidate_current_authority", AsyncMock())
    return guard


@pytest.mark.asyncio
async def test_bash_cannot_bypass_a_restricted_profile() -> None:
    ask = _guard("ask")
    automatic = _guard("automatic")
    full = _guard("full_access")

    assert await ask.decision("bash", "bash", {}) == "ask"
    assert await automatic.decision("bash", "bash", {}) == "deny"
    assert await full.decision("bash", "bash", {}) == "allow"
    assert await ask.decision("read", "read", {}) == "allow"
    assert await full.decision("ask", "ast_parse", {}) == "deny"
    assert await ask.decision("ask", "run_tests", {}) == "deny"
