"""Skill type definitions used at the agent runtime.

After the Wave 5.1 cleanup and the 2026 skill-system refactor, the
runtime only needs a small structural Protocol describing the subset
of Skill attributes touched by the ReAct agent (forced-skill matching,
prompt injection, tool whitelisting).

Implicit skill matching, success/failure counters, and the legacy
SkillOrchestrator / SkillExecutionMode / SkillMatchResult /
SkillExecutionConfig types have been removed; nothing imports them
anymore.
"""

from __future__ import annotations

from typing import Any, Protocol


class SkillProtocol(Protocol):
    """Structural interface for Skill objects consumed by the agent runtime.

    The agent only reads a flat view of a skill: its identity, the
    declared tool whitelist, the Markdown body to inject as a mandatory
    prompt, an opaque status field, and the agent-mode accessibility
    check used to gate which skills are visible per agent mode.
    """

    id: str
    name: str
    description: str
    tools: list[str]
    full_content: str | None
    status: Any  # SkillStatus enum

    def is_accessible_by_agent(self, agent_mode: str) -> bool:
        """Return True if this skill is exposed under the given agent mode."""
        ...
