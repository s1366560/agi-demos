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
    ]
