"""Tool policy resolver for multi-layer access control in multi-agent system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolPolicy:
    """Immutable tool access policy for a specific layer.

    Attributes:
        source: Identifies the policy source (e.g. "sandbox", "agent", "subagent").
        precedence: Higher value = evaluated first. Enables layered override semantics.
        allowed: Tools allowed by this layer. None means no restriction from this layer.
                 frozenset({"*"}) means all tools allowed.
                 A non-empty set means only those tools are allowed.
        denied: Tools explicitly denied by this layer.
    """

    source: str
    precedence: int
    allowed: frozenset[str] | None
    denied: frozenset[str] = field(default_factory=frozenset)


class ToolPolicyResolver:
    """Multi-layer tool access control resolver.

    Evaluates tool access by iterating policies in precedence order (highest first).
    A tool is denied if ANY higher-precedence policy denies it or restricts it without inclusion.
    """

    def __init__(self) -> None:
        """Initialize with empty policy list."""
        self._policies: list[ToolPolicy] = []

    def register_policy(self, policy: ToolPolicy) -> None:
        """Register a tool policy and maintain precedence order.

        Args:
            policy: The ToolPolicy to register.
        """
        self._policies.append(policy)
        # Sort by precedence descending (highest first)
        self._policies.sort(key=lambda p: p.precedence, reverse=True)

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed across all registered policies.

        Evaluation order: highest precedence first.
        - If a policy denies the tool → return False
        - If a policy restricts allowed (not None) and tool not in allowed (and "*" not in allowed) → return False
        - If all policies pass → return True

        Args:
            tool_name: Name of the tool to check.

        Returns:
            True if the tool is allowed, False otherwise.
        """
        for policy in self._policies:
            # Check explicit denial
            if tool_name in policy.denied:
                return False

            # Check allowed restriction
            if policy.allowed is not None:
                # If allowed is specified, tool must be in it or "*" must be in it
                if tool_name not in policy.allowed and "*" not in policy.allowed:
                    return False

        # All policies passed
        return True

    def filter_tools(self, tool_names: list[str]) -> list[str]:
        """Filter a list of tools to only those that are allowed.

        Args:
            tool_names: List of tool names to filter.

        Returns:
            List of tools that passed access control, in original order.
        """
        return [t for t in tool_names if self.is_allowed(t)]

    def get_denial_reason(self, tool_name: str) -> str | None:
        """Get human-readable reason for tool denial, if applicable.

        Args:
            tool_name: Name of the tool to check.

        Returns:
            Human-readable reason string if denied, None if allowed.
        """
        for policy in self._policies:
            # Check explicit denial
            if tool_name in policy.denied:
                return f"Denied by {policy.source} policy"

            # Check allowed restriction
            if policy.allowed is not None:
                if tool_name not in policy.allowed and "*" not in policy.allowed:
                    return f"Not allowed by {policy.source} policy (allowed: {', '.join(sorted(policy.allowed)) if policy.allowed != frozenset(['*']) else 'all'})"

        return None
