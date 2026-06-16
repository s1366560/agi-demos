"""Message and execution endpoints.

Endpoints for conversation messages, execution history, and status.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.configuration.factories import create_llm_client
from src.domain.events.types import (
    DELTA_EVENT_TYPES,
    INTERNAL_EVENT_TYPES,
    AgentEventType,
)
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
    Message as DBMessage,
    User,
)
from src.infrastructure.i18n import gettext as _

from .schemas import ExecutionStatsResponse
from .utils import get_container_with_db

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Displayable events — derived from the canonical AgentEventType registry.
#
# The history endpoint (GET /conversations/{cid}/messages) replays events from
# the WAL on reconnect.  For a long-running session the live frontend router
# (web/src/services/agent/messageRouter.ts) handles ~80+ event types, so a
# hand-maintained allow-list is brittle and silently drops new types.
#
# Strategy: derive ``_DISPLAYABLE_EVENTS`` from ``AgentEventType`` minus an
# explicit deny-list of types that are unsafe or pointless to replay
# (streaming fragments, internal control signals, lifecycle markers that the
# UI doesn't render historically).  Adding a new event type to
# ``AgentEventType`` automatically makes it replayable unless explicitly
# excluded here.
# ---------------------------------------------------------------------------

# Lifecycle / status markers that have no historical UI value.  ``status`` and
# ``start`` are emitted on every run; ``complete``/``cancelled`` are inferred
# from the message lifecycle on the client.  ``message`` is a generic carrier
# already covered by ``user_message`` / ``assistant_message``.
_LIFECYCLE_NON_DISPLAYABLE: set[AgentEventType] = {
    AgentEventType.STATUS,
    AgentEventType.START,
    AgentEventType.COMPLETE,
    AgentEventType.CANCELLED,
    AgentEventType.ERROR,
    AgentEventType.MESSAGE,
    AgentEventType.PROGRESS,
    AgentEventType.TITLE_GENERATED,
}

# Events derived from other persisted state — replaying them produces
# duplicates of artefacts already rendered from the timeline + DB.
_DERIVED_NON_DISPLAYABLE: set[AgentEventType] = {
    AgentEventType.TOOLS_UPDATED,
    AgentEventType.CONTEXT_STATUS,
    AgentEventType.CONTEXT_SUMMARY_GENERATED,
}

_NON_DISPLAYABLE_EVENT_TYPES: set[AgentEventType] = (
    DELTA_EVENT_TYPES | INTERNAL_EVENT_TYPES | _LIFECYCLE_NON_DISPLAYABLE | _DERIVED_NON_DISPLAYABLE
)

_DISPLAYABLE_EVENTS: set[str] = {
    et.value for et in AgentEventType if et not in _NON_DISPLAYABLE_EVENT_TYPES
}


def _assert_conversation_scope(
    conversation: Any,
    *,
    current_user: User,
    tenant_id: str,
    project_id: str,
) -> None:
    if getattr(conversation, "tenant_id", None) != tenant_id:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))
    if getattr(conversation, "user_id", None) != current_user.id:
        raise HTTPException(status_code=403, detail=_("Access denied"))
    if getattr(conversation, "project_id", None) != project_id:
        raise HTTPException(status_code=403, detail=_("Access denied"))


async def _verify_conversation_access(
    conversation_id: str,
    current_user: User,
    db: AsyncSession,
    *,
    tenant_id: str,
    project_id: str | None = None,
) -> None:
    query = (
        select(DBConversation.user_id, DBConversation.tenant_id, DBConversation.project_id)
        .where(DBConversation.id == conversation_id)
        .limit(1)
    )
    result = await db.execute(refresh_select_statement(query))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))
    owner_id, conversation_tenant_id, conversation_project_id = row
    if conversation_tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=_("Conversation not found"))
    if owner_id != current_user.id:
        raise HTTPException(status_code=403, detail=_("Access denied"))
    if project_id is not None and conversation_project_id != project_id:
        raise HTTPException(status_code=403, detail=_("Access denied"))


# Legacy alias event-type strings that the agent has historically emitted but
# are not first-class members of ``AgentEventType``.  Preserve replay parity.
_DISPLAYABLE_EVENTS.update(
    {
        # Contract-agent tool calls can persist only streaming act_delta rows
        # when the final tool call terminates the session before a full act row.
        "act_delta",
        "permission_requested",  # legacy alias for permission_asked
        "permission_granted",  # legacy alias for permission_replied
        # Sessionized / chained SubAgent events predate AgentEventType but the
        # live SSE adapter renders them as first-class timeline items.
        "subagent_run_started",
        "subagent_run_completed",
        "subagent_run_failed",
        "subagent_session_spawned",
        "subagent_session_message_sent",
        "subagent_announce_giveup",
        "chain_started",
        "chain_step_started",
        "chain_step_completed",
        "chain_completed",
    }
)

_SKIP_EVENT_SENTINEL = object()
_TERMINAL_WORKSPACE_CONTRACT_TOOLS = {
    "workspace_submit_verification_judgment",
    "workspace_submit_supervisor_decision",
}


# ---------------------------------------------------------------------------
# Helpers for get_conversation_messages
# ---------------------------------------------------------------------------


def _extract_tool_execution_id(data: dict[str, Any]) -> str | None:
    """Return the stable per-call execution identity from an event payload."""
    for key in ("tool_execution_id", "execution_id", "call_id"):
        value = data.get(key)
        if value:
            return str(value)
    return None


def _build_tool_exec_map(tool_executions: list[Any]) -> dict[str, Any]:
    """Build a lookup map from tool executions keyed by call id, with tool-name fallback."""
    tool_exec_map: dict[str, dict[str, Any]] = {}
    for te in tool_executions:
        message_id = getattr(te, "message_id", None)
        call_id = getattr(te, "call_id", None)
        record_id = getattr(te, "id", None)
        tool_name = getattr(te, "tool_name", None)
        execution = {
            "_execution_id": str(record_id) if record_id else None,
            "startTime": te.started_at.timestamp() * 1000 if te.started_at else None,
            "endTime": te.completed_at.timestamp() * 1000 if te.completed_at else None,
            "duration": te.duration_ms,
        }

        for execution_id in (call_id, record_id):
            if execution_id:
                tool_exec_map[f"{message_id}:{execution_id}"] = execution
        if tool_name:
            tool_exec_map.setdefault(f"{message_id}:{tool_name}", execution)
    return tool_exec_map


def _build_hitl_answered_map(events: list[Any]) -> dict[str, Any]:
    """Build HITL answered map from answered events by request_id."""
    hitl_answered_map: dict[str, dict[str, Any]] = {}
    _answer_extractors: dict[str, str] = {
        "clarification_answered": "answer",
        "decision_answered": "decision",
    }
    for event in events:
        event_type = event.event_type
        data = event.event_data or {}
        request_id = data.get("request_id", "")
        if not request_id:
            continue
        if event_type in _answer_extractors:
            field = _answer_extractors[event_type]
            hitl_answered_map[request_id] = {field: data.get(field, "")}
        elif event_type == "env_var_provided":
            hitl_answered_map[request_id] = {"values": data.get("values", {})}
        elif event_type in ("permission_granted", "permission_replied"):
            hitl_answered_map[request_id] = {"granted": data.get("granted", False)}
    return hitl_answered_map


def _build_hitl_status_map(hitl_requests: list[Any]) -> dict[str, Any]:
    """Build HITL status map from database requests."""
    hitl_status_map: dict[str, dict[str, Any]] = {}
    for req in hitl_requests:
        hitl_status_map[req.id] = {
            "status": req.status.value if hasattr(req.status, "value") else req.status,
            "response": req.response,
            "response_metadata": req.response_metadata or {},
        }
    return hitl_status_map


def _build_artifact_maps(events: list[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build artifact ready/error maps for merging into artifact_created events."""
    artifact_ready_map: dict[str, dict[str, Any]] = {}
    artifact_error_map: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = event.event_type
        data = event.event_data or {}
        if event_type == "artifact_ready":
            aid = data.get("artifact_id", "")
            if aid:
                artifact_ready_map[aid] = {
                    "url": data.get("url", ""),
                    "preview_url": data.get("preview_url", ""),
                }
        elif event_type == "artifact_error":
            aid = data.get("artifact_id", "")
            if aid:
                artifact_error_map[aid] = {
                    "error": data.get("error", "Upload failed"),
                }
    return artifact_ready_map, artifact_error_map


