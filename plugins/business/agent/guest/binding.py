"""Bind the command guest to a host port."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from typing import Any, Protocol

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]

# One JSON line carries a transcript page. The default 64 KiB stream buffer is too small.
RPC_LINE_LIMIT = 32 * 1024 * 1024


class CommandScope(Protocol):
    tenant_id: str
    project_id: str | None


class CommandUser(Protocol):
    id: str


class CommandContext(Protocol):
    scope: CommandScope
    user: CommandUser


class CommandError(OptionalBusinessError):
    pass


class CommandPort(Protocol):
    user_id: str
    tenant_id: str
    project_id: str | None

    async def http(
        self,
        method: str,
        path: str,
        *,
        project_route: bool = False,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        absolute: bool = False,
    ) -> dict[str, Any]: ...

    async def own(self, conversation_id: str) -> None: ...

    async def local_ids(self, ids: list[str]) -> list[str]: ...

    async def meta(self, conversation_id: str) -> dict[str, Any] | None: ...

    async def placements(self, ids: list[str]) -> dict[str, str]: ...

    async def run_cloud(self, run_id: str, conversation_id: str) -> bool: ...

    async def run_conversation(self, run_id: str) -> str | None: ...

    async def run_fields(self, run_id: str, conversation_id: str) -> dict[str, Any]: ...

    async def device(self, op: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def stream(
        self, message: dict[str, Any], progress: Progress | None
    ) -> dict[str, Any]: ...

    async def actor(self, action: str) -> str: ...

    async def voice(self, conversation_id: str) -> dict[str, str]: ...

    async def welcome(self, complete: bool | None) -> dict[str, Any]: ...

    async def model_routes(self) -> dict[str, Any]: ...

    async def lifecycle_snapshot(self) -> dict[str, Any]: ...

    async def templates(self, limit: int) -> list[dict[str, Any]]: ...

    async def hitl(self, conversation_id: str, request_id: str) -> dict[str, Any] | None: ...

    async def attachment_files(
        self, conversation_id: str, ids: list[str]
    ) -> dict[str, dict[str, Any]]: ...

    async def attachment(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def dashboard(self, op: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def tenant_sessions(self, op: str, payload: dict[str, Any]) -> dict[str, Any]: ...


_port: ContextVar[CommandPort | None] = ContextVar("agent_command_port", default=None)


def bound() -> bool:
    return _port.get() is not None


def current() -> CommandPort:
    port = _port.get()
    if port is None:
        raise CommandError("runtime_unavailable", "agent command guest is not bound")
    return port


def bind(port: CommandPort) -> Token[CommandPort | None]:
    return _port.set(port)


def reset(token: Token[CommandPort | None]) -> None:
    _port.reset(token)
