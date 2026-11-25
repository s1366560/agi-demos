"""Scoped, idle-expiring channels for the native project PTY and KasmVNC protocols."""

import asyncio
import base64
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from pydantic import Field, TypeAdapter
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException
from websockets.typing import Subprotocol

from src.configuration.config import get_settings
from src.host.packages.release_pin import ACTIVE_APPLICATION_PIN
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .package_sandbox_operations import _Input, _request, _sandbox

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress

type Kind = Literal["terminal", "desktop"]
type Owner = tuple[str, str, str, str, int, Kind]
CHUNK_SIZE = 32 * 1024


class _Open(_Input):
    action: Literal["open"]
    resolution: Literal["1280x720", "1600x900", "1920x1080", "2560x1440"] = "1280x720"


class _Handle(_Input):
    channel: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{32}$")]


class _Read(_Handle):
    action: Literal["read", "close"]


class _Write(_Handle):
    action: Literal["write"]
    data: Annotated[str, Field(min_length=1, max_length=44_000)]


_ACTION: TypeAdapter[_Open | _Read | _Write] = TypeAdapter(
    Annotated[_Open | _Read | _Write, Field(discriminator="action")]
)


@dataclass
class Channel:
    owner: Owner
    socket: ClientConnection
    remainder: bytes = b""
    timer: asyncio.TimerHandle | None = None
    reading: asyncio.Lock = field(default_factory=asyncio.Lock)


class Channels:
    """Handles have affinity to the admitting API process. A lost handle requires reconnect."""

    def __init__(self: Self) -> None:
        self.live: dict[str, Channel] = {}
        self.slots = asyncio.Semaphore(64)
        self.closing: set[asyncio.Task[None]] = set()

    def renew(self: Self, key: str, item: Channel) -> None:
        if item.timer:
            item.timer.cancel()
        item.timer = asyncio.get_running_loop().call_later(30, self.retire, key)

    def retire(self: Self, key: str) -> None:
        if item := self.live.pop(key, None):
            if item.timer:
                item.timer.cancel()
            task = asyncio.create_task(item.socket.close())
            self.closing.add(task)
            task.add_done_callback(self.closing.discard)
            self.slots.release()

    async def open(
        self: Self, owner: Owner, connect_socket: Callable[[], Awaitable[ClientConnection]]
    ) -> str:
        if self.slots.locked():
            raise OptionalBusinessError("runtime_unavailable", "Sandbox channel capacity reached")
        await self.slots.acquire()
        try:
            socket = await connect_socket()
        except BaseException:
            self.slots.release()
            raise
        key = secrets.token_urlsafe(24)
        self.live[key] = item = Channel(owner, socket)
        self.renew(key, item)
        return key


_channels = Channels()


async def _connect(ctx: "PackageOperationContext", kind: Kind, resolution: str) -> ClientConnection:
    # Both paths terminate at the canonical project authority. Its WS handshake rechecks the actor.
    sandbox = _sandbox(ctx, await _request(ctx, "GET", "", absent_ok=True))
    if sandbox is None:
        raise OptionalBusinessError("runtime_unavailable", "Prepare the project sandbox first")
    path = "/terminal/proxy/ws"
    protocols = []
    if kind == "desktop":
        response = await _request(
            ctx, "POST", "/desktop/session?" + urlencode({"resolution": resolution})
        )
        if not response or (response.get("project_id"), response.get("protocol")) != (
            ctx.scope.project_id,
            "kasmvnc-1",
        ):
            raise OptionalBusinessError("forbidden", "Desktop authority scope mismatch")
        path = "/desktop/proxy/websockify"
        protocols = [Subprotocol("binary")]
    return await _socket(ctx, path, protocols, "ephemeral=true" if kind == "terminal" else "")