def _timeline_event_id(event: Any) -> str:
    """Build the stable timeline item id for an execution event."""
    return f"{event.event_type}-{event.event_time_us}-{event.event_counter}"


def _build_completion_map(
    message_events_by_id: dict[str, list[Any]],
) -> dict[str, dict[str, Any]]:
    """Build assistant timeline-id -> complete event payload lookup."""
    completion_map: dict[str, dict[str, Any]] = {}
    for message_id, message_events in message_events_by_id.items():
        if not message_id:
            continue

        last_assistant_event = next(
            (
                event
                for event in reversed(message_events)
                if event.event_type == "assistant_message"
            ),
            None,
        )
        if last_assistant_event is None:
            continue

        completion_event = next(
            (event for event in reversed(message_events) if event.event_type == "complete"),
            None,
        )
        if completion_event is None:
            continue

        data = completion_event.event_data or {}
        if isinstance(data, dict):
            completion_map[_timeline_event_id(last_assistant_event)] = data
    return completion_map


def _resolve_hitl_answered(
    request_id: str,
    field_name: str,
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
) -> tuple[bool, Any]:
    """Check if an HITL request has been answered and extract the response value."""
    if request_id in hitl_answered_map:
        return True, hitl_answered_map[request_id].get(field_name)
    if request_id in hitl_status_map:
        status_info = hitl_status_map[request_id]
        if status_info["status"] in ("answered", "completed"):
            value = status_info.get("response") or status_info.get("response_metadata", {}).get(
                field_name
            )
            return True, value
    return False, None


# ---------------------------------------------------------------------------
# Per-event-type timeline item builders
# ---------------------------------------------------------------------------


def _build_user_message(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "message_id": data.get("message_id"),
        "content": data.get("content", ""),
        "role": "user",
    }
    metadata: dict[str, Any] = {}
    if data.get("file_metadata"):
        metadata["fileMetadata"] = data["file_metadata"]
    if data.get("forced_skill_name"):
        metadata["forcedSkillName"] = data["forced_skill_name"]
    if metadata:
        item["metadata"] = metadata
    return item


def _build_assistant_message(
    data: dict[str, Any],
    event: Any,
    completion_map: dict[str, dict[str, Any]],
    **_kwargs: Any,
) -> dict[str, Any]:
    completion_data = completion_map.get(_timeline_event_id(event), {})
    artifacts = data.get("artifacts") or completion_data.get("artifacts")
    trace_url = data.get("trace_url") or completion_data.get("trace_url")
    execution_summary = data.get("execution_summary") or completion_data.get("execution_summary")

    item: dict[str, Any] = {
        "message_id": data.get("message_id"),
        "content": data.get("content", ""),
        "role": "assistant",
    }
    if artifacts:
        item["artifacts"] = artifacts
    metadata: dict[str, Any] = {}
    if trace_url:
        metadata["traceUrl"] = trace_url
    if execution_summary:
        metadata["executionSummary"] = execution_summary
    if metadata:
        item["metadata"] = metadata
    return item


def _build_thought(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any] | object:
    thought_content = data.get("thought", "")
    if not thought_content or not thought_content.strip():
        return _SKIP_EVENT_SENTINEL
    return {"content": thought_content}


def _build_act(
    data: dict[str, Any], event: Any, tool_exec_map: dict[str, Any], **_kwargs: Any
) -> dict[str, Any]:
    execution_id = _extract_tool_execution_id(data)
    item: dict[str, Any] = {
        "toolName": data.get("tool_name", ""),
        "toolInput": data.get("tool_input", {}),
    }
    execution_keys = []
    if execution_id:
        execution_keys.append(f"{event.message_id}:{execution_id}")
    execution_keys.append(f"{event.message_id}:{data.get('tool_name', '')}")
    for key in execution_keys:
        if key in tool_exec_map:
            execution = dict(tool_exec_map[key])
            execution_id = execution.pop("_execution_id", None) or execution_id
            item["execution"] = execution
            break
    if execution_id:
        item["execution_id"] = execution_id
    return item


