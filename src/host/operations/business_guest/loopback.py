"""Run a guest shaper in-process against the admitted host port.

Unit tests and direct operation calls use the same projection as the child process.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from plugins.business.guest_runtime.binding import CommandError, Progress, bind, bound, reset
from src.host.operations.admitted_loopback import admitted_client
from src.host.operations.business_guest.data_plane import invoke_data


class _Scope(Protocol):
    tenant_id: str


class _Call(Protocol):
    scope: _Scope
    user: object


Handler = Callable[..., Awaitable[dict[str, Any]]]


def _decode(response: object) -> object:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return {"detail": response.text}


class LoopbackPort:
    def __init__(self, ctx: _Call) -> None:
        self.ctx = ctx
        user = getattr(ctx, "user", None)
        self.user_id = "" if user is None else str(getattr(user, "id", ""))
        self.tenant_id = str(ctx.scope.tenant_id)
        self.project_id = getattr(ctx.scope, "project_id", None)

    async def call(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        del name, payload
        raise CommandError("forbidden", "operation bodies stay in the guest")

    async def http(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with admitted_client(self.ctx) as client:
            response = await client.request(method, path, json=body, params=query, headers=headers)
        return {
            "status": response.status_code,
            "body": _decode(response),
            "headers": {key: value for key, value in response.headers.items()},
        }

    async def data(
        self,
        name: str,
        params: dict[str, Any],
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        return await invoke_data(self.ctx, name, params, progress)


async def call_in_guest(
    ctx: object,
    handler: Handler,
    payload: dict[str, Any],
    progress: Progress | None,
) -> dict[str, Any]:
    if bound():
        return await handler(ctx, payload, progress)
    token = bind(LoopbackPort(ctx))
    try:
        return await handler(ctx, payload, progress)
    finally:
        reset(token)
