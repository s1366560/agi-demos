"""Project lifecycle commands. Pool and actor calls stay on the host port."""

from __future__ import annotations

from typing import Any, Literal

from plugins.business.agent.backend.chat_operations import _Input
from plugins.business.agent.guest.binding import CommandContext, CommandError, Progress, current


class ActorControl(_Input):
    action: Literal["stop", "restart", "pause", "resume"]


def _pool_path(ctx: CommandContext) -> str:
    tenant = getattr(getattr(ctx, "scope", None), "tenant_id", None) or current().tenant_id
    project = getattr(getattr(ctx, "scope", None), "project_id", None) or current().project_id
    if not isinstance(tenant, str) or not isinstance(project, str):
        raise CommandError("forbidden", "project scope required")
    return f"/api/v1/tenants/{tenant}/projects/{project}/pool/instances/chat"


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


async def _canonical_http(
    ctx: CommandContext,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await current().http(method, path, body=body, query=query, absolute=True)


async def project_lifecycle_snapshot(_tenant_id: str, _project_id: str) -> dict[str, Any]:
    return await current().lifecycle_snapshot()


async def call_actor_control(_ctx: CommandContext, action: str) -> str:
    return await current().actor(action)


async def snapshot(ctx: CommandContext) -> dict[str, Any]:
    pool = await _canonical_http(ctx, "GET", _pool_path(ctx))
    project_id = ctx.scope.project_id
    if not isinstance(project_id, str):
        raise CommandError("forbidden", "project scope required")
    actor = await project_lifecycle_snapshot(ctx.scope.tenant_id, project_id)
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


async def control(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    action = ActorControl.model_validate(payload).action
    status = await snapshot(ctx)
    if action not in status["allowed_actions"]:
        raise CommandError("forbidden", "Agent lifecycle action unavailable")
    if not status["pool_managed"]:
        return {"action": action, "status": await call_actor_control(ctx, action + "_agent")}
    path = _pool_path(ctx)
    if action in ("pause", "resume"):
        result = await _canonical_http(ctx, "POST", f"{path}/{action}")
    else:
        result = await _canonical_http(ctx, "DELETE", path)
    if not result.get("success"):
        raise CommandError("apply_failed", "Agent pool did not accept the action")
    return {"action": action, "status": result["action"]}
