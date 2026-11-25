"""Read the current project Agent state without creating its actor."""

from typing import Any


async def project_lifecycle_snapshot(tenant_id: str, project_id: str) -> dict[str, Any]:
    from src.infrastructure.adapters.secondary.ray.client import await_ray
    from src.infrastructure.agent.actor.actor_manager import get_actor_if_exists

    actor = await get_actor_if_exists(
        tenant_id=tenant_id, project_id=project_id, agent_mode="default"
    )
    if not actor:
        return {"lifecycle_state": "uninitialized", "is_active": False, "is_initialized": False}
    status = await await_ray(actor.status.remote())
    lifecycle = (
        "initializing"
        if not status.is_initialized
        else "executing"
        if status.is_executing
        else "ready"
    )
    return {
        "lifecycle_state": lifecycle,
        "is_active": status.is_active,
        "is_initialized": status.is_initialized,
        "tool_count": status.tool_count or 0,
        "skill_count": status.skill_count or 0,
        "subagent_count": status.subagent_count or 0,
        "error_message": None,
    }
