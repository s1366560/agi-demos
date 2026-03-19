"""Binding scope enum for message routing priority."""

from __future__ import annotations

from enum import Enum


class BindingScope(str, Enum):
    """Priority scope for message-to-agent binding resolution.

    Listed from most specific (highest priority) to least specific.
    The router evaluates bindings in this order and returns the first match.
    """

    CONVERSATION = "conversation"
    USER_AGENT = "user_agent"
    PROJECT_ROLE = "project_role"
    PROJECT = "project"
    TENANT = "tenant"
    DEFAULT = "default"

    @property
    def priority(self) -> int:
        """Return numeric priority (lower = higher priority)."""
        return _SCOPE_PRIORITY[self]


_SCOPE_PRIORITY: dict[BindingScope, int] = {
    BindingScope.CONVERSATION: 0,
    BindingScope.USER_AGENT: 1,
    BindingScope.PROJECT_ROLE: 2,
    BindingScope.PROJECT: 3,
    BindingScope.TENANT: 4,
    BindingScope.DEFAULT: 5,
}
