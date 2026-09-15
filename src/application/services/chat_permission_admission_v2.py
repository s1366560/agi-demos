"""Canonical chat permission snapshots sourced from the workspace authority."""

from __future__ import annotations

from typing import Any

from src.application.services.agent.runtime_model_route import load_workspace_policy
from src.infrastructure.adapters.secondary.persistence.models import Conversation
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

PERMITTED_REQUEST_MODES = {
    "ask": frozenset({"ask"}),
    "automatic": frozenset({"ask", "automatic"}),
    "full_access": frozenset({"ask", "automatic", "full_access"}),
}
PERMISSION_PROFILES = {
    "ask": "read_only",
    "automatic": "workspace_write",
    "full_access": "full_access",
}


def require_chat_permission_mode(policy: dict[str, Any], requested: str | None) -> str:
    ceiling = policy.get("permission_mode")
    if not isinstance(ceiling, str) or ceiling not in PERMITTED_REQUEST_MODES:
        raise RuntimeV2Error("chat_permission_policy_invalid", "Chat permission policy is invalid")
    effective = requested if requested is not None else ceiling
    if effective not in PERMITTED_REQUEST_MODES[ceiling]:
        raise RuntimeV2Error(
            "chat_permission_policy_denied", "Requested permissions exceed workspace policy"
        )
    return effective


async def load_chat_permission_policy(conversation: Conversation) -> dict[str, Any]:
    # Unbound conversations have no workspace authority granting unattended writes.
    if not getattr(conversation, "workspace_id", None):
        return {"revision": 0, "permission_mode": "ask", "source": "unbound_chat_default"}
    return await load_workspace_policy(conversation)


async def prepare_chat_permission_snapshot(
    conversation: Conversation, requested: str | None
) -> dict[str, Any]:
    policy = await load_chat_permission_policy(conversation)
    effective = require_chat_permission_mode(policy, requested)
    return {
        "schema_version": 1,
        "requested_permission_mode": requested,
        "effective_permission_mode": effective,
        "permission_profile": PERMISSION_PROFILES[effective],
        "policy": policy,
    }
