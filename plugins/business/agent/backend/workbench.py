"""Conversation-bound capabilities used by the original chat workbench."""

import base64
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
    _canonical_http,
    _own_conversation,
    _turn,
    canonical_bytes,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext, Progress


class Answer(ConversationInput):
    request_id: Identifier
    hitl_type: Literal["clarification", "decision", "permission", "a2ui_action", "env_var"]
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


class TimelineReview(History):
    view: Literal["workbench", "attachments", "artifact"] = "workbench"
    # The file of the `artifact` view, as the timeline names it.
    artifact_id: Identifier | None = None


# A step is placed among the messages of its turn, so every row keeps its position.
ROW_KEYS = ("id", "type", "timestamp", "eventTimeUs", "eventCounter")
TOOL_KEYS = (
    "execution_id",
    "call_id",
    "message_id",
    "toolName",
    "toolInput",
    "toolOutput",
    "isError",
    "execution",
)
PERMISSION_KEYS = (
    "requestId",
    "toolName",
    "action",
    "resource",
    "reason",
    "description",
    "riskLevel",
    "answered",
    "granted",
    # A request allowed by policy is not shown as a decision in the transcript.
    "autoApproved",
    "auto_approved",
)
# What the transcript cards read from a human-in-the-loop request and from its
# answer. An answer names the variables it provided; their values are not part of
# a transcript.
CARD_KEYS = {
    "permission_asked": (*PERMISSION_KEYS, "expiresAt", "createdAt"),
    "permission_requested": (*PERMISSION_KEYS, "expiresAt", "createdAt"),
    "permission_replied": ("requestId", "granted", "autoApproved", "auto_approved"),
    "permission_granted": ("requestId", "granted", "autoApproved", "auto_approved"),
    "clarification_asked": (
        "requestId",
        "question",
        "clarificationType",
        "options",
        "allowCustom",
        "answered",
        "answer",
        "expiresAt",
        "createdAt",
    ),
    "clarification_answered": ("requestId", "answer"),
    "decision_asked": (
        "requestId",
        "question",
        "decisionType",
        "options",
        "allowCustom",
        "defaultOption",
        "selectionMode",
        "maxSelections",
        "answered",
        "decision",
        "expiresAt",
        "createdAt",
    ),
    "decision_answered": ("requestId", "decision"),
    "env_var_requested": (
        "requestId",
        "toolName",
        "fields",
        "message",
        "answered",
        "providedVariables",
        "expiresAt",
        "createdAt",
    ),
    "env_var_provided": ("requestId", "toolName", "variableNames"),
}
ERROR_KEYS = ("message", "code")
# What the card of a file the agent produced reads. Its address is signed by the
# storage and runs out; the card asks the `artifact` view for a new one.
ARTIFACT_KEYS = (
    "artifactId",
    "filename",
    "mimeType",
    "category",
    "sizeBytes",
    "url",
    "previewUrl",
    "sourceTool",
    "error",
)
# A picture is shown inside the page, which reaches no storage of its own. Larger
# files are opened by their address.
PREVIEW_IMAGE_BYTES = 1_048_576
# What the canvas reads from the metadata of a block: the language of a file, and
# the surface and the request of an A2UI block.
BLOCK_METADATA_KEYS = ("language", "mime_type", "surface_id", "hitl_request_id")
# What the memory steps of a transcript read. A recalled memory is shown with its
# text, score, source and category; the rest of the retrieval record stays.
RECALLED_KEYS = ("content", "score", "source", "category")
MEMORY_KEYS = {
    "memory_recalled": ("memories", "count", "searchMs"),
    "memory_captured": ("capturedCount", "categories"),
}


