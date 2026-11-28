"""Compatibility wrapper. The socket is opened by the host without the caller bearer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.host.operations.agent_package.turn_stream import actor_control, stream_turn as host_stream

if TYPE_CHECKING:
    from plugins.business.agent.guest.binding import CommandContext

__all__ = ["call_actor_control", "stream_turn"]


async def stream_turn(ctx: CommandContext, data: dict[str, Any], progress: object) -> dict[str, Any]:
    return await host_stream(
        ctx.request.app,
        user_id=str(ctx.user.id),
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        data=data,
        progress=progress,
    )


async def call_actor_control(ctx: CommandContext, action: str) -> str:
    return await actor_control(
        ctx.request.app,
        user_id=str(ctx.user.id),
        tenant_id=ctx.scope.tenant_id,
        project_id=ctx.scope.project_id,
        action=action,
    )
