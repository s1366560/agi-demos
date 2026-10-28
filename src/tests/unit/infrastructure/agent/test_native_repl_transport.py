"""Declared REPL wire formats reach real receive/chunk/result logic without Redis I/O."""

from __future__ import annotations

import base64
import copy
import json
import struct
import time
import zlib
from typing import TYPE_CHECKING, Any

import pytest

from src.infrastructure.agent.native_computer_use.media import MAX_CHUNK_BYTES, MediaTransport
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError, request_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.infrastructure.agent.tools.result import ToolResult

pytestmark = pytest.mark.unit
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOioAAAAASUVORK5CYII="
)
WAV = (
    b"RIFF"
    + struct.pack("<I", 38)
    + b"WAVEfmt "
    + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
    + b"data"
    + struct.pack("<I", 2)
    + b"\x00\x00"
)
# The receiver verifies the MIME signature; codec playback is a separate browser test.
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + bytes(64)


def padded_png(size: int) -> bytes:
    """A valid PNG ancillary chunk keeps this a real image at the target byte size."""
    data = b"fixture\x00" + bytes(size - len(PNG) - 12 - len(b"fixture\x00"))
    kind = b"tEXt"
    chunk = struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return PNG[:-12] + chunk + PNG[-12:]


class MemoryTransport(MediaTransport):
    """Replace persistence only; inherited protocol validation and callbacks remain real."""

    def __init__(self, *, declared: bool) -> None:
        self.current: dict[str, Any] = {
            "request_id": "request",
            "connection_id": "connection",
            "status": "claimed",
            "cancelled": False,
            "expires_at": time.time() + 60,
            "authorization_revision": 1,
            "device_id": "device",
            "user_id": "user",
            "tenant_id": "tenant",
            "project_id": "project",
            "conversation_id": "conversation",
            "run_id": "run",
            "session_id": "session",
            "tool_name": "arbitrary_registered_tool",
            "input_json": "{}",
            **({"display_kind": "repl_output"} if declared else {}),
        }
        self.parts: dict[str, str] = {}
        self.redis = self
        self.before_update: Callable[[], None] | None = None

    async def read(self, key: str) -> dict[str, Any] | None:
        assert key == request_key("request")
        return copy.deepcopy(self.current)

    async def update(
        self, key: str, change: Callable[..., dict[str, Any]], **kwargs: object
    ) -> dict[str, Any]:
        assert key == request_key("request")
        if self.before_update is not None:
            self.before_update()
            self.before_update = None
        candidate = change(copy.deepcopy(self.current))
        if kwargs.get("extra") is not None:
            kwargs["extra"](self, candidate)
        self.current = candidate
        return copy.deepcopy(candidate)

    def set(self, key: str, value: str, **_kwargs: object) -> None:
        self.parts[key] = value

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.parts.get(key) for key in keys]


def message(mime: str, content: bytes, **extra: object) -> dict[str, Any]:
    descriptor = {"artifact_id": "native_asset", "mime_type": mime, "size_bytes": len(content)}
    return {
        "request_id": "request",
        "output_json": json.dumps(
            {
                "outputs": [{"type": "text", "text": "before"}],
                "artifacts": [
                    {"kind": "image" if mime.startswith("image/") else "audio", **descriptor}
                ],
                "output_order": [{"source": "text", "index": 0}, {"source": "media", "index": 0}],
            }
        ),
        "is_error": False,
        "media": [descriptor],
        **extra,
    }


async def transfer(transport: MemoryTransport, mime: str, content: bytes) -> ToolResult:
    original = message(mime, content)
    await transport.receive_result("connection", original)
    assert transport.current["status"] == "receiving"
    for offset in range(0, len(content), MAX_CHUNK_BYTES):
        part = content[offset : offset + MAX_CHUNK_BYTES]
        await transport.receive_chunk(
            "connection",
            {
                "request_id": "request",
                "artifact_id": "native_asset",
                "mime_type": mime,
                "offset": offset,
                "eof": offset + len(part) == len(content),
                "data_base64": base64.b64encode(part).decode(),
            },
        )
    assert transport.current["status"] == "completed"
    result = await transport.result(transport.current)
    assert result.output == original["output_json"]
    assert len(result.attachments) == 1
    assert result.attachments[0].name == "native_asset"
    assert result.attachments[0].mime_type == mime
    assert result.attachments[0].content == content
    return result


@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("case", ["large_png", "mpeg", "xwav"])
async def test_repl_formats_require_server_owned_declared_snapshot(
    declared: bool, case: str
) -> None:
    mime, content = {
        "large_png": ("image/png", padded_png(9 * 1024 * 1024)),
        "mpeg": ("audio/mpeg", MP3),
        "xwav": ("audio/x-wav", WAV),
    }[case]
    transport = MemoryTransport(declared=declared)
    if declared:
        await transfer(transport, mime, content)
    else:
        with pytest.raises(DeviceBridgeError):
            await transport.receive_result("connection", message(mime, content))
        assert transport.current["status"] == "claimed"
        assert transport.parts == {}