def timeline_attachments(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    files = {}
    for row in rows:
        if row.get("type") != "user_message":
            continue
        entries = (row.get("metadata") or {}).get("fileMetadata")
        if isinstance(entries, list):
            files[row["id"]] = [
                {key: file[key] for key in ("filename", "mime_type", "size_bytes")}
                for file in entries
                if isinstance(file, dict)
                and isinstance(file.get("filename"), str)
                and isinstance(file.get("mime_type"), str)
                and isinstance(file.get("size_bytes"), int)
            ]
    return files


def transcript_event(row: dict[str, Any]) -> dict[str, Any]:
    """What a transcript reads from a timeline row, placed where it happened."""
    kind = row.get("type")
    if kind == "canvas_updated":
        block: dict[str, Any] = row.get("block") or {}
        metadata = block.get("metadata")
        return {
            **{key: row[key] for key in ROW_KEYS if key in row},
            "action": row["action"],
            "block_id": row["block_id"],
            "block": {
                key: block[key] for key in ("id", "title", "block_type", "content") if key in block
            }
            | (
                {}
                if not isinstance(metadata, dict)
                else {
                    "metadata": {
                        key: metadata[key] for key in BLOCK_METADATA_KEYS if key in metadata
                    }
                }
            ),
        }
    keys: tuple[str, ...]
    if kind in {"act", "observe"}:
        keys = TOOL_KEYS
    elif kind in CARD_KEYS:
        keys = CARD_KEYS[kind]
    elif kind == "error":
        keys = ERROR_KEYS
    elif kind == "artifact_created":
        keys = ARTIFACT_KEYS
    elif kind in MEMORY_KEYS:
        keys = MEMORY_KEYS[kind]
    else:
        # Not drawn. It still ends the group of tool steps before it, as in the
        # original transcript, so it keeps its place and nothing else.
        keys = ()
    projected = {key: row[key] for key in (*ROW_KEYS, *keys) if key in row}
    if kind == "act":
        # The transcript tells an argument draft of a call from its execution by
        # this one field; the rest of the metadata stays on the server.
        source: object = (row.get("metadata") or {}).get("sourceEventType")
        if isinstance(source, str):
            projected["metadata"] = {"sourceEventType": source}
    if isinstance(projected.get("memories"), list):
        projected["memories"] = [
            {key: memory[key] for key in RECALLED_KEYS if key in memory}
            for memory in projected["memories"]
            if isinstance(memory, dict)
        ]
    return projected


async def artifact(
    ctx: "PackageOperationContext", conversation_id: str, artifact_id: str
) -> dict[str, Any]:
    """A file the agent produced in a conversation, as the page can show it.

    The application is asked in the caller's own name, and names the conversation
    the file belongs to. The address of the file is signed anew, and a small
    picture comes as the page can draw it.
    """
    base = f"/api/v1/artifacts/{artifact_id}"
    row = await _canonical_http(ctx, "GET", base)
    if (
        row.get("conversation_id") != conversation_id
        or row.get("project_id") != ctx.scope.project_id
    ):
        raise OptionalBusinessError("forbidden", "Artifact unavailable for this conversation")
    result: dict[str, Any] = {"id": artifact_id, "status": row.get("status")}
    if row.get("status") != "ready":
        return result
    result["url"] = (await _canonical_http(ctx, "POST", base + "/refresh-url"))["url"]
    mime = str(row.get("mime_type") or "")
    if mime.startswith("image/") and (row.get("size_bytes") or 0) <= PREVIEW_IMAGE_BYTES:
        content_type, content = await canonical_bytes(ctx, base + "/content/bytes")
        if content and content_type.startswith("image/"):
            result["preview"] = (
                f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
            )
    return result


async def interactions(
    ctx: "PackageOperationContext", payload: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    data = TimelineReview.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    if data.view == "artifact":
        if data.artifact_id is None:
            raise OptionalBusinessError("page_request_invalid", "No file was named")
        return {"artifact": await artifact(ctx, data.conversation_id, data.artifact_id)}
    base = f"conversations/{data.conversation_id}"
    query = data.model_dump(exclude={"conversation_id", "view"}, exclude_none=True)
    timeline = await _canonical(ctx, "GET", base + "/messages", query=query)
    if data.view == "attachments":
        return {"attachments": timeline_attachments(timeline["timeline"])}
    pending = await _canonical(ctx, "GET", "hitl/" + base + "/pending")
    rows = [transcript_event(row) for row in timeline["timeline"]]
    requests = []
    for item in pending["requests"]:
        if item.get("native_binding") or item["request_type"] not in {
            "permission",
            "decision",
            "clarification",
            "a2ui_action",
            "env_var",
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
