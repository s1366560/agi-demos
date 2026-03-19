"""Sandbox scope definitions for multi-agent sandbox isolation."""

from __future__ import annotations

from enum import Enum


class SandboxScope(str, Enum):
    """Enum defining how sandbox environments are scoped in a multi-agent system.

    Scopes control sandbox lifecycle and sharing:
    - SESSION: One sandbox per conversation session, shared by all agents.
    - AGENT: Each agent gets its own isolated sandbox instance.
    - SHARED: A persistent sandbox shared across sessions within a project.
    """

    SESSION = "session"
    AGENT = "agent"
    SHARED = "shared"


class SandboxScopeResolver:
    """Pure function resolver for determining sandbox scope from configuration."""

    @staticmethod
    def resolve(
        explicit_scope: SandboxScope | None = None,
        agent_depth: int = 0,
        has_shared_files: bool = False,
    ) -> SandboxScope:
        """Resolve the effective sandbox scope.

        Resolution precedence:
        1. Explicit scope (if provided) always wins.
        2. If agent has shared_files configured, use SHARED.
        3. Root agents (depth 0) default to SESSION.
        4. Child agents default to AGENT (isolated).

        Args:
            explicit_scope: Explicitly configured scope, if any.
            agent_depth: Current agent depth (0 = root).
            has_shared_files: Whether the agent has shared_files configured.

        Returns:
            The resolved SandboxScope.

        Raises:
            ValueError: If agent_depth is negative.
        """
        if agent_depth < 0:
            raise ValueError(f"Agent depth cannot be negative: {agent_depth}")

        if explicit_scope is not None:
            return explicit_scope

        if has_shared_files:
            return SandboxScope.SHARED

        if agent_depth == 0:
            return SandboxScope.SESSION

        return SandboxScope.AGENT
