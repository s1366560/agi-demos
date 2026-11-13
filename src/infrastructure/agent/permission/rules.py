"""Permission rules definition and evaluation."""

import fnmatch
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RuleScope(str, Enum):
    """Scope of a permission rule."""

    AGENT = "agent"  # Agent-level (most broad)
    USER = "user"  # User-level
    SESSION = "session"  # Session-level (most specific)


class PermissionAction(Enum):
    """Permission action types - Reference: OpenCode permission/next.ts"""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class PermissionRule:
    """
    Permission rule definition.

    A rule consists of:
    - permission: The permission type (e.g., "read", "edit", "bash")
    - pattern: A glob pattern for the target (e.g., "*.env", "git*")
    - action: What to do when this rule matches (allow/deny/ask)

    Rules are evaluated in order, with later rules taking precedence.
    """

    permission: str
    pattern: str
    action: PermissionAction
    scope: RuleScope = RuleScope.AGENT
    arg_pattern: str | None = None

    def matches(
        self,
        permission: str,
        target: str,
        args: dict[str, Any] | None = None,
    ) -> bool:
        """Check if this rule matches the given permission, target, and optionally args.

        Args:
            permission: The permission being requested
            target: The target (file path, command, etc.)
            args: Optional tool arguments to match against arg_pattern

        Returns:
            True if this rule matches
        """
        if not (
            fnmatch.fnmatch(permission, self.permission) and fnmatch.fnmatch(target, self.pattern)
        ):
            return False
        if self.arg_pattern is None:
            return True
        if args is None:
            return True  # No args to check; pattern matches permission+target
        return self._match_arg_pattern(args)

    def _match_arg_pattern(self, args: dict[str, Any]) -> bool:
        """Match arg_pattern against tool arguments.

        Format: "key:value_glob" where key is the argument name and value_glob
        is a glob pattern matched against str(arg_value).
        """
        if not self.arg_pattern:
            return True
        colon_idx = self.arg_pattern.find(":")
        if colon_idx < 0:
            return True  # Malformed pattern, treat as match
        key = self.arg_pattern[:colon_idx].strip()
        value_pattern = self.arg_pattern[colon_idx + 1 :].strip()
        arg_value = args.get(key)
        if arg_value is None:
            return False
        return fnmatch.fnmatch(str(arg_value), value_pattern)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "permission": self.permission,
            "pattern": self.pattern,
            "action": self.action.value,
        }
        if self.scope != RuleScope.AGENT:
            result["scope"] = self.scope.value
        if self.arg_pattern is not None:
            result["arg_pattern"] = self.arg_pattern
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionRule":
        """Create from dictionary."""
        return cls(
            permission=data["permission"],
            pattern=data["pattern"],
            action=PermissionAction(data["action"]),
            scope=RuleScope(data["scope"]) if "scope" in data else RuleScope.AGENT,
            arg_pattern=data.get("arg_pattern"),
        )


def evaluate_rules(
    permission: str,
    pattern: str,
    *rulesets: list[PermissionRule],
    args: dict[str, Any] | None = None,
) -> PermissionRule:
    """
    Evaluate permission against multiple rulesets.

    Uses "last match wins" strategy - later rules override earlier ones.
    If no match is found, returns a default ASK rule.

    Reference: OpenCode evaluate()

    Args:
        permission: The permission type being requested
        pattern: The target pattern to check
        *rulesets: Variable number of rule lists to check
        args: Optional tool arguments for arg_pattern matching

    Returns:
        The matching rule, or a default ASK rule
    """
    # Merge all rulesets
    merged: list[PermissionRule] = []
    for ruleset in rulesets:
        if ruleset:
            merged.extend(ruleset)

    # Find last matching rule (last match wins)
    for rule in reversed(merged):
        if rule.matches(permission, pattern, args):
            return rule

    # Default to ASK
    return PermissionRule(permission, "*", PermissionAction.ASK)


def get_disabled_tools(
    tools: list[str],
    ruleset: list[PermissionRule],
) -> set[str]:
    """
    Get the set of tools that are fully disabled.

    A tool is disabled if there's a DENY rule with pattern "*"
    for that tool's permission.

    Reference: OpenCode disabled()

    Args:
        tools: List of tool names to check
        ruleset: Rules to evaluate against

    Returns:
        Set of disabled tool names
    """
    result = set()

    # Tools that map to "edit" permission
    EDIT_TOOLS = {"edit", "write", "patch", "multiedit"}

    for tool in tools:
        # Edit tools share the "edit" permission
        permission = "edit" if tool in EDIT_TOOLS else tool

        # Find last matching rule
        for rule in reversed(ruleset):
            if fnmatch.fnmatch(permission, rule.permission):
                # Only disable if DENY + wildcard pattern
                if rule.pattern == "*" and rule.action == PermissionAction.DENY:
                    result.add(tool)
                break

    return result


