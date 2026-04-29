"""System actor identities for the durable workspace plan runtime."""

from __future__ import annotations

WORKSPACE_PLAN_SYSTEM_ACTOR_ID = "workspace-plan:system"
LEGACY_SISYPHUS_AGENT_ID = "builtin:sisyphus"


def persisted_attempt_leader_agent_id(leader_agent_id: str | None) -> str | None:
    """Return the agent-definition-backed leader id safe for attempt rows."""

    if leader_agent_id == WORKSPACE_PLAN_SYSTEM_ACTOR_ID:
        return None
    return leader_agent_id


__all__ = [
    "LEGACY_SISYPHUS_AGENT_ID",
    "WORKSPACE_PLAN_SYSTEM_ACTOR_ID",
    "persisted_attempt_leader_agent_id",
]
