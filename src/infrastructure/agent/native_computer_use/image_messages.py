"""Persist native media as scoped artifacts and hydrate images only for inference."""

from __future__ import annotations

import base64
import hashlib
import struct
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.domain.events.agent_events import AgentArtifactCreatedEvent
from src.domain.model.artifact.artifact import ArtifactStatus
from src.infrastructure.agent.native_computer_use.media_redaction import (
    _MODEL_MEDIA_REFERENCES,
    redact_model_media as redact_model_media,
)
from src.infrastructure.agent.tools.result import ToolAttachment
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService

IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
AUDIO_EXTENSIONS = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 64 * 1024 * 1024
IMAGE_MESSAGE_MARKER = "_native_tool_images"


def _image_dimensions(content: bytes, mime_type: str) -> tuple[int, int]:
    if mime_type not in IMAGE_EXTENSIONS or not 0 < len(content) <= MAX_IMAGE_BYTES:
        raise RuntimeV2Error("computer_use_image_invalid", "Native image size or format is invalid")
    try:
        if mime_type == "image/png" and content[:16] == b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
            width, height = struct.unpack(">II", content[16:24])
            if content[-12:] != b"\x00\x00\x00\x00IEND\xaeB`\x82":
                raise ValueError("PNG end missing")
        elif (
            mime_type == "image/jpeg" and content[:2] == b"\xff\xd8" and content[-2:] == b"\xff\xd9"
        ):
            width, height = _jpeg_dimensions(content)
        elif mime_type == "image/webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            width, height = _webp_dimensions(content)
        else:
            raise ValueError("image type mismatch")
        if not 0 < width <= 16384 or not 0 < height <= 16384 or width * height > 40_000_000:
            raise ValueError("image dimensions invalid")
        return width, height
    except Exception as error:
        raise RuntimeV2Error(
            "computer_use_image_invalid", "Native image could not be decoded"
        ) from error


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    while offset + 4 < len(content):
        if content[offset] != 0xFF:
            raise ValueError("invalid JPEG marker")
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        length = int.from_bytes(content[offset : offset + 2], "big")
        if length < 2 or offset + length > len(content):
            raise ValueError("invalid JPEG segment")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 8:
                raise ValueError("invalid JPEG frame")
            height, width = struct.unpack(">HH", content[offset + 3 : offset + 7])
            return width, height
        if marker == 0xDA:
            break
        offset += length
    raise ValueError("JPEG frame missing")


