"""Attachment shapes validated in the guest. Bytes are posted by the host."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping  # noqa: TC003
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from plugins.business.agent.guest.binding import CommandContext, CommandError
from src.domain.model.agent.attachment import DEFAULT_PART_SIZE

CHUNK_SIZE = 45 * 1024
type Identifier = str


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConversationInput(_Input):
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class FileInput(ConversationInput):
    filename: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")
    mime_type: str = Field(min_length=1, max_length=100, pattern=r"^[\w.+-]+/[\w.+-]+$")


class AttachmentUpload(FileInput):
    content: str = Field(max_length=61440)


class Begin(FileInput):
    action: Literal["begin"]
    size_bytes: int = Field(gt=0)


class Transfer(ConversationInput):
    attachment_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")


class Chunk(Transfer):
    action: Literal["chunk"]
    part_number: int = Field(ge=1)
    offset: int = Field(ge=0, lt=DEFAULT_PART_SIZE)
    content: str = Field(min_length=1, max_length=61440)


class Finish(Transfer):
    action: Literal["finish", "abort"]


def decode(content: str) -> bytes:
    try:
        return base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise CommandError("apply_failed", "Invalid attachment encoding") from exc


def metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("id", "filename", "mime_type", "size_bytes", "status")}


async def storage(ctx: CommandContext, path: str, **kwargs: object) -> dict[str, Any]:
    poster = getattr(ctx, "attachment_post", None)
    if poster is None:
        raise CommandError("runtime_unavailable", "attachment storage is host-owned")
    reply = await cast("Any", poster)(path, kwargs)
    if not isinstance(reply, dict):
        raise CommandError("apply_failed", "Invalid attachment storage response")
    return reply


async def store_chunk(
    ctx: CommandContext,
    attachment: object,
    step: Chunk,
    redis: object,
    key: str,
) -> dict[str, Any]:
    record = cast("Any", attachment)
    cache = cast("Any", redis)
    size = min(DEFAULT_PART_SIZE, record.size_bytes - (step.part_number - 1) * DEFAULT_PART_SIZE)
    raw = decode(step.content)
    if size <= 0 or step.offset % CHUNK_SIZE or len(raw) != min(CHUNK_SIZE, size - step.offset):
        raise CommandError("apply_failed", "Unexpected attachment chunk")
    if await cache.hexists(key, f"etag:{step.part_number}"):
        return {"accepted": True}
    if step.part_number > 1 and not await cache.hexists(key, f"etag:{step.part_number - 1}"):
        raise CommandError("conflict", "A previous attachment part is incomplete")
    field = f"chunk:{step.offset}"
    previous = await cache.hget(key, field)
    if previous is not None and previous != step.content:
        raise CommandError("conflict", "Attachment chunk changed during retry")
    async with cache.pipeline() as pipe:
        pipe.hset(key, field, step.content)
        pipe.expire(key, 1800)
        await pipe.execute()
    if step.offset + len(raw) == size:
        offsets = [f"chunk:{offset}" for offset in range(0, size, CHUNK_SIZE)]
        chunks = await cache.hmget(key, offsets)
        contents = bytearray()
        for chunk in chunks:
            if chunk is None:
                raise CommandError("conflict", "An attachment chunk is missing")
            contents.extend(decode(chunk))
        reply = await storage(
            ctx,
            "part",
            data={"attachment_id": record.id, "part_number": step.part_number},
            files={"file": (record.filename, bytes(contents), record.mime_type)},
        )
        async with cache.pipeline() as pipe:
            pipe.hset(key, f"etag:{step.part_number}", reply["etag"])
            pipe.hdel(key, *offsets)
            pipe.expire(key, 1800)
            await pipe.execute()
    return {"accepted": True}