@pytest.mark.parametrize(("mime", "content"), [("image/png", PNG), ("audio/wav", WAV)])
async def test_non_repl_existing_media_round_trip_stays_supported(
    mime: str, content: bytes
) -> None:
    await transfer(MemoryTransport(declared=False), mime, content)


async def test_wire_or_output_display_cannot_opt_non_repl_into_repl_formats() -> None:
    transport = MemoryTransport(declared=False)
    forged = message("audio/mpeg", MP3, display_kind="repl_output")
    output = json.loads(forged["output_json"])
    output["display"] = {"kind": "repl_output", "entries": []}
    forged["output_json"] = json.dumps(output)
    with pytest.raises(DeviceBridgeError):
        await transport.receive_result("connection", forged)
    assert transport.current["status"] == "claimed"


async def test_wrong_connection_cannot_use_declared_repl_snapshot() -> None:
    transport = MemoryTransport(declared=True)
    with pytest.raises(DeviceBridgeError):
        await transport.receive_result("wrong-connection", message("audio/mpeg", MP3))
    assert transport.current["status"] == "claimed"


async def test_changed_declared_snapshot_is_rechecked_inside_atomic_update() -> None:
    transport = MemoryTransport(declared=True)
    transport.before_update = lambda: transport.current.pop("display_kind", None)
    with pytest.raises(DeviceBridgeError):
        await transport.receive_result("connection", message("audio/mpeg", MP3))
    assert transport.current["status"] == "claimed"


@pytest.mark.parametrize("mime", ["audio/mpeg", "audio/x-wav"])
async def test_declared_mime_does_not_accept_unrelated_content_bytes(mime: str) -> None:
    transport = MemoryTransport(declared=True)
    with pytest.raises(DeviceBridgeError):
        await transfer(transport, mime, b"<html>not-media</html>")


@pytest.mark.parametrize(
    ("size", "allowed"), [(10 * 1024 * 1024, True), (10 * 1024 * 1024 + 1, False)]
)
async def test_fresh_repl_individual_wire_limit_before_any_media_write(
    size: int, allowed: bool
) -> None:
    transport = MemoryTransport(declared=True)
    value = message("image/png", PNG)
    value["media"][0]["size_bytes"] = size
    if allowed:
        await transport.receive_result("connection", value)
        assert transport.current["status"] == "receiving"
    else:
        with pytest.raises(DeviceBridgeError):
            await transport.receive_result("connection", value)
        assert transport.current["status"] == "claimed"
    assert transport.parts == {}


@pytest.mark.parametrize("declared", [False, True])
@pytest.mark.parametrize("total", [32 * 1024 * 1024, 32 * 1024 * 1024 + 1])
async def test_repl_cell_wire_budget_is_separate_from_legacy_wav_budget(
    declared: bool, total: int
) -> None:
    transport = MemoryTransport(declared=declared)
    value = message("audio/wav", WAV)
    sizes = [8 * 1024 * 1024] * 3 + [total - 24 * 1024 * 1024]
    value["media"] = [
        {"artifact_id": f"audio_{index}", "mime_type": "audio/wav", "size_bytes": size}
        for index, size in enumerate(sizes)
    ]
    if declared and total > 32 * 1024 * 1024:
        with pytest.raises(DeviceBridgeError):
            await transport.receive_result("connection", value)
        assert transport.current["status"] == "claimed"
    else:
        await transport.receive_result("connection", value)
        assert transport.current["status"] == "receiving"
    assert transport.parts == {}


@pytest.mark.parametrize("declared", [False, True])
async def test_declared_repl_supports_twenty_one_small_images_without_relaxing_legacy_count(
    declared: bool,
) -> None:
    transport = MemoryTransport(declared=declared)
    value = message("image/png", PNG)
    value["media"] = [
        {"artifact_id": f"image_{index}", "mime_type": "image/png", "size_bytes": len(PNG)}
        for index in range(21)
    ]
    if declared:
        await transport.receive_result("connection", value)
        assert len(transport.current["media"]) == 21
    else:
        with pytest.raises(DeviceBridgeError):
            await transport.receive_result("connection", value)
        assert transport.current["status"] == "claimed"
    assert transport.parts == {}