async def _socket(
    ctx: "PackageOperationContext", path: str, protocols: list[Subprotocol], query: str = ""
) -> ClientConnection:
    settings = get_settings()
    authority = urlsplit(
        str(settings.project_sandbox_authority_url or f"http://127.0.0.1:{settings.api_port}")
    )
    url = urlunsplit(
        (
            "wss" if authority.scheme == "https" else "ws",
            authority.netloc,
            "/api/v1/projects/" + quote(ctx.scope.project_id, safe="") + "/sandbox" + path,
            query,
            "",
        )
    )
    return await connect(
        url,
        additional_headers={"Authorization": ctx.request.headers.get("Authorization", "")},
        subprotocols=protocols,
        proxy=None,
        open_timeout=10,
        close_timeout=2,
        max_queue=2,
        max_size=8 * 1024 * 1024,
    )


async def _read(item: Channel) -> dict[str, Any]:
    if item.reading.locked():
        raise OptionalBusinessError("conflict", "Sandbox channel already has a reader")
    async with item.reading:
        if not item.remainder:
            try:
                frame = await asyncio.wait_for(item.socket.recv(), timeout=1)
            except TimeoutError:
                return {"data": ""}
            if item.owner[-1] == "terminal" and isinstance(frame, str):
                return {"message": frame}
            if not isinstance(frame, bytes):
                raise OptionalBusinessError("runtime_unavailable", "Invalid desktop frame")
            item.remainder = frame
        chunk, item.remainder = item.remainder[:CHUNK_SIZE], item.remainder[CHUNK_SIZE:]
        return {"data": base64.b64encode(chunk).decode("ascii")}


def _owner(ctx: "PackageOperationContext", kind: Kind) -> Owner:
    pin = ACTIVE_APPLICATION_PIN.get()
    if not pin or (pin.plugin_id, pin.tenant_id, pin.project_id) != (
        "memstack-environments",
        ctx.scope.tenant_id,
        ctx.scope.project_id,
    ):
        raise OptionalBusinessError("forbidden", "A verified release is required")
    return (
        str(ctx.user.id),
        ctx.scope.tenant_id,
        ctx.scope.project_id,
        pin.digest,
        pin.authorization_epoch,
        kind,
    )


async def open_run_terminal(
    ctx: "PackageOperationContext", session_id: str, resume_token: str
) -> dict[str, str]:
    owner = _owner(ctx, "terminal")
    try:
        channel = await _channels.open(
            owner,
            lambda: _socket(
                ctx,
                "/terminal/sessions/" + session_id + "/ws",
                [Subprotocol("memstack.terminal-v2"), Subprotocol(resume_token)],
            ),
        )
    except (WebSocketException, OSError, TimeoutError) as exc:
        raise OptionalBusinessError("runtime_unavailable", "Run terminal is unavailable") from exc
    return {"channel": channel}


async def _exchange(
    ctx: "PackageOperationContext", payload: dict[str, Any], kind: Kind
) -> dict[str, Any]:
    action = _ACTION.validate_python(payload)
    owner = _owner(ctx, kind)
    try:
        if isinstance(action, _Open):
            return {
                "channel": await _channels.open(
                    owner, lambda: _connect(ctx, kind, action.resolution)
                )
            }
        key = action.channel
        item = _channels.live.get(key)
        if not item or item.owner != owner:
            raise OptionalBusinessError(
                "forbidden", "Sandbox channel expired or belongs to another scope"
            )
        _channels.renew(key, item)
        if isinstance(action, _Write):
            if kind == "terminal":
                await item.socket.send(action.data)
            else:
                await item.socket.send(base64.b64decode(action.data, validate=True))
        elif action.action == "close":
            _channels.retire(key)
        else:
            return await _read(item)
        return {}
    except (WebSocketException, OSError, TimeoutError) as exc:
        if not isinstance(action, _Open):
            _channels.retire(action.channel)
        raise OptionalBusinessError("runtime_unavailable", "Sandbox channel disconnected") from exc


async def project_terminal(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    return await _exchange(ctx, payload, "terminal")


async def project_desktop(
    ctx: "PackageOperationContext", payload: dict[str, Any], _progress: "Progress | None"
) -> dict[str, Any]:
    return await _exchange(ctx, payload, "desktop")