def default_ruleset() -> list[PermissionRule]:
    """
    Get the default permission ruleset.

    Reference: OpenCode agent.ts defaults

    Returns:
        List of default permission rules
    """
    return [
        # Allow all by default
        PermissionRule("*", "*", PermissionAction.ALLOW),
        # Ask for doom loop (repeated tool calls)
        PermissionRule("doom_loop", "*", PermissionAction.ASK),
        # Ask for external directory access
        PermissionRule("external_directory", "*", PermissionAction.ASK),
        # Ask for .env files (but allow .env.example)
        PermissionRule("read", "*.env", PermissionAction.ASK),
        PermissionRule("read", "*.env.*", PermissionAction.ASK),
        PermissionRule("read", "*.env.example", PermissionAction.ALLOW),
        # Deny question tool by default (requires explicit enable)
        PermissionRule("question", "*", PermissionAction.DENY),
    ]


def explore_mode_ruleset() -> list[PermissionRule]:
    """
    Get the permission ruleset for Explore Mode (SubAgent).

    In Explore Mode, the agent has:
    - Pure read-only access
    - No plan editing capability
    - No file modification capability
    - No sandbox access (pure codebase exploration)

    Returns:
        List of permission rules for Explore Mode
    """
    return [
        # Deny all modifications
        PermissionRule("edit", "*", PermissionAction.DENY),
        PermissionRule("write", "*", PermissionAction.DENY),
        PermissionRule("patch", "*", PermissionAction.DENY),
        PermissionRule("multiedit", "*", PermissionAction.DENY),
        PermissionRule("bash", "*", PermissionAction.DENY),
        PermissionRule("code_executor", "*", PermissionAction.DENY),
        # Allow read operations
        PermissionRule("read", "*", PermissionAction.ALLOW),
        PermissionRule("glob", "*", PermissionAction.ALLOW),
        PermissionRule("grep", "*", PermissionAction.ALLOW),
        # Allow memory and entity operations (read-only)
        PermissionRule("memory_search", "*", PermissionAction.ALLOW),
        PermissionRule("entity_lookup", "*", PermissionAction.ALLOW),
        PermissionRule("episode_retrieval", "*", PermissionAction.ALLOW),
        PermissionRule("graph_query", "*", PermissionAction.ALLOW),
        # Allow web search
        PermissionRule("web_search", "*", PermissionAction.ALLOW),
        PermissionRule("web_scrape", "*", PermissionAction.ALLOW),
        # Deny memory creation
        PermissionRule("memory_create", "*", PermissionAction.DENY),
        # Deny human interaction tools (SubAgent cannot ask user)
        PermissionRule("ask_clarification", "*", PermissionAction.DENY),
        PermissionRule("ask_decision", "*", PermissionAction.DENY),
        # Deny all sandbox tools in explore mode (must come AFTER read allow rule)
        # Sandbox tools use original names like "bash", "write", etc.
        PermissionRule("*", "bash", PermissionAction.DENY),
        PermissionRule("*", "write", PermissionAction.DENY),
        PermissionRule("*", "file_write", PermissionAction.DENY),
        PermissionRule("*", "edit", PermissionAction.DENY),
        PermissionRule("*", "patch", PermissionAction.DENY),
        PermissionRule("*", "execute", PermissionAction.DENY),
    ]


# === Sandbox MCP Tool Permission Rules ===


def classify_sandbox_tool_permission(tool_name: str) -> str:
    """
    Classify a sandbox MCP tool by its permission type.

    This function determines which permission category a tool belongs to
    based on its name. The permission type controls how the tool is
    handled by the permission system.

    Args:
        tool_name: The name of the MCP tool (e.g., "bash", "file_read")

    Returns:
        Permission type: "read", "write", "bash", or "ask"

    Examples:
        >>> classify_sandbox_tool_permission("file_read")
        'read'
        >>> classify_sandbox_tool_permission("bash")
        'bash'
        >>> classify_sandbox_tool_permission("unknown")
        'ask'
    """
    # Read-type tools - allow by default
    read_tools = {
        "read",
        "batch_read",
        "list",
        "file_read",
        "read_file",
        "list_files",
        "list_artifacts",
        "cat",
        "grep",
        "glob",
        "find",
        "ls",
        "dir",
        # Fixed AST inspection endpoints read source without executing it.
        "ast_parse",
        "ast_find_symbols",
        "ast_extract_function",
        "ast_get_imports",
        # Fixed sandbox protocol inspection endpoints; these do not invoke tools.
        "mcp_server_list",
        "mcp_server_list_prompts",
        "mcp_server_get_prompt",
        "mcp_server_list_resources",
        "mcp_server_read_resource",
        "mcp_server_discover_tools",
        "preview_edit",
        "git_log",
        "git_diff",
        "find_definition",
        "find_references",
        "call_graph",
        "dependency_graph",
        "get_desktop_status",
        "get_terminal_status",
        "platform_list_workspace_files",
        "platform_read_workspace_file",
        "platform_download_workspace_file",
    }

    # Write-type tools - require user confirmation outside full_access.
    write_tools = {
        "file_write",
        "write_file",
        "create_file",
        "edit_file",
        "delete_file",
        "remove",
        "rm",
        "mv",
        "rename",
        "mkdir",
        "touch",
        "write",
        "import_file",
        "import_files_batch",
        "code_index_build",
        "generate_commit",
    }
    edit_tools = {"edit", "batch_edit", "edit_by_ast"}
    patch_tools = {"patch"}

    # Execute/bash tools - require user confirmation outside full_access.
    execute_tools = {
        "bash",
        "execute",
        "run_command",
        "python",
        "node",
        "sh",
        "shell",
        "deps_check",
        "deps_install",
        "run_tests",
        "generate_tests",
        "analyze_coverage",
        "start_desktop",
        "stop_desktop",
        "restart_desktop",
        "change_resolution",
        "start_terminal",
        "stop_terminal",
        "restart_terminal",
    }
    mcp_tools = {
        "mcp_server_set_log_level",
        "mcp_server_install",
        "mcp_server_start",
        "mcp_server_stop",
        "mcp_server_call_tool",
    }
    plugin_tools = {"plugin_tool_exec"}

    categories = (
        (read_tools, "read"),
        (edit_tools, "edit"),
        (patch_tools, "patch"),
        (write_tools, "write"),
        (execute_tools, "bash"),
        (mcp_tools, "mcp"),
        (plugin_tools, "plugin_manager"),
    )
    tool_lower = tool_name.lower()
    for names, category in categories:
        if tool_lower in names:
            return category
    # Unknown tools stay outside the declared categories. full_access does not
    # promote this sentinel into a grant.
    return "ask"