def _parse_accumulated_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not isinstance(raw_arguments, str) or not raw_arguments.strip():
        return {}
    parsed = _load_json_object_prefix(raw_arguments)
    if parsed is _SKIP_EVENT_SENTINEL:
        return {"partial_arguments": raw_arguments}
    return parsed if isinstance(parsed, dict) else {"arguments": parsed}


def _load_json_object_prefix(raw_arguments: str) -> Any:
    try:
        return json.loads(raw_arguments)
    except json.JSONDecodeError:
        pass

    repaired = _close_json_prefix(raw_arguments)
    if repaired == raw_arguments:
        repaired = _trim_to_complete_json_object_prefix(raw_arguments)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        trimmed = _trim_to_complete_json_object_prefix(raw_arguments)
        if trimmed != raw_arguments and trimmed != repaired:
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                pass
        return _SKIP_EVENT_SENTINEL


def _close_json_prefix(raw_arguments: str) -> str:
    stack: list[str] = []
    in_string = False
    escaped = False

    for char in raw_arguments:
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in ("}", "]"):
            if not stack or stack[-1] != char:
                return raw_arguments
            stack.pop()

    if in_string or not stack:
        return raw_arguments
    return f"{raw_arguments}{''.join(reversed(stack))}"


def _trim_to_complete_json_object_prefix(raw_arguments: str) -> str:
    stack: list[str] = []
    in_string = False
    escaped = False
    last_top_level_comma_index: int | None = None

    for index, char in enumerate(raw_arguments):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in ("}", "]"):
            if not stack or stack[-1] != char:
                return raw_arguments
            stack.pop()
        elif char == "," and stack == ["}"]:
            last_top_level_comma_index = index

    if last_top_level_comma_index is None:
        return raw_arguments
    return _close_json_prefix(raw_arguments[:last_top_level_comma_index])


