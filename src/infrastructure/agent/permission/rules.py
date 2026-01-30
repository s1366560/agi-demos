"""Permission rules definition and evaluation."""

import fnmatch
from dataclasses import dataclass
from enum import Enum
from typing import List


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

    def matches(self, permission: str, target: str) -> bool:
        """
        Check if this rule matches the given permission and target.

        Args:
            permission: The permission being requested
            target: The target (file path, command, etc.)

        Returns:
            True if this rule matches
        """
        return fnmatch.fnmatch(permission, self.permission) and fnmatch.fnmatch(
            target, self.pattern
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "permission": self.permission,
            "pattern": self.pattern,
            "action": self.action.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PermissionRule":
        """Create from dictionary."""
        return cls(
            permission=data["permission"],
            pattern=data["pattern"],
            action=PermissionAction(data["action"]),
        )


def evaluate_rules(
    permission: str,
    pattern: str,
    *rulesets: List[PermissionRule],
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

    Returns:
        The matching rule, or a default ASK rule
    """
    # Merge all rulesets
    merged: List[PermissionRule] = []
    for ruleset in rulesets:
        if ruleset:
            merged.extend(ruleset)

    # Find last matching rule (last match wins)
    for rule in reversed(merged):
        if rule.matches(permission, pattern):
            return rule

    # Default to ASK
    return PermissionRule(permission, "*", PermissionAction.ASK)


def get_disabled_tools(
    tools: List[str],
    ruleset: List[PermissionRule],
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


def default_ruleset() -> List[PermissionRule]:
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
        # Plan tools require ask by default
        PermissionRule("plan_enter", "*", PermissionAction.ASK),
        PermissionRule("plan_exit", "*", PermissionAction.ASK),
        PermissionRule("plan_update", "*", PermissionAction.ALLOW),
    ]


def plan_mode_ruleset() -> List[PermissionRule]:
    """
    Get the permission ruleset for Plan Mode.

    In Plan Mode, the agent has:
    - Read-only access to the codebase
    - Plan editing capability
    - No file modification capability

    Returns:
        List of permission rules for Plan Mode
    """
    return [
        # Deny all file modifications
        PermissionRule("edit", "*", PermissionAction.DENY),
        PermissionRule("write", "*", PermissionAction.DENY),
        PermissionRule("patch", "*", PermissionAction.DENY),
        PermissionRule("multiedit", "*", PermissionAction.DENY),
        PermissionRule("bash", "*", PermissionAction.DENY),  # No shell access
        PermissionRule("code_executor", "*", PermissionAction.DENY),
        # Deny entering plan mode again (already in it)
        PermissionRule("plan_enter", "*", PermissionAction.DENY),
        # Allow plan operations
        PermissionRule("plan_update", "*", PermissionAction.ALLOW),
        PermissionRule("plan_exit", "*", PermissionAction.ALLOW),
        # Allow read operations
        PermissionRule("read", "*", PermissionAction.ALLOW),
        PermissionRule("glob", "*", PermissionAction.ALLOW),
        PermissionRule("grep", "*", PermissionAction.ALLOW),
        # Allow memory and entity operations (read-only)
        PermissionRule("memory_search", "*", PermissionAction.ALLOW),
        PermissionRule("entity_lookup", "*", PermissionAction.ALLOW),
        PermissionRule("episode_retrieval", "*", PermissionAction.ALLOW),
        PermissionRule("graph_query", "*", PermissionAction.ALLOW),
        # Allow web search and clarification
        PermissionRule("web_search", "*", PermissionAction.ALLOW),
        PermissionRule("web_scrape", "*", PermissionAction.ALLOW),
        PermissionRule("ask_clarification", "*", PermissionAction.ALLOW),
        PermissionRule("ask_decision", "*", PermissionAction.ALLOW),
        # Deny memory creation (read-only mode)
        PermissionRule("memory_create", "*", PermissionAction.DENY),
    ]


def explore_mode_ruleset() -> List[PermissionRule]:
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
        # Deny all plan operations (this is a SubAgent)
        PermissionRule("plan_enter", "*", PermissionAction.DENY),
        PermissionRule("plan_exit", "*", PermissionAction.DENY),
        PermissionRule("plan_update", "*", PermissionAction.DENY),
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
        # Using wild permission to match all types for sandbox tools
        PermissionRule("*", "sandbox_*_*", PermissionAction.DENY),
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
        "file_read",
        "read_file",
        "list_files",
        "cat",
        "grep",
        "glob",
        "find",
        "ls",
        "dir",
    }

    # Write-type tools - require user confirmation
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
    }

    # Execute/bash tools - require user confirmation
    execute_tools = {
        "bash",
        "execute",
        "run_command",
        "python",
        "node",
        "sh",
        "shell",
    }

    tool_lower = tool_name.lower()

    if tool_lower in read_tools:
        return "read"
    elif tool_lower in write_tools:
        return "write"
    elif tool_lower in execute_tools:
        return "bash"
    else:
        # Unknown tools default to ASK for safety
        return "ask"


def sandbox_mcp_ruleset() -> List[PermissionRule]:
    """
    Get the permission ruleset for Sandbox MCP tools.

    This ruleset provides fine-grained permission control for MCP tools
    exposed through sandbox instances. Tools are namespaced with the
    pattern: `sandbox_{sandbox_id}_{tool_name}`.

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
        # Read-type tools: allow by default
        PermissionRule("read", "sandbox_*_*_read", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_*_list", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_file_read", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_list_files", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_cat", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_grep", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_glob", PermissionAction.ALLOW),
        PermissionRule("read", "sandbox_*_find", PermissionAction.ALLOW),
        # Write-type tools: ask for confirmation
        PermissionRule("write", "sandbox_*_*_write", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_*_create", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_*_edit", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_*_delete", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_file_write", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_write_file", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_create_file", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_edit_file", PermissionAction.ASK),
        PermissionRule("write", "sandbox_*_delete_file", PermissionAction.ASK),
        # Execute/bash tools: ask for confirmation
        PermissionRule("bash", "sandbox_*_bash", PermissionAction.ASK),
        PermissionRule("bash", "sandbox_*_execute", PermissionAction.ASK),
        PermissionRule("bash", "sandbox_*_run", PermissionAction.ASK),
        PermissionRule("bash", "sandbox_*_python", PermissionAction.ASK),
        PermissionRule("bash", "sandbox_*_sh", PermissionAction.ASK),
        PermissionRule("bash", "sandbox_*_shell", PermissionAction.ASK),
        # Default rule: ask for unknown sandbox tools
        PermissionRule("sandbox_*_*", "*", PermissionAction.ASK),
    ]
