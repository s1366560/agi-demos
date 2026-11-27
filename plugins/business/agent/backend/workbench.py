"""Transcript projection for the signed workbench. Rows are filtered in the guest."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from plugins.business.agent.backend.attachment_parts import AttachmentUpload, Identifier
from plugins.business.agent.backend.chat_operations import (
    ConversationInput,
    History,
    Turn,
    _canonical,
    _own_conversation,
    _turn,
)
from plugins.business.agent.guest.binding import (
    CommandContext,
    CommandError,
    Progress,
    bound,
    current,
)


class Answer(ConversationInput):
    request_id: Identifier = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    hitl_type: Literal["clarification", "decision", "permission", "a2ui_action"]
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    response_data: dict[str, Any]


async def _visible_request(
    _ctx: CommandContext, conversation_id: str, request_id: str
) -> dict[str, Any] | None:
    if not bound():
        return None
    return await current().hitl(conversation_id, request_id)


async def respond(ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    answer = Answer.model_validate(payload)
    await _own_conversation(ctx, answer.conversation_id)
    visible = await _visible_request(ctx, answer.conversation_id, answer.request_id)
    if visible is None:
        raise CommandError("forbidden", "Request unavailable to this package")
    body = answer.model_dump(exclude={"conversation_id"})
    result = await _canonical(ctx, "POST", "hitl/respond", body={**body, "contract_version": 2})
    return {key: result[key] for key in ("success", "authority_revision") if key in result}


class TimelineReview(History):
    view: Literal["workbench", "attachments"] = "workbench"


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
    "autoApproved",
    "auto_approved",
)
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
    kind = row.get("type")
    if kind == "canvas_updated":
        block = row.get("block") or {}
        return {
            **{key: row[key] for key in ROW_KEYS if key in row},
            "action": row["action"],
            "block_id": row["block_id"],
            "block": {
                key: block[key] for key in ("id", "title", "block_type", "content") if key in block
            },
        }
    keys: tuple[str, ...]
    if kind in {"act", "observe"}:
        keys = TOOL_KEYS
    elif kind in CARD_KEYS:
        keys = CARD_KEYS[kind]
    elif kind == "error":
        keys = ERROR_KEYS
    elif kind in MEMORY_KEYS:
        keys = MEMORY_KEYS[kind]
    else:
        keys = ()
    projected = {key: row[key] for key in (*ROW_KEYS, *keys) if key in row}
    if kind == "act":
        source = (row.get("metadata") or {}).get("sourceEventType")
        if isinstance(source, str):
            projected["metadata"] = {"sourceEventType": source}
    if isinstance(projected.get("memories"), list):
        projected["memories"] = [
            {key: memory[key] for key in RECALLED_KEYS if key in memory}
            for memory in projected["memories"]
            if isinstance(memory, dict)
        ]
    return projected


async def interactions(
    ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None
) -> dict[str, Any]:
    data = TimelineReview.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
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


async def upload(_ctx: CommandContext, payload: dict[str, Any], _progress: Progress | None) -> dict[str, Any]:
    if "action" not in payload:
        AttachmentUpload.model_validate(payload)
    return await current().attachment(payload)


class AttachedTurn(Turn):
    attachment_ids: list[str] = Field(min_length=1, max_length=10)


async def attached_turn(
    ctx: CommandContext, payload: dict[str, Any], progress: Progress | None
) -> dict[str, Any]:
    data = AttachedTurn.model_validate(payload)
    await _own_conversation(ctx, data.conversation_id)
    files = (
        await current().attachment_files(data.conversation_id, list(data.attachment_ids))
        if bound()
        else {}
    )
    if set(files) != set(data.attachment_ids):
        raise CommandError("forbidden", "Attachment unavailable for this conversation")
    return await _turn(
        ctx,
        Turn.model_validate(data.model_dump(exclude={"attachment_ids"})),
        progress,
        [files[id_] for id_ in dict.fromkeys(data.attachment_ids)],
    )


WORKBENCH_OPERATIONS: dict[str, Any] = {}