def sandbox_tool_permission_resolver(
    tool_name: str,
) -> Callable[[dict[str, Any]], str | None] | None:
    """Return argument effects for a fixed sandbox protocol definition."""
    return _deps_check_permission if tool_name == "deps_check" else None


def _deps_check_permission(arguments: dict[str, Any]) -> str | None:
    package_type = arguments.get("package_type", "pip")
    if not isinstance(package_type, str):
        return None
    if package_type == "command":
        # This branch only calls shutil.which; it never runs the located file.
        return "read"
    if package_type in {"pip", "system"}:
        # These branches invoke subprocesses, including a caller-selected venv pip.
        return "bash"
    return None


def sandbox_mcp_ruleset() -> list[PermissionRule]:
    """
    Get the permission ruleset for Sandbox MCP tools.

    This ruleset provides fine-grained permission control for MCP tools
    exposed through sandbox instances. Tools are registered with their
    original names (e.g., "bash", "file_read", "grep").

    Permission Strategy:
    - Read tools (file_read, list_files, etc): ALLOW by default
    - Write tools (file_write, create_file, etc): ASK for confirmation
    - Execute tools (bash, execute, etc): ASK for confirmation

    The rules are designed to:
    1. Allow safe read operations without interruption
    2. Require confirmation for potentially destructive write operations
    3. Require confirmation for code execution
    4. Work with the agent's permission modes (BUILD/PLAN/EXPLORE)

    Returns:
        List of permission rules for sandbox MCP tools

    Note:
        In PLAN mode, all sandbox tools are still subject to plan_mode_ruleset
        which denies write and bash operations. In EXPLORE mode, all sandbox
        tools are denied for pure read-only access.
    """
    return [
        # Default rule: ask for unknown sandbox tools (must be first - last match wins)
        PermissionRule("*", "*", PermissionAction.ASK),
        # Read-type tools: allow by default
        PermissionRule("read", "read", PermissionAction.ALLOW),
        PermissionRule("read", "file_read", PermissionAction.ALLOW),
        PermissionRule("read", "list_files", PermissionAction.ALLOW),
        PermissionRule("read", "cat", PermissionAction.ALLOW),
        PermissionRule("read", "grep", PermissionAction.ALLOW),
        PermissionRule("read", "glob", PermissionAction.ALLOW),
        PermissionRule("read", "find", PermissionAction.ALLOW),
        # Write-type tools: ask for confirmation
        PermissionRule("write", "write", PermissionAction.ASK),
        PermissionRule("write", "file_write", PermissionAction.ASK),
        PermissionRule("write", "write_file", PermissionAction.ASK),
        PermissionRule("write", "create_file", PermissionAction.ASK),
        PermissionRule("write", "edit_file", PermissionAction.ASK),
        PermissionRule("write", "delete_file", PermissionAction.ASK),
        PermissionRule("write", "edit", PermissionAction.ASK),
        PermissionRule("write", "patch", PermissionAction.ASK),
        # Execute/bash tools: ask for confirmation
        PermissionRule("bash", "bash", PermissionAction.ASK),
        PermissionRule("bash", "execute", PermissionAction.ASK),
        PermissionRule("bash", "run", PermissionAction.ASK),
        PermissionRule("bash", "python", PermissionAction.ASK),
        PermissionRule("bash", "sh", PermissionAction.ASK),
        PermissionRule("bash", "shell", PermissionAction.ASK),
    ]
