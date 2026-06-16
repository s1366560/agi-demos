"""Tool policy value objects for controlling tool access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.shared_kernel import ValueObject


class ToolPolicyPrecedence(str, Enum):
    ALLOW_FIRST = "allow_first"
    DENY_FIRST = "deny_first"


class ControlMessageType(str, Enum):
    STEER = "steer"
    KILL = "kill"
    PAUSE = "pause"
    RESUME = "resume"


@dataclass(frozen=True)
class ToolPolicy(ValueObject):
    """Immutable allow/deny policy for tool access.

    A non-empty allow list restricts access to listed tools unless it contains
    ``"*"``. DENY_FIRST denies conflicts; ALLOW_FIRST permits conflicts.
    """

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    precedence: ToolPolicyPrecedence = ToolPolicyPrecedence.DENY_FIRST

    def is_allowed(self, tool_name: str) -> bool:
        explicitly_allowed = tool_name in self.allow or "*" in self.allow
        has_allow_restriction = bool(self.allow) and "*" not in self.allow

        if self.precedence == ToolPolicyPrecedence.DENY_FIRST:
            if tool_name in self.deny:
                return False
            return explicitly_allowed or not has_allow_restriction

        if explicitly_allowed:
            return True
        if tool_name in self.deny:
            return False
        return not has_allow_restriction

    def filter_tools(self, tool_names: tuple[str, ...] | list[str]) -> list[str]:
        return [t for t in tool_names if self.is_allowed(t)]