def _build_act_delta(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    tool_name = data.get("tool_name", "")
    tool_input = _parse_accumulated_tool_arguments(data.get("accumulated_arguments"))
    return {
        "__timeline_type": "act",
        "toolName": tool_name,
        "toolInput": tool_input,
        "execution_id": _extract_tool_execution_id(data),
        "metadata": {
            "sourceEventType": "act_delta",
            "status": data.get("status", "preparing"),
            "synthesizeObserve": _should_synthesize_terminal_observe(tool_name, tool_input),
        },
    }


def _should_synthesize_terminal_observe(tool_name: Any, tool_input: dict[str, Any]) -> bool:
    if tool_name not in _TERMINAL_WORKSPACE_CONTRACT_TOOLS:
        return False
    return bool(tool_input.get("verdict") or tool_input.get("action"))


def _build_observe(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "toolName": data.get("tool_name", ""),
        "toolOutput": data.get("observation", ""),
        "isError": data.get("is_error", False),
    }
    execution_id = _extract_tool_execution_id(data)
    if execution_id:
        item["execution_id"] = execution_id
    raw_ui_meta = data.get("ui_metadata")
    if raw_ui_meta and isinstance(raw_ui_meta, dict):
        item["mcpUiMetadata"] = {
            "resource_uri": raw_ui_meta.get("resource_uri"),
            "server_name": raw_ui_meta.get("server_name"),
            "app_id": raw_ui_meta.get("app_id"),
            "title": raw_ui_meta.get("title"),
            "project_id": raw_ui_meta.get("project_id"),
        }
    return item


def _build_work_plan(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {"steps": data.get("steps", []), "status": data.get("status", "planning")}


def _build_task_start(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "taskId": data.get("task_id", ""),
        "content": data.get("content", ""),
        "orderIndex": data.get("order_index", 0),
        "totalTasks": data.get("total_tasks", 0),
    }


def _build_task_complete(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "taskId": data.get("task_id", ""),
        "status": data.get("status", "completed"),
        "orderIndex": data.get("order_index", 0),
        "totalTasks": data.get("total_tasks", 0),
    }


def _build_artifact_created(
    data: dict[str, Any],
    artifact_ready_map: dict[str, Any],
    artifact_error_map: dict[str, Any],
    **_kwargs: Any,
) -> dict[str, Any]:
    artifact_id = data.get("artifact_id", "")
    item: dict[str, Any] = {
        "artifactId": artifact_id,
        "filename": data.get("filename", ""),
        "mimeType": data.get("mime_type", ""),
        "category": data.get("category", "other"),
        "sizeBytes": data.get("size_bytes", 0),
        "url": data.get("url", ""),
        "previewUrl": data.get("preview_url", ""),
        "sourceTool": data.get("source_tool", ""),
        "metadata": data.get("metadata", {}),
    }
    if artifact_id in artifact_ready_map:
        ready = artifact_ready_map[artifact_id]
        item["url"] = ready.get("url") or item["url"]
        item["previewUrl"] = ready.get("preview_url") or item["previewUrl"]
    if artifact_id in artifact_error_map:
        item["error"] = artifact_error_map[artifact_id].get("error", "")
    return item


def _build_artifact_skip(**_kwargs: Any) -> object:
    """Skip artifact_ready/error events - merged into artifact_created above."""
    return _SKIP_EVENT_SENTINEL


def _build_clarification_asked(
    data: dict[str, Any],
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
    **_kwargs: Any,
) -> dict[str, Any]:
    request_id = data.get("request_id", "")
    answered, answer = _resolve_hitl_answered(
        request_id, "answer", hitl_answered_map, hitl_status_map
    )
    return {
        "requestId": request_id,
        "question": data.get("question", ""),
        "options": data.get("options", []),
        "allowCustom": data.get("allow_custom", True),
        "answered": answered,
        "answer": answer,
    }


def _build_clarification_answered(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {"requestId": data.get("request_id", ""), "answer": data.get("answer", "")}


def _build_decision_asked(
    data: dict[str, Any],
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
    **_kwargs: Any,
) -> dict[str, Any]:
    request_id = data.get("request_id", "")
    answered, decision = _resolve_hitl_answered(
        request_id, "decision", hitl_answered_map, hitl_status_map
    )
    return {
        "requestId": request_id,
        "question": data.get("question", ""),
        "options": data.get("options", []),
        "decisionType": data.get("decision_type", "branch"),
        "allowCustom": data.get("allow_custom", False),
        "defaultOption": data.get("default_option"),
        "answered": answered,
        "decision": decision,
    }


def _build_decision_answered(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {"requestId": data.get("request_id", ""), "decision": data.get("decision", "")}


def _build_env_var_requested(
    data: dict[str, Any],
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
    **_kwargs: Any,
) -> dict[str, Any]:
    request_id = data.get("request_id", "")
    answered = False
    values: dict[str, Any] = {}
    if request_id in hitl_answered_map:
        answered = True
        values = hitl_answered_map[request_id].get("values", {})
    elif request_id in hitl_status_map:
        status_info = hitl_status_map[request_id]
        if status_info["status"] in ("answered", "completed"):
            answered = True
            values = status_info.get("response_metadata", {}).get("values", {})
    return {
        "requestId": request_id,
        "toolName": data.get("tool_name", ""),
        "fields": data.get("fields", []),
        "message": data.get("message", ""),
        "context": data.get("context", {}),
        "answered": answered,
        "values": values,
    }


def _build_env_var_provided(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    variable_names = data.get("saved_variables", [])
    if not variable_names:
        variable_names = list(data.get("values", {}).keys())
    return {
        "requestId": data.get("request_id", ""),
        "toolName": data.get("tool_name", ""),
        "variableNames": variable_names,
    }


def _build_a2ui_action_asked(
    data: dict[str, Any], hitl_status_map: dict[str, Any], **_kwargs: Any
) -> dict[str, Any]:
    request_id = data.get("request_id", "")
    status_info = hitl_status_map.get(request_id, {})
    status = status_info.get("status")
    return {
        "request_id": request_id,
        "block_id": data.get("block_id", ""),
        "title": data.get("title"),
        "timeout_seconds": data.get("timeout_seconds"),
        "status": status,
        "answered": status in ("answered", "completed"),
    }


def _build_permission_asked(
    data: dict[str, Any],
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
    **_kwargs: Any,
) -> dict[str, Any]:
    request_id = data.get("request_id", "")
    answered = False
    granted = None
    if request_id in hitl_answered_map:
        answered = True
        granted = hitl_answered_map[request_id].get("granted")
    elif request_id in hitl_status_map:
        status_info = hitl_status_map[request_id]
        if status_info["status"] in ("answered", "completed"):
            answered = True
            granted = status_info.get("response_metadata", {}).get("granted")
    return {
        "requestId": request_id,
        "action": data.get("action", ""),
        "resource": data.get("resource", ""),
        "reason": data.get("reason", ""),
        "toolName": data.get("tool_name", ""),
        "toolDisplayName": data.get("tool_display_name", ""),
        "riskLevel": data.get("risk_level", "medium"),
        "description": data.get("description", ""),
        "allowRemember": data.get("allow_remember", True),
        "answered": answered,
        "granted": granted,
    }


def _build_permission_replied(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {"requestId": data.get("request_id", ""), "granted": data.get("granted", False)}


def _build_canvas_updated(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    """Build a canvas_updated timeline item from persisted event data."""
    return {
        "action": data.get("action", ""),
        "block_id": data.get("block_id", ""),
        "block": data.get("block"),
    }


def _build_subagent_routed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id", ""),
        "subagentName": data.get("subagent_name", ""),
        "confidence": data.get("confidence", 0),
        "reason": data.get("reason") or data.get("match_reason", ""),
    }


def _build_subagent_started(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id", ""),
        "subagentName": data.get("subagent_name", ""),
        "task": data.get("task", ""),
    }


def _build_subagent_completed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id") or data.get("run_id") or data.get("agent_id") or "",
        "subagentName": data.get("subagent_name"),
        "summary": data.get("summary") or data.get("final_content", ""),
        "tokensUsed": data.get("tokens_used", 0),
        "executionTimeMs": data.get("execution_time_ms", 0),
        "success": data.get("success", True),
    }


def _build_subagent_failed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id") or data.get("run_id") or data.get("agent_id") or "",
        "subagentName": data.get("subagent_name"),
        "error": data.get("error", ""),
    }


def _build_subagent_run(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("run_id", ""),
        "subagentName": data.get("subagent_name", ""),
        "task": data.get("task", ""),
        "status": data.get("status", ""),
        "summary": data.get("summary"),
        "error": data.get("error"),
        "executionTimeMs": data.get("execution_time_ms"),
        "tokensUsed": data.get("tokens_used"),
    }


def _build_subagent_session_spawned(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "conversationId": data.get("conversation_id", ""),
        "subagentId": data.get("run_id", ""),
        "subagentName": data.get("subagent_name", ""),
    }


def _build_subagent_session_message_sent(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "conversationId": data.get("conversation_id", ""),
        "parentSubagentId": data.get("parent_run_id", ""),
        "subagentId": data.get("run_id", ""),
        "subagentName": data.get("subagent_name", ""),
    }


def _build_subagent_announce_retry(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "conversationId": data.get("conversation_id") or data.get("session_id", ""),
        "subagentId": data.get("run_id") or data.get("agent_id", ""),
        "subagentName": data.get("subagent_name", ""),
        "attempt": data.get("attempt", 0),
        "error": data.get("error", ""),
        "nextDelayMs": data.get("next_delay_ms") or data.get("delay_ms", 0),
    }


def _build_subagent_announce_giveup(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "conversationId": data.get("conversation_id") or data.get("session_id", ""),
        "subagentId": data.get("run_id") or data.get("agent_id", ""),
        "subagentName": data.get("subagent_name", ""),
        "attempts": data.get("attempts", 0),
        "error": data.get("error") or data.get("last_error", ""),
    }


def _build_subagent_queued(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id", ""),
        "subagentName": data.get("subagent_name"),
        "queuePosition": data.get("queue_position"),
        "reason": data.get("reason"),
    }


def _build_subagent_killed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id", ""),
        "subagentName": data.get("subagent_name"),
        "kill_reason": data.get("kill_reason"),
        "error": data.get("error"),
    }


def _build_subagent_steered(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id", ""),
        "subagentName": data.get("subagent_name"),
        "instruction": data.get("instruction"),
    }


def _build_subagent_depth_limited(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentName": data.get("subagent_name"),
        "current_depth": data.get("current_depth"),
        "max_depth": data.get("max_depth"),
        "parentSubagentName": data.get("parent_subagent_name"),
    }


def _build_subagent_session_update(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "subagentId": data.get("subagent_id", ""),
        "subagentName": data.get("subagent_name"),
        "progress": data.get("progress"),
        "statusMessage": data.get("status_message"),
        "tokensUsed": data.get("tokens_used"),
        "toolCallsCount": data.get("tool_calls_count"),
    }


def _build_parallel_started(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "taskCount": data.get("task_count", 0),
        "subtasks": data.get("subtasks", []),
    }


def _build_parallel_completed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "results": data.get("results", []),
        "totalTimeMs": data.get("total_time_ms", 0),
    }


def _build_chain_started(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "stepCount": data.get("step_count", 0),
        "chainName": data.get("chain_name", ""),
    }


def _build_chain_step_started(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "stepIndex": data.get("step_index", 0),
        "stepName": data.get("step_name", ""),
        "subagentName": data.get("subagent_name", ""),
    }


def _build_chain_step_completed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "stepIndex": data.get("step_index", 0),
        "summary": data.get("summary", ""),
        "success": data.get("success"),
    }


def _build_chain_completed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "totalSteps": data.get("total_steps", 0),
        "totalTimeMs": data.get("total_time_ms", 0),
        "success": data.get("success"),
    }


