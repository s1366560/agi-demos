"""The sandbox registry is the discovery list later wrapped for the model."""

import pytest

from src.server.websocket_server import MCPWebSocketServer
from src.tools.registry import get_tool_registry

REMOVED_AGENT_TOOLS = frozenset(
    {
        "ast_parse",
        "ast_find_symbols",
        "ast_extract_function",
        "ast_get_imports",
        "edit_by_ast",
        "generate_tests",
        "run_tests",
        "analyze_coverage",
    }
)

# Still registered so the platform can call them. The host wrapper drops them.
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

MODEL_VISIBLE_TOOLS = frozenset(
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


def test_registry_drops_python_agent_tools_and_keeps_shared_index() -> None:
    names = frozenset(get_tool_registry().list_names())

    assert names.isdisjoint(REMOVED_AGENT_TOOLS)
    assert PLATFORM_MCP_TOOLS <= names
    assert names == MODEL_VISIBLE_TOOLS | PLATFORM_MCP_TOOLS
    assert len(names) == 47
    assert {
        "bash",
        "read",
        "write",
        "edit",
        "glob",
        "grep",
        "code_index_build",
        "find_definition",
        "find_references",
        "call_graph",
        "dependency_graph",
    } <= names


@pytest.mark.asyncio
async def test_selected_toolsets_define_both_discovery_and_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_TOOLSETS", "files,mcp-management")
    registry = get_tool_registry(str(tmp_path))
    server = MCPWebSocketServer(workspace_dir=str(tmp_path))
    server.register_tools(registry.get_all_tools())
    discovered = {tool["name"] for tool in (await server._handle_list_tools())["tools"]}
    assert "read" in discovered
    assert PLATFORM_MCP_TOOLS <= discovered
    assert "bash" not in discovered
    assert (await server._handle_call_tool({"name": "bash", "arguments": {}}))["isError"]
    (tmp_path / "version").write_text("one")
    result = await server._handle_call_tool({"name": "read", "arguments": {"file_path": "version"}})
    assert not result.get("isError", False)
    assert "one" in str(result["content"])


def test_empty_and_mistyped_toolsets_do_not_grant_default_tools(monkeypatch):
    monkeypatch.setenv("MCP_TOOLSETS", "")
    assert get_tool_registry().list_names() == []
    monkeypatch.setenv("MCP_TOOLSETS", "files,missing")
    with pytest.raises(ValueError, match="missing"):
        get_tool_registry()
