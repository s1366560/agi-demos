"""Bounded media transport, separate from tool text and control events."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from redis.asyncio.client import Pipeline

from src.infrastructure.agent.native_computer_use.control import ControlTransport, validate_control
from src.infrastructure.agent.native_computer_use.store import (
    MEDIA_SECONDS,
    PREFIX,
    DeviceBridgeError,
    digest,
    identifier,
    request_key,
    string,
)
from src.infrastructure.agent.tools.result import ToolAttachment, ToolControlOutcome, ToolResult

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_MEDIA_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 128 * 1024
MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "audio/wav"})


def integer(value: object, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise DeviceBridgeError("computer_use_invalid_media")
    return value


def owned_request(value: dict[str, Any] | None, connection_id: str) -> dict[str, Any]:
    if value is None or value.get("connection_id") != connection_id:
        raise DeviceBridgeError("computer_use_request_access_denied")
    return value


class MediaTransport(ControlTransport):
    async def receive_result(self, connection_id: str, message: dict[str, Any]) -> None:
        request_id = identifier(message.get("request_id"))
        output = message.get("output_json")
        error = message.get("is_error")
        descriptors = message.get("media")
        if (
            not isinstance(output, str)
            or len(output.encode()) > 512 * 1024
            or not isinstance(error, bool)
            or not isinstance(descriptors, list)
            or len(descriptors) > 20
        ):
            raise DeviceBridgeError("computer_use_invalid_result")
        try:
            json.loads(output)
        except ValueError as exc:
            raise DeviceBridgeError("computer_use_invalid_result") from exc
        control, generation = validate_control(message)
        media: dict[str, dict[str, Any]] = {}
        total = 0
        for descriptor in descriptors:
            if not isinstance(descriptor, dict):
                raise DeviceBridgeError("computer_use_invalid_media")
            artifact_id = identifier(descriptor.get("artifact_id"))
            mime_type = descriptor.get("mime_type")
            if mime_type not in MIME_TYPES or artifact_id in media:
                raise DeviceBridgeError("computer_use_invalid_media")
            maximum = MAX_MEDIA_BYTES if mime_type == "audio/wav" else MAX_IMAGE_BYTES
            size = integer(descriptor.get("size_bytes"), maximum)
            if size == 0:
                raise DeviceBridgeError("computer_use_invalid_media")
            total += size
            media[artifact_id] = {
                "mime_type": mime_type,
                "size_bytes": size,
                "offset": 0,
                "eof": False,
                "parts": [],
            }
        if total > MAX_MEDIA_BYTES:
            raise DeviceBridgeError("computer_use_media_too_large")

        def change(value: dict[str, Any] | None) -> dict[str, Any]:
            value = owned_request(value, connection_id)
            if value["status"] != "claimed" or value.get("cancelled"):
                raise DeviceBridgeError("computer_use_result_already_settled")
            return {
                **value,
                "status": "receiving" if media else "completed",
                "output_json": output,
                "is_error": error,
                "media": media,
                "control_outcome": control.value if control else None,
                "control_generation": generation,
            }

        await self.update(request_key(request_id), change)

    async def receive_chunk(self, connection_id: str, message: dict[str, Any]) -> None:
        request_id = identifier(message.get("request_id"))
        artifact_id = identifier(message.get("artifact_id"))
        offset = integer(message.get("offset"), MAX_MEDIA_BYTES)
        payload = message.get("data_base64")
        eof = message.get("eof")
        if (
            not isinstance(payload, str)
            or len(payload) > 4 * ((MAX_CHUNK_BYTES + 2) // 3)
            or not isinstance(eof, bool)
        ):
            raise DeviceBridgeError("computer_use_invalid_media_chunk")
        try:
            content = base64.b64decode(payload, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DeviceBridgeError("computer_use_invalid_media_chunk") from exc
        if not content or len(content) > MAX_CHUNK_BYTES:
            raise DeviceBridgeError("computer_use_invalid_media_chunk")
        part_key = f"{PREFIX}:media:{digest([request_id, artifact_id, offset])}"

        def change(value: dict[str, Any] | None) -> dict[str, Any]:
            value = owned_request(value, connection_id)
            if value["status"] != "receiving":
                raise DeviceBridgeError("computer_use_result_already_settled")
            file = value["media"].get(artifact_id)
            if (
                file is None
                or file["mime_type"] != message.get("mime_type")
                or file["eof"]
                or file["offset"] != offset
                or len(file["parts"]) >= 4096
                or offset + len(content) > file["size_bytes"]
                or eof != (offset + len(content) == file["size_bytes"])
            ):
                raise DeviceBridgeError("computer_use_media_offset_mismatch")
            file["offset"] += len(content)
            file["parts"].append(part_key)
            file["eof"] = eof
            if all(file["eof"] for file in value["media"].values()):
                value["status"] = "completed"
            return value

        def extra(pipe: Pipeline, _value: dict[str, Any]) -> None:
            # Hex supports the application's text-decoding Redis pool. It stays
            # in this private artifact record and never enters model/event text.
            pipe.set(part_key, content.hex(), ex=MEDIA_SECONDS)

        await self.update(request_key(request_id), change, extra=extra)

    async def result(self, value: dict[str, Any]) -> ToolResult:
        attachments = []
        for artifact_id, descriptor in value.get("media", {}).items():
            parts = await self.redis.mget(descriptor["parts"])
            if any(part is None for part in parts):
                raise DeviceBridgeError("computer_use_media_expired")
            content = b"".join(bytes.fromhex(string(part)) for part in parts)
            mime = descriptor["mime_type"]
            if len(content) != descriptor["size_bytes"] or not valid_media(content, mime):
                raise DeviceBridgeError("computer_use_invalid_media_bytes")
            attachments.append(ToolAttachment(name=artifact_id, content=content, mime_type=mime))
        control = (
            ToolControlOutcome(value["control_outcome"]) if value.get("control_outcome") else None
        )
        metadata = {"computer_use": True, "device_id": value["device_id"]}
        if control is not None:
            metadata.update(output=value["output_json"], control_outcome=control.value)
        return ToolResult(
            output=value["output_json"],
            is_error=value["is_error"],
            attachments=attachments,
            metadata=metadata,
            control_outcome=control,
            control_wait=(
                lambda: self.wait_control(value["request_id"], value["control_generation"])
            )
            if control == ToolControlOutcome.USER_PAUSED
            else None,
        )


def valid_media(content: bytes, mime: str) -> bool:
    if mime == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return mime == "audio/wav" and content[:4] == b"RIFF" and content[8:12] == b"WAVE"