def _webp_dimensions(content: bytes) -> tuple[int, int]:
    chunk = content[12:16]
    if int.from_bytes(content[4:8], "little") + 8 != len(content):
        raise ValueError("WebP size mismatch")
    if chunk == b"VP8X" and len(content) >= 30:
        return int.from_bytes(content[24:27], "little") + 1, int.from_bytes(
            content[27:30], "little"
        ) + 1
    if chunk == b"VP8L" and len(content) >= 25 and content[20] == 0x2F:
        value = int.from_bytes(content[21:25], "little")
        return (value & 0x3FFF) + 1, ((value >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 " and len(content) >= 30 and content[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", content[26:30])
        return width & 0x3FFF, height & 0x3FFF
    raise ValueError("WebP frame missing")


async def persist_tool_attachments(
    service: ArtifactService | None,
    attachments: list[ToolAttachment],
    *,
    scope: dict[str, Any],
    tool_name: str,
    tool_execution_id: str | None,
) -> tuple[list[AgentArtifactCreatedEvent], list[dict[str, Any]]]:
    """Store accepted attachments; returned references contain no local path or bytes."""
    if not attachments:
        return [], []
    if service is None or not all(
        scope.get(k) for k in ("tenant_id", "project_id", "conversation_id")
    ):
        raise RuntimeV2Error(
            "computer_use_artifact_unavailable", "Native media requires scoped storage"
        )
    events: list[AgentArtifactCreatedEvent] = []
    references: list[dict[str, Any]] = []
    for attachment in attachments:
        content = attachment.content
        mime_type = attachment.mime_type
        if not isinstance(content, bytes):
            raise RuntimeV2Error("computer_use_media_invalid", "Native media must be binary")
        dimensions: tuple[int, int] | None = None
        if mime_type in IMAGE_EXTENSIONS:
            dimensions = _image_dimensions(content, mime_type)
            extension = IMAGE_EXTENSIONS[mime_type]
        elif mime_type in AUDIO_EXTENSIONS and 0 < len(content) <= MAX_AUDIO_BYTES:
            extension = AUDIO_EXTENSIONS[mime_type]
        else:
            raise RuntimeV2Error("computer_use_media_invalid", "Native media format is unavailable")
        metadata: dict[str, Any] = {
            "upload_source": "native_computer_use",
            "native_attachment_id": attachment.name,
        }
        if mime_type in AUDIO_EXTENSIONS:
            from src.infrastructure.agent.native_computer_use.audio_authority import (
                capture_audio_origin,
            )
            from src.infrastructure.agent.native_computer_use.audio_messages import (
                current_audio_scope,
            )

            metadata["native_audio_origin"] = await capture_audio_origin(
                attachment,
                {**scope, **current_audio_scope()},
            )
        artifact = await service.create_artifact(
            file_content=content,
            filename=f"computer-use-{uuid4().hex}{extension}",
            project_id=str(scope["project_id"]),
            tenant_id=str(scope["tenant_id"]),
            conversation_id=str(scope["conversation_id"]),
            source_tool=tool_name,
            tool_execution_id=tool_execution_id,
            metadata=metadata,
        )
        if artifact.status != ArtifactStatus.READY:
            raise RuntimeV2Error(
                "computer_use_artifact_unavailable", "Native media storage did not finish"
            )
        origin = metadata.get("native_audio_origin")
        if isinstance(origin, dict):
            from src.infrastructure.agent.native_computer_use.audio_authority import (
                bind_audio_artifact,
            )
            from src.infrastructure.agent.native_computer_use.audio_messages import (
                current_audio_scope,
            )

            await bind_audio_artifact(artifact, {**scope, **current_audio_scope()}, origin)
        events.append(
            AgentArtifactCreatedEvent(
                artifact_id=artifact.id,
                filename=artifact.filename,
                mime_type=artifact.mime_type,
                category=artifact.category.value,
                size_bytes=artifact.size_bytes,
                url=artifact.url,
                preview_url=artifact.preview_url,
                source_tool=tool_name,
                tool_execution_id=tool_execution_id,
            )
        )
        if dimensions is not None:
            references.append(
                {
                    "type": "artifact_image",
                    "artifact_id": artifact.id,
                    "native_attachment_id": attachment.name,
                    "native_mime_type": mime_type,
                    "mime_type": artifact.mime_type,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "width": dimensions[0],
                    "height": dimensions[1],
                }
            )
        else:
            references.append(
                {
                    "type": "artifact_audio",
                    "artifact_id": artifact.id,
                    "native_attachment_id": attachment.name,
                    "native_mime_type": mime_type,
                    "mime_type": artifact.mime_type,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return events, references


def tool_image_message(call_id: str, references: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "user",
        IMAGE_MESSAGE_MARKER: True,
        "content": [
            {"type": "text", "text": f"Media returned by tool call {call_id}:"},
            *references,
        ],
    }


async def hydrate_image_messages(
    messages: list[dict[str, Any]],
    service: ArtifactService | None,
    scope: dict[str, Any],
) -> list[dict[str, Any]]:
    """Verify artifact ownership and turn durable references into real provider images."""
    hydrated: list[dict[str, Any]] = []
    references: dict[str, dict[str, Any]] = {}
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            hydrated.append(dict(message))
            continue
        parts: list[Any] = []
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "artifact_image":
                parts.append(part)
                continue
            if service is None:
                raise RuntimeV2Error(
                    "computer_use_artifact_unavailable", "Image storage is unavailable"
                )
            artifact_id = part.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id:
                raise RuntimeV2Error("computer_use_image_invalid", "Image reference is invalid")
            artifact = await service.get_artifact(artifact_id)
            if (
                artifact is None
                or artifact.status != ArtifactStatus.READY
                or (artifact.tenant_id, artifact.project_id, artifact.conversation_id)
                != (scope.get("tenant_id"), scope.get("project_id"), scope.get("conversation_id"))
            ):
                raise RuntimeV2Error(
                    "computer_use_image_scope_denied", "Image belongs to another scope"
                )
            if artifact.mime_type != part.get("mime_type") or artifact.size_bytes != part.get(
                "size_bytes"
            ):
                raise RuntimeV2Error("computer_use_image_changed", "Image reference changed")
            content_bytes = await service.get_artifact_bytes(artifact_id)
            if content_bytes is None or hashlib.sha256(content_bytes).hexdigest() != part.get(
                "sha256"
            ):
                raise RuntimeV2Error("computer_use_image_changed", "Image content changed")
            dimensions = _image_dimensions(content_bytes, artifact.mime_type)
            if dimensions != (part.get("width"), part.get("height")):
                raise RuntimeV2Error("computer_use_image_changed", "Image dimensions changed")
            encoded = base64.b64encode(content_bytes).decode("ascii")
            references[hashlib.sha256(encoded.encode("ascii")).hexdigest()] = dict(part)
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{artifact.mime_type};base64,{encoded}",
                        "detail": "high",
                    },
                }
            )
        hydrated.append(
            {k: v for k, v in message.items() if k != IMAGE_MESSAGE_MARKER} | {"content": parts}
        )
    _MODEL_MEDIA_REFERENCES.set(references)
    return hydrated