def _build_background_launched(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "executionId": data.get("execution_id", ""),
        "subagentName": data.get("subagent_name", ""),
        "task": data.get("task", ""),
    }


def _build_agent_spawned(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "agentId": data.get("agent_id", ""),
        "agentName": data.get("agent_name"),
        "parentAgentId": data.get("parent_agent_id"),
        "childSessionId": data.get("child_session_id"),
        "mode": data.get("mode", "autonomous"),
        "taskSummary": data.get("task_summary"),
    }


def _build_agent_completed(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "agentId": data.get("agent_id", ""),
        "agentName": data.get("agent_name"),
        "parentAgentId": data.get("parent_agent_id"),
        "sessionId": data.get("session_id"),
        "result": data.get("result"),
        "success": data.get("success", False),
        "artifacts": data.get("artifacts", []),
    }


def _build_agent_message_sent(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "fromAgentId": data.get("from_agent_id", ""),
        "toAgentId": data.get("to_agent_id", ""),
        "fromAgentName": data.get("from_agent_name", ""),
        "toAgentName": data.get("to_agent_name", ""),
        "messagePreview": data.get("message_preview", ""),
    }


def _build_agent_message_received(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "agentId": data.get("agent_id", ""),
        "agentName": data.get("agent_name", ""),
        "fromAgentId": data.get("from_agent_id", ""),
        "fromAgentName": data.get("from_agent_name", ""),
        "messagePreview": data.get("message_preview", ""),
    }


def _build_agent_stopped(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "agentId": data.get("agent_id", ""),
        "agentName": data.get("agent_name"),
        "reason": data.get("reason"),
        "stoppedBy": data.get("stopped_by"),
    }


# Dispatch dict: event_type -> builder function
_EVENT_BUILDERS: dict[str, Any] = {
    "user_message": _build_user_message,
    "assistant_message": _build_assistant_message,
    "thought": _build_thought,
    "act": _build_act,
    "act_delta": _build_act_delta,
    "observe": _build_observe,
    "work_plan": _build_work_plan,
    "task_start": _build_task_start,
    "task_complete": _build_task_complete,
    "artifact_created": _build_artifact_created,
    "artifact_ready": _build_artifact_skip,
    "artifact_error": _build_artifact_skip,
    "clarification_asked": _build_clarification_asked,
    "clarification_answered": _build_clarification_answered,
    "decision_asked": _build_decision_asked,
    "decision_answered": _build_decision_answered,
    "env_var_requested": _build_env_var_requested,
    "env_var_provided": _build_env_var_provided,
    "a2ui_action_asked": _build_a2ui_action_asked,
    "permission_requested": _build_permission_asked,
    "permission_asked": _build_permission_asked,
    "permission_granted": _build_permission_replied,
    "permission_replied": _build_permission_replied,
    "canvas_updated": _build_canvas_updated,
    "subagent_routed": _build_subagent_routed,
    "subagent_started": _build_subagent_started,
    "subagent_completed": _build_subagent_completed,
    "subagent_failed": _build_subagent_failed,
    "subagent_run_started": _build_subagent_run,
    "subagent_run_completed": _build_subagent_run,
    "subagent_run_failed": _build_subagent_run,
    "subagent_session_spawned": _build_subagent_session_spawned,
    "subagent_session_message_sent": _build_subagent_session_message_sent,
    "subagent_announce_retry": _build_subagent_announce_retry,
    "subagent_announce_giveup": _build_subagent_announce_giveup,
    "subagent_queued": _build_subagent_queued,
    "subagent_killed": _build_subagent_killed,
    "subagent_steered": _build_subagent_steered,
    "subagent_depth_limited": _build_subagent_depth_limited,
    "subagent_session_update": _build_subagent_session_update,
    "parallel_started": _build_parallel_started,
    "parallel_completed": _build_parallel_completed,
    "chain_started": _build_chain_started,
    "chain_step_started": _build_chain_step_started,
    "chain_step_completed": _build_chain_step_completed,
    "chain_completed": _build_chain_completed,
    "background_launched": _build_background_launched,
    "agent_spawned": _build_agent_spawned,
    "agent_completed": _build_agent_completed,
    "agent_message_sent": _build_agent_message_sent,
    "agent_message_received": _build_agent_message_received,
    "agent_stopped": _build_agent_stopped,
}


