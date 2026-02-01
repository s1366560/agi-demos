"""Tool registry for MCP server.

Manages registration and discovery of MCP tools.
"""

import logging
from typing import Dict, List

from src.server.websocket_server import MCPTool
from src.tools.artifact_tools import (
    create_batch_export_artifacts_tool,
    create_export_artifact_tool,
    create_list_artifacts_tool,
)
from src.tools.ast_tools import (
    create_ast_extract_function_tool,
    create_ast_find_symbols_tool,
    create_ast_get_imports_tool,
    create_ast_parse_tool,
)
from src.tools.bash_tool import create_bash_tool
from src.tools.desktop_tools import (
    create_desktop_status_tool,
    create_restart_desktop_tool,
    create_start_desktop_tool,
    create_stop_desktop_tool,
)
from src.tools.edit_tools import (
    create_batch_edit_tool,
    create_edit_by_ast_tool,
    create_preview_edit_tool,
)
from src.tools.file_tools import (
    create_edit_tool,
    create_glob_tool,
    create_grep_tool,
    create_list_tool,
    create_patch_tool,
    create_read_tool,
    create_write_tool,
)
from src.tools.git_tools import (
    create_generate_commit_tool,
    create_git_diff_tool,
    create_git_log_tool,
)
from src.tools.index_tools import (
    create_call_graph_tool,
    create_code_index_build_tool,
    create_dependency_graph_tool,
    create_find_definition_tool,
    create_find_references_tool,
)
from src.tools.terminal_tools import (
    create_restart_terminal_tool,
    create_start_terminal_tool,
    create_stop_terminal_tool,
    create_terminal_status_tool,
)
from src.tools.test_tools import (
    create_analyze_coverage_tool,
    create_generate_tests_tool,
    create_run_tests_tool,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry for MCP tools.

    Manages tool registration and provides tool discovery.
    """

    def __init__(self, workspace_dir: str = "/workspace"):
        """
        Initialize the tool registry.

        Args:
            workspace_dir: Root directory for file operations
        """
        self.workspace_dir = workspace_dir
        self._tools: Dict[str, MCPTool] = {}

    def register(self, tool: MCPTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def get(self, name: str) -> MCPTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[MCPTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def list_names(self) -> List[str]:
        """List all tool names."""
        return list(self._tools.keys())


def get_tool_registry(workspace_dir: str = "/workspace") -> ToolRegistry:
    """
    Create and populate a tool registry with all available tools.

    Args:
        workspace_dir: Root directory for file operations

    Returns:
        Populated tool registry
    """
    registry = ToolRegistry(workspace_dir)

    # Register file tools
    registry.register(create_read_tool())
    registry.register(create_write_tool())
    registry.register(create_edit_tool())
    registry.register(create_glob_tool())
    registry.register(create_grep_tool())
    registry.register(create_list_tool())
    registry.register(create_patch_tool())

    # Register artifact tools
    registry.register(create_export_artifact_tool())
    registry.register(create_list_artifacts_tool())
    registry.register(create_batch_export_artifacts_tool())

    # Register bash tool
    registry.register(create_bash_tool())

    # Register AST tools
    registry.register(create_ast_parse_tool())
    registry.register(create_ast_find_symbols_tool())
    registry.register(create_ast_extract_function_tool())
    registry.register(create_ast_get_imports_tool())

    # Register code indexing tools
    registry.register(create_code_index_build_tool())
    registry.register(create_find_definition_tool())
    registry.register(create_find_references_tool())
    registry.register(create_call_graph_tool())
    registry.register(create_dependency_graph_tool())

    # Register edit tools
    registry.register(create_edit_by_ast_tool())
    registry.register(create_batch_edit_tool())
    registry.register(create_preview_edit_tool())

    # Register test tools
    registry.register(create_generate_tests_tool())
    registry.register(create_run_tests_tool())
    registry.register(create_analyze_coverage_tool())

    # Register git tools
    registry.register(create_git_diff_tool())
    registry.register(create_git_log_tool())
    registry.register(create_generate_commit_tool())

    # Register terminal tools
    registry.register(create_start_terminal_tool())
    registry.register(create_stop_terminal_tool())
    registry.register(create_terminal_status_tool())
    registry.register(create_restart_terminal_tool())

    # Register desktop tools
    registry.register(create_start_desktop_tool())
    registry.register(create_stop_desktop_tool())
    registry.register(create_desktop_status_tool())
    registry.register(create_restart_desktop_tool())

    logger.info(f"Tool registry initialized with {len(registry.list_names())} tools")
    return registry
