"""Conversation-bound capabilities used by the original chat workbench."""

from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.models import HITLRequest
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

from .attachment_parts import FileInput, decode, metadata, multipart, storage
from .chat_operations import (
    ConversationInput,
    History,
    Identifier,
    Turn,
    _canonical,
    _own_conversation,
    _turn,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class Answer(ConversationInput):
    request_id: Identifier
    hitl_type: Literal["clarification", "decision", "permission", "a2ui_action"]
    expected_revision: int = Field(ge=1)
    idempotency_key: Identifier
    response_data: dict[str, Any]


async def respond(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    answer = Answer.model_validate(payload)
    await _own_conversation(ctx, answer.conversation_id)
    record = await ctx.db.scalar(
        select(HITLRequest).where(
            HITLRequest.id == answer.request_id,
            HITLRequest.conversation_id == answer.conversation_id,
            HITLRequest.tenant_id == ctx.scope.tenant_id,
            HITLRequest.project_id == ctx.scope.project_id,
        )
    )
    if (
        record is None
        or record.user_id not in (None, ctx.user.id)
        or (record.request_metadata or {}).get("native_binding")
    ):
        raise OptionalBusinessError("forbidden", "Request unavailable to this package")
    body = answer.model_dump(exclude={"conversation_id"})
    result = await _canonical(ctx, "POST", "hitl/respond", body={**body, "contract_version": 2})
    return {key: result[key] for key in ("success", "authority_revision") if key in result}


async def interactions(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = History.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    base = f"conversations/{data.conversation_id}"
    query = data.model_dump(exclude={"conversation_id"}, exclude_none=True)
    timeline = await _canonical(ctx, "GET", base + "/messages", query=query)
    pending = await _canonical(ctx, "GET", "hitl/" + base + "/pending")
    rows = []
    for row in timeline["timeline"]:
        kind = row.get("type")
        if kind in {"act", "observe"}:
            rows.append(
                {
                    key: row[key]
                    for key in (
                        "id",
                        "type",
                        "execution_id",
                        "toolName",
                        "toolInput",
                        "toolOutput",
                        "isError",
                    )
                    if key in row
                }
            )
        elif kind == "canvas_updated":
            block = row.get("block") or {}
            rows.append(
                {
                    "id": row["id"],
                    "type": kind,
                    "action": row["action"],
                    "block_id": row["block_id"],
                    "block": {
                        key: block[key]
                        for key in ("id", "title", "block_type", "content")
                        if key in block
                    },
                }
            )
    requests = []
    for item in pending["requests"]:
        if item.get("native_binding") or item["request_type"] not in {
            "permission",
            "decision",
            "clarification",
            "a2ui_action",
        }:
            continue
        meta = item.get("metadata") or {}
        fields = {
            key: meta[key]
            for key in (
                "allow_custom",
                "selection_mode",
                "max_selections",
                "decision_type",
                "clarification_type",
                "tool_name",
                "risk_level",
                "block_id",
                "description",
            )
            if key in meta
        }
        requests.append(
            {
                **fields,
                **{
                    key: item[key]
                    for key in (
                        "id",
                        "request_type",
                        "question",
                        "options",
                        "created_at",
                        "expires_at",
                        "authority_revision",
                    )
                    if key in item
                },
            }
        )
    return {"events": rows, "requests": requests}


class AttachmentUpload(FileInput):
    content: str = Field(max_length=61440)


async def upload(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    if "action" in payload:
        return await multipart(ctx, payload)
    data = AttachmentUpload.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    item = await storage(
        ctx,
        "simple",
        data={
            "conversation_id": data.conversation_id,
            "project_id": ctx.scope.project_id,
            "purpose": "llm_context",
        },
        files={"file": (data.filename, decode(data.content), data.mime_type)},
    )
    return metadata(item)


class AttachedTurn(Turn):
    attachment_ids: list[Identifier] = Field(min_length=1, max_length=10)


async def attached_turn(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    from src.infrastructure.adapters.secondary.persistence.attachment_model import AttachmentModel

    data = AttachedTurn.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    records = await ctx.db.scalars(
        select(AttachmentModel).where(
            AttachmentModel.id.in_(data.attachment_ids),
            AttachmentModel.conversation_id == data.conversation_id,
            AttachmentModel.tenant_id == ctx.scope.tenant_id,
            AttachmentModel.project_id == ctx.scope.project_id,
            AttachmentModel.status.in_(("uploaded", "processing", "ready")),
        )
    )
    files = {
        row.id: {
            "id": row.id,
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
        }
        for row in records
    }
    if set(files) != set(data.attachment_ids):
        raise OptionalBusinessError("forbidden", "Attachment unavailable for this conversation")
    return await _turn(
        ctx,
        Turn.model_validate(data.model_dump(exclude={"attachment_ids"})),
        progress,
        [files[id_] for id_ in dict.fromkeys(data.attachment_ids)],
    )


WORKBENCH_OPERATIONS = {
    "app.agent.interactions": interactions,
    "app.agent.respond": respond,
    "app.agent.attachments": upload,
    "app.agent.attachments.turn": attached_turn,
}
