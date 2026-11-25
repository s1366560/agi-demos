"""Project-scoped lifecycle controls used by the signed Agent status bar."""

from typing import TYPE_CHECKING, Any, Literal

from src.infrastructure.agent.actor.lifecycle_snapshot import project_lifecycle_snapshot
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .chat_operations import _canonical_http, _Input
from .chat_stream import call_actor_control

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class ActorControl(_Input):
    action: Literal["stop", "restart", "pause", "resume"]


def _pool_path(ctx: "PackageOperationContext") -> str:
    return (
        f"/api/v1/tenants/{ctx.scope.tenant_id}/projects/{ctx.scope.project_id}/pool/instances/chat"
    )


def _pool_state(status: str | None) -> str:
    return {
        "created": "initializing",
        "initializing": "initializing",
        "initialization_failed": "error",
        "unhealthy": "error",
        "degraded": "error",
        "ready": "ready",
        "executing": "executing",
        "paused": "paused",
        "terminating": "shutting_down",
    }.get(status or "", "uninitialized")


async def snapshot(ctx: "PackageOperationContext") -> dict[str, Any]:
    pool = await _canonical_http(ctx, "GET", _pool_path(ctx))
    actor = await project_lifecycle_snapshot(ctx.scope.tenant_id, ctx.scope.project_id)
    state = actor["lifecycle_state"]
    pool_managed = pool["enabled"]
    if pool_managed:
        state = _pool_state((pool.get("instance") or {}).get("status"))
    allowed: list[str] = []
    authority = pool["allowed_actions"]
    if "terminate" in authority:
        if state in ("ready", "executing", "paused"):
            allowed.append("stop")
        if state in ("ready", "executing", "paused", "error"):
            allowed.append("restart")
    if pool_managed and state == "ready" and "pause" in authority:
        allowed.append("pause")
    if pool_managed and state == "paused" and "resume" in authority:
        allowed.append("resume")
    return {
        "lifecycle_state": state,
        "tool_count": actor.get("tool_count", 0),
        "skill_count": actor.get("skill_count", 0),
        "pool_managed": pool_managed,
        "allowed_actions": allowed,
    }


async def control(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    action = ActorControl.model_validate(payload).action
    status = await snapshot(ctx)
    if action not in status["allowed_actions"]:
        raise OptionalBusinessError("forbidden", "Agent lifecycle action unavailable")
    if not status["pool_managed"]:
        return {"action": action, "status": await call_actor_control(ctx, action + "_agent")}
    path = _pool_path(ctx)
    if action in ("pause", "resume"):
        result = await _canonical_http(ctx, "POST", f"{path}/{action}")
    else:
        result = await _canonical_http(ctx, "DELETE", path)
    if not result.get("success"):
        raise OptionalBusinessError("apply_failed", "Agent pool did not accept the action")
    return {"action": action, "status": result["action"]}