@pytest.mark.parametrize("case", ["large_png", "mpeg", "xwav"])
async def test_received_media_uses_real_artifact_mime_and_owned_bytes_response(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx
    from fastapi import FastAPI

    from src.application.services.artifact_content_authority_service import (
        ArtifactContentAuthorityService,
    )
    from src.application.services.artifact_service import ArtifactService
    from src.domain.ports.repositories.artifact_content_authority_repository import (
        ArtifactContentAuthorityRecord,
    )
    from src.infrastructure.adapters.primary.web.routers.agent import computer_use_media as api
    from src.infrastructure.agent.native_computer_use import audio_authority
    from src.infrastructure.agent.native_computer_use.image_messages import persist_tool_attachments
    from src.infrastructure.agent.native_computer_use.repl_output import (
        repl_output_display,
        select_repl_attachments,
    )

    mime, content = {
        "large_png": ("image/png", padded_png(9 * 1024 * 1024)),
        "mpeg": ("audio/mpeg", MP3),
        "xwav": ("audio/x-wav", WAV),
    }[case]
    transport = MemoryTransport(declared=True)
    result = await transfer(transport, mime, content)
    # External membership/run authority is a seam; receipt identity/hash binding stays real.
    monkeypatch.setattr(
        audio_authority,
        "require_audio_authority",
        AsyncMock(side_effect=lambda *_: (transport, copy.deepcopy(transport.current))),
    )
    objects: dict[str, bytes] = {}

    async def upload_file(
        file_content: bytes, object_key: str, **_kwargs: object
    ) -> SimpleNamespace:
        objects[object_key] = file_content
        return SimpleNamespace(etag="fixture")

    async def get_file_metadata(key: str) -> SimpleNamespace:
        return SimpleNamespace(size_bytes=len(objects[key]))

    async def get_file_bounded(key: str, *, max_bytes: int) -> bytes:
        assert len(objects[key]) <= max_bytes
        return objects[key]

    storage = SimpleNamespace(
        upload_file=upload_file,
        generate_presigned_url=AsyncMock(return_value="https://fixture.invalid/media"),
        get_file_metadata=get_file_metadata,
        get_file_bounded=get_file_bounded,
    )
    service = ArtifactService(storage_service=storage)
    selected, omitted = select_repl_attachments(result.output, result.attachments)
    _, references = await persist_tool_attachments(
        service,
        selected,
        scope={"tenant_id": "tenant", "project_id": "project", "conversation_id": "conversation"},
        tool_name="arbitrary_registered_tool",
        tool_execution_id="call",
    )
    display = repl_output_display(
        {"x-agistack-display-kind": "repl_output"}, result.output, [*references, *omitted]
    )
    entry = display["entries"][1]
    artifact = await service.get_artifact(entry["artifactId"])
    stored_mime = "audio/wav" if mime == "audio/x-wav" else mime
    assert entry["artifactId"] != "native_asset"
    assert entry["mimeType"] == artifact.mime_type == stored_mime
    assert references[0]["native_mime_type"] == mime
    if mime.startswith("audio/"):
        assert transport.current["audio_artifacts"][artifact.id]["mime_type"] == stored_mime

    async def get_authority(scope: object) -> ArtifactContentAuthorityRecord | None:
        current = await service.get_artifact(scope.artifact_id)
        if current is None or (scope.tenant_id, scope.project_id, scope.conversation_id) != (
            current.tenant_id,
            current.project_id,
            current.conversation_id,
        ):
            return None
        return ArtifactContentAuthorityRecord(
            scope=scope,
            mime_type=current.mime_type,
            status=current.status.value,
            object_key=current.object_key,
            size_bytes=current.size_bytes,
            revision=1,
            content_hash=current.metadata["content_hash"],
        )

    content_service = ArtifactContentAuthorityService(
        repository=SimpleNamespace(get_authority=get_authority),
        storage_service=storage,
    )

    class Database:
        async def scalar(self, statement: object) -> str | None:
            params = set(statement.compile().params.values())
            needed = {"user", "tenant", "project"}
            if "conversations" in str(statement):
                needed.add("conversation")
            return "allowed" if needed <= params else None

    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1/agent")
    services = SimpleNamespace(artifacts=service, content=content_service, commit=AsyncMock())
    app.dependency_overrides[api.get_current_user] = lambda: SimpleNamespace(id="user")
    app.dependency_overrides[api.get_db] = lambda: Database()
    app.dependency_overrides[api.artifact_http_application_authority_dependency_v2] = (
        lambda: SimpleNamespace(services=services)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/agent/conversations/conversation/tool-media/{artifact.id}",
            params={"tenant_id": "tenant", "project_id": "project"},
        )
    assert response.status_code == 200, response.text
    assert response.content == content
    assert response.headers["content-type"] == entry["mimeType"]
    assert response.headers["content-length"] == str(entry["sizeBytes"])
    assert response.headers["cache-control"] == "private, no-store"
    services.commit.assert_awaited_once()
