"""Bind a business-command guest to the host port.

The guest receives the operation, payload, and tenant/project/user ids only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from typing import Any, Protocol

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]

# One JSON line can be a page of records. The default 64 KiB stream buffer truncates it.
RPC_LINE_LIMIT = 32 * 1024 * 1024


class CommandError(OptionalBusinessError):
    pass


class CommandPort(Protocol):
    user_id: str
    tenant_id: str
    project_id: str | None

    async def call(self, name: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def http(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


_port: ContextVar[CommandPort | None] = ContextVar("business_command_port", default=None)


def current() -> CommandPort:
    port = _port.get()
    if port is None:
        raise CommandError("runtime_unavailable", "business command guest is not bound")
    return port


def bind(port: CommandPort) -> Token[CommandPort | None]:
    return _port.set(port)


def reset(token: Token[CommandPort | None]) -> None:
    _port.reset(token)


def bind_operation(operation: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def handler(
        _ctx: object, payload: dict[str, Any], _progress: object
    ) -> dict[str, Any]:
        return await current().call(operation, payload)

    return handler
