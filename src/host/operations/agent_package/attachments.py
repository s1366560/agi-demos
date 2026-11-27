"""Attachment bytes stay on the host. The guest only names the operation."""

from __future__ import annotations

from typing import Any, cast

import httpx

from src.host.operations.agent_package.admission import admit
from src.host.operations.agent_package.bridge import HostBridge
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError


async def perform(bridge: HostBridge, payload: dict[str, Any]) -> dict[str, Any]:
    from plugins.business.agent.guest import attachments as guest

    await bridge.own(payload["conversation_id"])
    if payload.get("action"):
        return await _multipart(bridge, payload)
    item = await _store_simple(bridge, payload)
    return guest.metadata(item)


async def _store_simple(bridge: HostBridge, payload: dict[str, Any]) -> dict[str, Any]:
    from plugins.business.agent.guest.attachments import decode

    content = decode(payload["content"])
    return await _post(
        bridge,
        "simple",
        data={
            "conversation_id": payload["conversation_id"],
            "project_id": bridge.project_id,
            "purpose": "llm_context",
        },
        files={"file": (payload["filename"], content, payload["mime_type"])},
    )


async def _post(
    bridge: HostBridge,
    path: str,
    *,
    data: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with admit(bridge.user_id, bridge.tenant_id):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=bridge.ctx.request.app),
            base_url="http://localhost",
        ) as client:
            reply = await client.post(
                "/api/v1/attachments/upload/" + path,
                data=data,
                files=files,
                json=body,
                params={"project_id": bridge.project_id} if bridge.project_id else None,
            )
    if reply.status_code >= 400:
        raise OptionalBusinessError(
            "apply_failed", f"Attachment storage returned HTTP {reply.status_code}"
        )
    result = reply.json()
    if not isinstance(result, dict):
        raise OptionalBusinessError("apply_failed", "Invalid attachment storage response")
    return result


async def _multipart(bridge: HostBridge, payload: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from plugins.business.agent.guest.attachments import metadata
    from src.infrastructure.adapters.secondary.cache.redis_pool import get_redis_client
    from src.infrastructure.adapters.secondary.persistence.attachment_model import AttachmentModel

    if payload["action"] == "begin":
        reply = await _post(
            bridge,
            "initiate",
            body={
                "conversation_id": payload["conversation_id"],
                "filename": payload["filename"],
                "mime_type": payload["mime_type"],
                "size_bytes": payload["size_bytes"],
                "project_id": bridge.project_id,
                "purpose": "llm_context",
            },
        )
        return {key: reply[key] for key in ("attachment_id", "part_size", "total_parts")}
    attachment = await bridge.ctx.db.scalar(
        select(AttachmentModel).where(
            AttachmentModel.id == payload["attachment_id"],
            AttachmentModel.project_id == bridge.project_id,
            AttachmentModel.tenant_id == bridge.tenant_id,
            AttachmentModel.conversation_id == payload["conversation_id"],
        )
    )
    if not attachment or not attachment.total_parts:
        raise OptionalBusinessError("forbidden", "Attachment unavailable for this conversation")
    key = f"package-agent:attachment:{attachment.id}"
    redis = await get_redis_client()
    async with redis.lock(key + ":lock", timeout=90, blocking_timeout=15):
        if payload["action"] == "abort":
            await _post(bridge, "abort", data={"attachment_id": attachment.id})
            await redis.delete(key)
            return {"aborted": True}
        if attachment.status != "pending":
            if payload["action"] == "finish" and attachment.status in {
                "uploaded",
                "ready",
                "processing",
            }:
                return metadata(
                    {
                        "id": attachment.id,
                        "filename": attachment.filename,
                        "mime_type": attachment.mime_type,
                        "size_bytes": attachment.size_bytes,
                        "status": attachment.status,
                    }
                )
            raise OptionalBusinessError("conflict", "Upload is no longer pending")
        if payload["action"] == "chunk":
            from types import SimpleNamespace

            from plugins.business.agent.guest.attachments import Chunk, store_chunk

            async def poster(path: str, fields: dict[str, Any]) -> dict[str, Any]:
                return await _post(
                    bridge,
                    path,
                    data=fields.get("data"),
                    files=fields.get("files"),
                    body=fields.get("json"),
                )

            return await store_chunk(
                SimpleNamespace(attachment_post=poster),
                attachment,
                Chunk.model_validate(payload),
                redis,
                key,
            )
        parts = []
        for number in range(1, attachment.total_parts + 1):
            etag = await cast("Any", redis.hget(key, f"etag:{number}"))
            if not etag:
                raise OptionalBusinessError("conflict", "Incomplete attachment")
            parts.append({"part_number": number, "etag": etag})
        result = await _post(
            bridge, "complete", body={"attachment_id": attachment.id, "parts": parts}
        )
        await redis.delete(key)
        return metadata(result)
