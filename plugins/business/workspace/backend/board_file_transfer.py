"""Transfer Workspace Core files through the bounded rich-page channel."""

import base64
import binascii
import json
from collections.abc import AsyncIterator
from hashlib import sha256
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.host.operations.remote_application_commands import application_result
from src.infrastructure.adapters.secondary.cache.redis_pool import get_redis_client
from src.infrastructure.i18n import gettext as _

from .workspace_directory_export import _body, _request_core, read_workspace_operation

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from redis.asyncio import Redis

    from src.host.operations.application_commands import PackageOperationContext, Progress

CHUNK = 40 * 1024
MAX_BYTES = 100 * 1024 * 1024


class UploadInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    size: int = Field(ge=0, le=MAX_BYTES)
    filename: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f\x7f]+$")
    mime: str = Field(min_length=1, max_length=128, pattern=r"^[\w.+-]+/[\w.+-]+$")
    parent_path: str = Field(min_length=1, max_length=1024)


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(ge=0, lt=MAX_BYTES)
    content: str = Field(min_length=1, max_length=54616)


async def _hash_field(redis: "Redis", key: str, field: str) -> str | None:
    # redis-py shares the hget signature between sync and async clients.
    return await cast("Awaitable[str | None]", redis.hget(key, field))


async def upload(
    ctx: "PackageOperationContext",
    workspace: str,
    operation: str,
    transfer: UUID,
    revision: int,
    fields: dict[str, Any],
) -> dict[str, Any]:
    identity = sha256(
        repr((ctx.scope.tenant_id, ctx.scope.project_id, ctx.user.id, workspace)).encode()
    ).hexdigest()
    key = f"workspace:board-upload:{identity}:{transfer}"
    redis = await get_redis_client()
    if operation == "begin":
        await read_workspace_operation(ctx, {"workspace_id": workspace}, None)
        info = UploadInfo.model_validate(fields)
        async with redis.pipeline() as pipe:
            pipe.hsetnx(key, "info", info.model_dump_json())
            pipe.expire(key, 900)
            await pipe.execute()
        if await _hash_field(redis, key, "info") != info.model_dump_json():
            raise HTTPException(409, _("File metadata changed during retry"))
        return {"accepted": True}
    stored = await _hash_field(redis, key, "info")
    if not stored:
        raise HTTPException(410, _("File upload expired"))
    info = UploadInfo.model_validate_json(stored)
    if operation == "chunk":
        return await _store_chunk(redis, key, info, Part.model_validate(fields))
    if operation == "abort":
        await redis.delete(key)
        return {"aborted": True}
    if operation not in {"finish", "finish-native"}:
        raise HTTPException(422, _("Unknown file operation"))
    async with redis.lock(key + ":finish", timeout=180, blocking_timeout=30):
        if cached := await _hash_field(redis, key, "result"):
            return application_result(json.loads(cached))
        result = await _finish(ctx, workspace, operation, transfer, revision, redis, key, info)
        async with redis.pipeline() as pipe:
            pipe.delete(key)
            pipe.hset(key, mapping={"result": json.dumps(result), "info": info.model_dump_json()})
            pipe.expire(key, 900)
            await pipe.execute()
        return result


async def _store_chunk(redis: "Redis", key: str, info: UploadInfo, part: Part) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(part.content, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, _("Invalid file encoding")) from error
    expected = min(CHUNK, info.size - part.offset)
    if part.offset % CHUNK or expected != len(decoded):
        raise HTTPException(422, _("Invalid file chunk"))
    field = str(part.offset)
    async with redis.pipeline() as pipe:
        pipe.hsetnx(key, field, part.content)
        pipe.expire(key, 900)
        await pipe.execute()
    if await _hash_field(redis, key, field) != part.content:
        raise HTTPException(409, _("File chunk changed during retry"))
    return {"accepted": True}


async def _finish(
    ctx: "PackageOperationContext",
    workspace: str,
    operation: str,
    transfer: UUID,
    revision: int,
    redis: "Redis",
    key: str,
    info: UploadInfo,
) -> dict[str, Any]:
    if await cast("Awaitable[int]", redis.hlen(key)) != 1 + (info.size + CHUNK - 1) // CHUNK:
        raise HTTPException(409, _("File upload incomplete"))
    boundary = "workspace-" + uuid4().hex

    async def contents() -> AsyncIterator[bytes]:
        name = info.filename.replace('"', "%22")
        yield (
            f'--{boundary}\r\nContent-Disposition: form-data; name="parent_path"\r\n\r\n{info.parent_path}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: {info.mime}\r\n\r\n"
        ).encode()
        for offset in range(0, info.size, CHUNK):
            content = await _hash_field(redis, key, str(offset))
            if content is None:
                raise HTTPException(410, _("File upload expired"))
            yield base64.b64decode(content, validate=True)
        yield f"\r\n--{boundary}--\r\n".encode()

    path = (
        ("collaboration", "mutations", "files", "upload")
        if operation == "finish-native"
        else ("blackboard", "files", "upload")
    )
    response = await _request_core(
        ctx,
        workspace=workspace,
        child=path,
        method="POST",
        request_id=transfer,
        expected_revision=revision,
        upload=contents(),
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    try:
        if not 200 <= response.status_code < 300:
            raise HTTPException(response.status_code, _("Workspace file upload failed"))
        return {
            "data": json.loads(await _body(response)),
            "status": response.status_code,
            "headers": {},
        }
    finally:
        await response.aclose()


async def download(
    ctx: "PackageOperationContext", workspace: str, file_id: str, progress: "Progress | None"
) -> dict[str, Any]:
    if progress is None:
        raise HTTPException(422, _("File download requires a stream"))
    response = await _request_core(
        ctx, workspace=workspace, child=("blackboard", "files", file_id, "download")
    )
    try:
        if not 200 <= response.status_code < 300:
            raise HTTPException(response.status_code, _("File download failed"))
        size = 0
        async for block in response.aiter_raw():
            size += len(block)
            if size > MAX_BYTES:
                raise HTTPException(413, _("File too large"))
            for offset in range(0, len(block), CHUNK):
                await progress(
                    {"content": base64.b64encode(block[offset : offset + CHUNK]).decode("ascii")}
                )
        return {
            "size": size,
            "mime": response.headers.get("content-type", "application/octet-stream"),
        }
    finally:
        await response.aclose()
