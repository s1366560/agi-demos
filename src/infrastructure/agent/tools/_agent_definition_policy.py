"""Shared agent-definition mutation policy.

Encapsulates A2A normalization and update-semantics rules so both the
router and the agent tool reuse identical logic without duplication.
"""

from __future__ import annotations

from typing import Any

from src.domain.model.agent.agent_definition import Agent
from src.infrastructure.agent.sisyphus.builtin_agent import (
    DEFAULT_AGENT_TO_AGENT_ALLOWLIST,
)


def normalize_new_agent_a2a(
    *,
    enabled: bool,
    allowlist: list[str] | None,
) -> list[str] | None:
    """Normalize A2A config for newly created agents."""
    normalized = Agent.normalize_agent_to_agent_allowlist(allowlist)
    if enabled and normalized is None:
        return list(DEFAULT_AGENT_TO_AGENT_ALLOWLIST)
    return normalized


def normalize_updated_agent_a2a(
    agent: Agent,
    updates: dict[str, Any],
) -> None:
    """Normalize A2A fields in-place within an updates dict."""
    has_allowlist_in_updates = "agent_to_agent_allowlist" in updates

    if has_allowlist_in_updates:
        updates["agent_to_agent_allowlist"] = Agent.normalize_agent_to_agent_allowlist(
            updates["agent_to_agent_allowlist"]
        )

    enabled_after = updates.get("agent_to_agent_enabled", agent.agent_to_agent_enabled)
    if not enabled_after:
        return

    if has_allowlist_in_updates:
        if updates["agent_to_agent_allowlist"] is None:
            updates["agent_to_agent_allowlist"] = list(DEFAULT_AGENT_TO_AGENT_ALLOWLIST)
        return

    if (
        updates.get("agent_to_agent_enabled") is True
        and not agent.agent_to_agent_enabled
        and agent.agent_to_agent_allowlist is None
    ):
        updates["agent_to_agent_allowlist"] = list(DEFAULT_AGENT_TO_AGENT_ALLOWLIST)