def _build_timeline(
    events: list[Any],
    tool_exec_map: dict[str, Any],
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
    artifact_ready_map: dict[str, Any],
    artifact_error_map: dict[str, Any],
    completion_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the timeline list from raw events using the dispatch dict."""
    timeline: list[dict[str, Any]] = []
    replayable_act_delta_ids = _find_replayable_act_delta_ids(events)
    for event in events:
        event_type = event.event_type
        if event_type == "act_delta" and _event_identity(event) not in replayable_act_delta_ids:
            continue
        data = event.event_data or {}
        builder = _EVENT_BUILDERS.get(event_type)
        if builder is None:
            continue

        fields = builder(
            data=data,
            event=event,
            tool_exec_map=tool_exec_map,
            hitl_answered_map=hitl_answered_map,
            hitl_status_map=hitl_status_map,
            artifact_ready_map=artifact_ready_map,
            artifact_error_map=artifact_error_map,
            completion_map=completion_map,
        )
        if fields is _SKIP_EVENT_SENTINEL:
            continue
        timeline_type = fields.pop("__timeline_type", event_type)

        item = {
            "id": _timeline_event_id(event),
            "type": timeline_type,
            "eventTimeUs": event.event_time_us,
            "eventCounter": event.event_counter,
            "timestamp": event.event_time_us // 1000
            if event.event_time_us
            else (int(event.created_at.timestamp() * 1000) if event.created_at else None),
        }
        item.update(fields)
        timeline.append(item)
        if event_type == "act_delta" and _should_append_synthetic_observe(item):
            timeline.append(_build_synthetic_observe_item(item))
    return timeline


def _should_append_synthetic_observe(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata")
    return isinstance(metadata, dict) and metadata.get("synthesizeObserve") is True


def _build_synthetic_observe_item(act_item: dict[str, Any]) -> dict[str, Any]:
    tool_input = act_item.get("toolInput")
    result = tool_input if isinstance(tool_input, dict) else {}
    metadata = dict(act_item.get("metadata") or {})
    metadata["sourceEventType"] = "synthetic_observe"
    return {
        "id": f"observe-{act_item['id']}",
        "type": "observe",
        "eventTimeUs": act_item["eventTimeUs"],
        "eventCounter": act_item["eventCounter"],
        "timestamp": act_item["timestamp"],
        "toolName": act_item.get("toolName", ""),
        "toolOutput": json.dumps(result, ensure_ascii=False),
        "isError": False,
        "execution_id": act_item.get("execution_id"),
        "metadata": metadata,
    }


def _event_identity(event: Any) -> tuple[int, int, str]:
    return (event.event_time_us, event.event_counter, event.event_type)


def _act_delta_replay_key(event: Any) -> tuple[str, str]:
    data = event.event_data or {}
    message_id = event.message_id or ""
    tool_name = data.get("tool_name", "")
    execution_id = _extract_tool_execution_id(data)
    return (message_id, str(execution_id or tool_name))


def _find_replayable_act_delta_ids(events: list[Any]) -> set[tuple[int, int, str]]:
    """Return the last act_delta per tool call, unless a full act already exists."""
    latest_delta_by_key: dict[tuple[str, str], Any] = {}
    full_act_keys: set[tuple[str, str]] = set()

    for event in events:
        if event.event_type == "act_delta":
            latest_delta_by_key[_act_delta_replay_key(event)] = event
            continue
        if event.event_type == "act":
            full_act_keys.add(_act_delta_replay_key(event))

    return {
        _event_identity(event)
        for event in latest_delta_by_key.values()
        if _act_delta_replay_key(event) not in full_act_keys
    }


async def _resolve_pagination_cursors(
    event_repo: Any,
    conversation_id: str,
    from_time_us: int | None,
    from_counter: int | None,
    before_time_us: int | None,
    before_counter: int | None,
) -> tuple[int, int, int | None, int | None]:
    """Resolve pagination cursor values, defaulting to latest if neither provided."""
    calc_from_time_us = from_time_us or 0
    calc_from_counter = from_counter or 0
    calc_before_time_us = before_time_us
    calc_before_counter = before_counter

    if calc_from_time_us == 0 and calc_before_time_us is None:
        last_time_us, _last_counter = await event_repo.get_last_event_time(conversation_id)
        if last_time_us > 0:
            calc_before_time_us = last_time_us + 1
            calc_before_counter = 0
            calc_from_time_us = 0

    return calc_from_time_us, calc_from_counter, calc_before_time_us, calc_before_counter


async def _check_has_more(
    event_repo: Any,
    conversation_id: str,
    first_time_us: int | None,
    first_counter: int | None,
) -> bool:
    """Check whether there are more events before the first timeline event."""
    if first_time_us is None:
        return False
    check_events = await event_repo.get_events(
        conversation_id=conversation_id,
        from_time_us=0,
        limit=1,
        event_types=_DISPLAYABLE_EVENTS,
        before_time_us=first_time_us,
        before_counter=first_counter,
    )
    return len(check_events) > 0


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=500, description="Maximum events to return"),
    from_time_us: int | None = Query(
        None, description="Starting event_time_us (inclusive) for forward pagination"
    ),
    from_counter: int | None = Query(
        None, description="Starting event_counter (inclusive) for forward pagination"
    ),
    before_time_us: int | None = Query(
        None, description="For backward pagination, get events before this event_time_us"
    ),
    before_counter: int | None = Query(
        None, description="For backward pagination, event_counter for the cursor"
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get conversation timeline from unified event stream with bidirectional pagination.

    Returns timeline of all events in the conversation, ordered by sequence number.
    """
    try:
        assert request is not None
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        conversation = await agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
        )

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        event_repo = container.agent_execution_event_repository()
        tool_exec_repo = container.tool_execution_record_repository()

        cursors = await _resolve_pagination_cursors(
            event_repo,
            conversation_id,
            from_time_us,
            from_counter,
            before_time_us,
            before_counter,
        )
        calc_from_time_us, calc_from_counter, calc_before_time_us, calc_before_counter = cursors

        events = await event_repo.get_events(
            conversation_id=conversation_id,
            from_time_us=calc_from_time_us,
            from_counter=calc_from_counter,
            limit=limit,
            event_types=_DISPLAYABLE_EVENTS,
            before_time_us=calc_before_time_us,
            before_counter=calc_before_counter,
        )

        tool_exec_map = _build_tool_exec_map(
            await tool_exec_repo.list_by_conversation(conversation_id)
        )
        hitl_answered_map = _build_hitl_answered_map(events)

        hitl_repo = container.hitl_request_repository()
        hitl_status_map = _build_hitl_status_map(
            await hitl_repo.get_by_conversation(conversation_id)
        )
        visible_assistant_message_ids = {
            event.message_id
            for event in events
            if event.event_type == "assistant_message" and event.message_id
        }
        visible_artifact_message_ids = {
            event.message_id
            for event in events
            if event.event_type == "artifact_created" and event.message_id
        }
        message_events_by_id = await event_repo.get_events_by_message_ids(
            conversation_id, visible_assistant_message_ids | visible_artifact_message_ids
        )
        completion_map = _build_completion_map(
            {
                message_id: message_events_by_id.get(message_id, [])
                for message_id in visible_assistant_message_ids
            }
        )

        message_context_events = [
            message_event
            for message_events in message_events_by_id.values()
            for message_event in message_events
        ]
        artifact_ready_map, artifact_error_map = _build_artifact_maps(
            [*events, *message_context_events]
        )

        timeline = _build_timeline(
            events,
            tool_exec_map,
            hitl_answered_map,
            hitl_status_map,
            artifact_ready_map,
            artifact_error_map,
            completion_map,
        )

        first_time_us_val = timeline[0]["eventTimeUs"] if timeline else None
        first_counter_val = timeline[0]["eventCounter"] if timeline else None
        last_time_us_val = timeline[-1]["eventTimeUs"] if timeline else None
        last_counter_val = timeline[-1]["eventCounter"] if timeline else None

        has_more = await _check_has_more(
            event_repo, conversation_id, first_time_us_val, first_counter_val
        )

        return {
            "conversationId": conversation_id,
            "timeline": timeline,
            "total": len(timeline),
            "has_more": has_more,
            "first_time_us": first_time_us_val,
            "first_counter": first_counter_val,
            "last_time_us": last_time_us_val,
            "last_counter": last_counter_val,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting conversation messages")
        raise HTTPException(status_code=500, detail=_("Failed to get messages")) from exc


@router.get("/conversations/{conversation_id}/execution")
async def get_conversation_execution(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=100, description="Maximum executions to return"),
    status_filter: str | None = Query(None, description="Filter by execution status"),
    tool_filter: str | None = Query(None, description="Filter by tool name"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the agent execution history for a conversation."""
    try:
        assert request is not None
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        executions = await agent_service.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=limit,
        )

        if status_filter:
            executions = [e for e in executions if e.get("status") == status_filter]
        if tool_filter:
            executions = [e for e in executions if e.get("tool_name") == tool_filter]

        return {
            "conversation_id": conversation_id,
            "executions": executions,
            "total": len(executions),
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=_("Conversation not found")) from e
    except Exception as exc:
        logger.exception("Error getting conversation execution history")
        raise HTTPException(status_code=500, detail=_("Failed to get execution history")) from exc


@router.get("/conversations/{conversation_id}/tool-executions")
async def get_conversation_tool_executions(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    message_id: str | None = Query(None, description="Filter by message ID"),
    limit: int = Query(100, ge=1, le=500, description="Maximum executions to return"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the tool execution history for a conversation."""
    try:
        assert request is not None
        container = get_container_with_db(request, db)

        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        _assert_conversation_scope(
            conversation,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        tool_execution_repo = container.tool_execution_record_repository()

        if message_id:
            records = [
                record
                for record in await tool_execution_repo.list_by_message(message_id, limit=limit)
                if record.conversation_id == conversation_id
            ]
        else:
            records = await tool_execution_repo.list_by_conversation(conversation_id, limit=limit)

        return {
            "conversation_id": conversation_id,
            "tool_executions": [record.to_dict() for record in records],
            "total": len(records),
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting tool execution history")
        raise HTTPException(
            status_code=500, detail=_("Failed to get tool execution history")
        ) from exc


@router.get("/conversations/{conversation_id}/status")
async def get_conversation_execution_status(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    include_recovery_info: bool = Query(
        False, description="Include event recovery information for stream resumption"
    ),
    from_time_us: int = Query(
        0, description="Client's last known event_time_us (for recovery calculation)"
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the current execution status of a conversation with optional recovery info."""
    try:
        assert request is not None
        container = get_container_with_db(request, db)

        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail=_("Conversation not found"))

        _assert_conversation_scope(
            conversation,
            current_user=current_user,
            tenant_id=tenant_id,
            project_id=project_id,
        )

        redis_client = container.redis_client
        is_running = False
        current_message_id = None

        if redis_client:
            import redis.asyncio as redis

            if isinstance(redis_client, redis.Redis):
                key = f"agent:running:{conversation_id}"
                exists = await redis_client.exists(key)
                is_running = bool(exists)

                if is_running:
                    message_id_bytes = await redis_client.get(key)
                    if message_id_bytes:
                        current_message_id = (
                            message_id_bytes.decode()
                            if isinstance(message_id_bytes, bytes)
                            else message_id_bytes
                        )

        result = {
            "conversation_id": conversation_id,
            "is_running": is_running,
            "current_message_id": current_message_id,
        }

        if include_recovery_info:
            recovery_info = await _get_recovery_info(
                container=container,
                redis_client=redis_client,
                conversation_id=conversation_id,
                message_id=current_message_id,
                from_time_us=from_time_us,
            )
            result["recovery"] = recovery_info

        return result

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting conversation execution status")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to get execution status"),
        ) from exc


async def _get_recovery_info(
    container: DIContainer,
    redis_client: Any,
    conversation_id: str,
    message_id: str | None,
    from_time_us: int,
) -> dict[str, Any]:
    """Get event stream recovery information."""
    recovery_info = {
        "can_recover": False,
        "last_event_time_us": 0,
        "last_event_counter": 0,
        "stream_exists": False,
        "recovery_source": "none",
    }

    try:
        if redis_client and message_id:
            stream_recovery = await _get_stream_recovery_info(redis_client, conversation_id)
            if stream_recovery is not None:
                recovery_info.update(stream_recovery)

        if not recovery_info["stream_exists"]:
            event_repo = container.agent_execution_event_repository()
            last_time_us, last_counter = await event_repo.get_last_event_time(conversation_id)
            if last_time_us > 0:
                recovery_info["last_event_time_us"] = last_time_us
                recovery_info["last_event_counter"] = last_counter
                recovery_info["can_recover"] = True
                recovery_info["recovery_source"] = "database"

    except Exception as e:
        logger.warning(f"Error getting recovery info: {e}")

    return recovery_info


async def _get_stream_recovery_info(
    redis_client: Any,
    conversation_id: str,
) -> dict[str, Any] | None:
    """Read recovery metadata from the Redis event stream when present."""
    import redis.asyncio as redis

    if not isinstance(redis_client, redis.Redis):
        return None

    stream_key = f"agent:events:{conversation_id}"
    recovery_info: dict[str, Any] | None = None
    try:
        stream_info = await redis_client.xinfo_stream(stream_key)
        if stream_info:
            last_entry = await redis_client.xrevrange(stream_key, count=1)
            if last_entry:
                _, fields = last_entry[0]
                recovery_info = _decode_stream_recovery_payload(
                    fields.get(b"data") or fields.get("data"),
                    conversation_id,
                )
    except redis.ResponseError:
        recovery_info = None
    return recovery_info


def _decode_stream_recovery_payload(
    data_raw: Any,
    conversation_id: str,
) -> dict[str, Any] | None:
    if not data_raw:
        return None

    try:
        data_obj = json.loads(data_raw)
    except (TypeError, ValueError):
        logger.warning(
            "Skipping malformed recovery stream payload",
            extra={"conversation_id": conversation_id},
        )
        return None

    if not isinstance(data_obj, dict):
        return None

    evt_time = data_obj.get("event_time_us", 0)
    evt_counter = data_obj.get("event_counter", 0)
    recovery_info: dict[str, Any] = {"stream_exists": True}
    if evt_time:
        recovery_info.update(
            {
                "last_event_time_us": evt_time,
                "last_event_counter": evt_counter,
                "can_recover": True,
                "recovery_source": "stream",
            }
        )
    return recovery_info


# ---------------------------------------------------------------------------
# Helpers for get_execution_stats
# ---------------------------------------------------------------------------


def _compute_durations(executions: list[dict[str, Any]]) -> list[float]:
    """Extract durations in ms from executions that have both start and end times."""
    durations: list[float] = []
    for e in executions:
        if e.get("started_at") and e.get("completed_at"):
            started = datetime.fromisoformat(e["started_at"].replace("Z", "+00:00"))
            completed = datetime.fromisoformat(e["completed_at"].replace("Z", "+00:00"))
            durations.append((completed - started).total_seconds() * 1000)
    return durations


def _compute_tool_usage(executions: list[dict[str, Any]]) -> dict[str, int]:
    """Count tool usage across executions."""
    tool_usage: dict[str, int] = {}
    for e in executions:
        tool_name = e.get("tool_name")
        if tool_name:
            tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
    return tool_usage


def _compute_status_distribution(executions: list[dict[str, Any]]) -> dict[str, int]:
    """Count status distribution across executions."""
    status_distribution: dict[str, int] = {}
    for e in executions:
        status = e.get("status", "UNKNOWN")
        status_distribution[status] = status_distribution.get(status, 0) + 1
    return status_distribution


def _compute_timeline_data(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build timeline data bucketed by hour."""
    if not executions:
        return []

    time_buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "completed": 0, "failed": 0}
    )

    for e in executions:
        if not e.get("started_at"):
            continue
        started = datetime.fromisoformat(e["started_at"].replace("Z", "+00:00"))
        bucket_key = started.strftime("%Y-%m-%d %H:00")
        time_buckets[bucket_key]["count"] += 1
        if e.get("status") == "COMPLETED":
            time_buckets[bucket_key]["completed"] += 1
        elif e.get("status") == "FAILED":
            time_buckets[bucket_key]["failed"] += 1

    return [{"time": k, **v} for k, v in sorted(time_buckets.items())]


@router.get("/conversations/{conversation_id}/execution/stats")
async def get_execution_stats(
    conversation_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ExecutionStatsResponse:
    """Get execution statistics for a conversation."""
    try:
        assert request is not None
        container = get_container_with_db(request, db)
        llm = await create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        executions = await agent_service.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=1000,
        )

        durations = _compute_durations(executions)

        return ExecutionStatsResponse(
            total_executions=len(executions),
            completed_count=sum(1 for e in executions if e.get("status") == "COMPLETED"),
            failed_count=sum(1 for e in executions if e.get("status") == "FAILED"),
            average_duration_ms=sum(durations) / len(durations) if durations else 0.0,
            tool_usage=_compute_tool_usage(executions),
            status_distribution=_compute_status_distribution(executions),
            timeline_data=_compute_timeline_data(executions),
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=_("Conversation not found")) from e
    except Exception as exc:
        logger.exception("Error getting execution statistics")
        raise HTTPException(
            status_code=500, detail=_("Failed to get execution statistics")
        ) from exc


@router.get("/conversations/{conversation_id}/messages/{message_id}/replies")
async def get_message_replies(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get replies to a specific message."""
    try:
        await _verify_conversation_access(
            conversation_id,
            current_user,
            db,
            tenant_id=tenant_id,
        )

        query = (
            select(DBMessage)
            .where(
                DBMessage.conversation_id == conversation_id,
                DBMessage.reply_to_id == message_id,
            )
            .order_by(DBMessage.created_at)
        )
        result = await db.execute(refresh_select_statement(query))
        messages = result.scalars().all()
        return [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": str(m.created_at),
                "reply_to_id": m.reply_to_id,
            }
            for m in messages
        ]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting message replies")
        raise HTTPException(status_code=500, detail=_("Failed to get message replies")) from exc
