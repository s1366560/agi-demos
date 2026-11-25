"""Relay bounded page messages to the canonical multipart attachment service."""

import base64
import binascii
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx
from pydantic import Field
from sqlalchemy import select

from src.domain.model.agent.attachment import DEFAULT_PART_SIZE
from src.infrastructure.adapters.secondary.cache.redis_pool import get_redis_client
from src.infrastructure.adapters.secondary.persistence.attachment_model import AttachmentModel
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .chat_operations import ConversationInput, Identifier, _own_conversation

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from httpx._types import RequestData, RequestFiles
    from redis.asyncio import Redis

    from src.host.operations.application_commands import PackageOperationContext

CHUNK_SIZE = 45 * 1024


class FileInput(ConversationInput):
    filename: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")
    mime_type: str = Field(min_length=1, max_length=100, pattern=r"^[\w.+-]+/[\w.+-]+$")


class Begin(FileInput):
    action: Literal["begin"]
    size_bytes: int = Field(gt=0)


class Transfer(ConversationInput):
    attachment_id: Identifier


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
        raise OptionalBusinessError("apply_failed", "Invalid attachment encoding") from exc


async def storage(
    ctx: "PackageOperationContext",
    path: str,
    *,
    data: "RequestData | None" = None,
    files: "RequestFiles | None" = None,
    json: dict[str, object] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctx.request.app),
        base_url="http://localhost",
        headers={"authorization": ctx.request.headers.get("authorization", "")},
    ) as client:
        result = await client.post(
            "/api/v1/attachments/upload/" + path, data=data, files=files, json=json
        )
    if result.status_code >= 400:
        raise OptionalBusinessError(
            "apply_failed", f"Attachment storage returned HTTP {result.status_code}"
        )
    reply = result.json()
    if not isinstance(reply, dict):
        raise OptionalBusinessError("apply_failed", "Invalid attachment storage response")
    return reply


def metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("id", "filename", "mime_type", "size_bytes", "status")}


async def multipart(ctx: "PackageOperationContext", payload: dict[str, Any]) -> dict[str, Any]:
    if payload["action"] == "begin":
        begin = Begin.model_validate(payload)
        await _own_conversation(ctx, begin.conversation_id)
        reply = await storage(
            ctx,
            "initiate",
            json={
                **begin.model_dump(exclude={"action"}),
                "project_id": ctx.scope.project_id,
                "purpose": "llm_context",
            },
        )
        return {key: reply[key] for key in ("attachment_id", "part_size", "total_parts")}
    step = (
        Chunk.model_validate(payload)
        if payload["action"] == "chunk"
        else Finish.model_validate(payload)
    )
    await _own_conversation(ctx, step.conversation_id)
    attachment = await ctx.db.scalar(
        select(AttachmentModel).where(
            AttachmentModel.id == step.attachment_id,
            AttachmentModel.project_id == ctx.scope.project_id,
            AttachmentModel.tenant_id == ctx.scope.tenant_id,
            AttachmentModel.conversation_id == step.conversation_id,
        )
    )
    if not attachment or not attachment.total_parts:
        raise OptionalBusinessError("forbidden", "Attachment unavailable for this conversation")
    key = f"package-agent:attachment:{attachment.id}"
    redis = await get_redis_client()
    async with redis.lock(key + ":lock", timeout=90, blocking_timeout=15):
        if step.action == "abort":
            await storage(ctx, "abort", data={"attachment_id": attachment.id})
            await redis.delete(key)
            return {"aborted": True}
        if attachment.status != "pending":
            if step.action == "finish" and attachment.status in {"uploaded", "ready", "processing"}:
                return metadata(
                    {
                        k: getattr(attachment, k)
                        for k in ("id", "filename", "mime_type", "size_bytes", "status")
                    }
                )
            raise OptionalBusinessError("conflict", "Upload is no longer pending")
        if isinstance(step, Chunk):
            return await store_chunk(ctx, attachment, step, redis, key)
        parts = []
        for number in range(1, attachment.total_parts + 1):
            etag = await cast("Awaitable[str | None]", redis.hget(key, f"etag:{number}"))
            if not etag:
                raise OptionalBusinessError("conflict", "Incomplete attachment")
            parts.append({"part_number": number, "etag": etag})
        result = await storage(
            ctx, "complete", json={"attachment_id": attachment.id, "parts": parts}
        )
        await redis.delete(key)
        return metadata(result)


async def store_chunk(
    ctx: "PackageOperationContext",
    attachment: AttachmentModel,
    step: Chunk,
    redis: "Redis",
    key: str,
) -> dict[str, Any]:
    size = min(
        DEFAULT_PART_SIZE, attachment.size_bytes - (step.part_number - 1) * DEFAULT_PART_SIZE
    )
    raw = decode(step.content)
    if size <= 0 or step.offset % CHUNK_SIZE or len(raw) != min(CHUNK_SIZE, size - step.offset):
        raise OptionalBusinessError("apply_failed", "Unexpected attachment chunk")
    if await cast("Awaitable[bool]", redis.hexists(key, f"etag:{step.part_number}")):
        return {"accepted": True}
    if step.part_number > 1 and not await cast(
        "Awaitable[bool]", redis.hexists(key, f"etag:{step.part_number - 1}")
    ):
        raise OptionalBusinessError("conflict", "A previous attachment part is incomplete")
    field = f"chunk:{step.offset}"
    previous = await cast("Awaitable[str | None]", redis.hget(key, field))
    if previous is not None and previous != step.content:
        raise OptionalBusinessError("conflict", "Attachment chunk changed during retry")
    async with redis.pipeline() as pipe:
        pipe.hset(key, field, step.content)
        pipe.expire(key, 1800)
        await pipe.execute()
    if step.offset + len(raw) == size:
        offsets = [f"chunk:{offset}" for offset in range(0, size, CHUNK_SIZE)]
        chunks = await cast("Awaitable[list[str | None]]", redis.hmget(key, offsets))
        contents = bytearray()
        for chunk in chunks:
            if chunk is None:
                raise OptionalBusinessError("conflict", "An attachment chunk is missing")
            contents.extend(decode(chunk))
        reply = await storage(
            ctx,
            "part",
            data={
                "attachment_id": attachment.id,
                "part_number": step.part_number,
            },
            files={
                "file": (
                    attachment.filename,
                    bytes(contents),
                    attachment.mime_type,
                )
            },
        )
        async with redis.pipeline() as pipe:
            pipe.hset(key, f"etag:{step.part_number}", reply["etag"])
            pipe.hdel(key, *offsets)
            pipe.expire(key, 1800)
            await pipe.execute()
    return {"accepted": True}
