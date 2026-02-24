"""Message and execution endpoints.

Endpoints for conversation messages, execution history, and status.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.configuration.factories import create_llm_client
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Message as DBMessage,
    User,
)

from .schemas import ExecutionStatsResponse
from .utils import get_container_with_db

router = APIRouter()
logger = logging.getLogger(__name__)

_DISPLAYABLE_EVENTS = {
    "user_message",
    "assistant_message",
    "thought",
    "act",
    "observe",
    "work_plan",
    "artifact_created",
    "artifact_ready",
    "artifact_error",
    # Task timeline events
    "task_start",
    "task_complete",
    # HITL (Human-in-the-Loop) events
    "clarification_asked",
    "clarification_answered",
    "decision_asked",
    "decision_answered",
    "env_var_requested",
    "env_var_provided",
    # Agent emits both permission_asked and permission_requested
    "permission_asked",
    "permission_requested",
    # Agent emits both permission_replied and permission_granted
    "permission_replied",
    "permission_granted",
}

_SKIP_EVENT_SENTINEL = object()


# ---------------------------------------------------------------------------
# Helpers for get_conversation_messages
# ---------------------------------------------------------------------------


def _build_tool_exec_map(tool_executions: list[Any]) -> dict[str, Any]:
    """Build a lookup map from tool executions keyed by message_id:tool_name."""
    tool_exec_map: dict[str, dict[str, Any]] = {}
    for te in tool_executions:
        key = f"{te.message_id}:{te.tool_name}"
        tool_exec_map[key] = {
            "startTime": te.started_at.timestamp() * 1000 if te.started_at else None,
            "endTime": te.completed_at.timestamp() * 1000 if te.completed_at else None,
            "duration": te.duration_ms,
        }
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


def _build_assistant_message(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    return {
        "message_id": data.get("message_id"),
        "content": data.get("content", ""),
        "role": "assistant",
    }


def _build_thought(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any] | object:
    thought_content = data.get("thought", "")
    if not thought_content or not thought_content.strip():
        return _SKIP_EVENT_SENTINEL
    return {"content": thought_content}


def _build_act(data: dict[str, Any], event: Any, tool_exec_map: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "toolName": data.get("tool_name", ""),
        "toolInput": data.get("tool_input", {}),
    }
    key = f"{event.message_id}:{data.get('tool_name', '')}"
    if key in tool_exec_map:
        item["execution"] = tool_exec_map[key]
    return item


def _build_observe(data: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "toolName": data.get("tool_name", ""),
        "toolOutput": data.get("observation", ""),
        "isError": data.get("is_error", False),
    }
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
    data: dict[str, Any], artifact_ready_map: dict[str, Any], artifact_error_map: dict[str, Any], **_kwargs: Any
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
    data: dict[str, Any], hitl_answered_map: dict[str, Any], hitl_status_map: dict[str, Any], **_kwargs: Any
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
    data: dict[str, Any], hitl_answered_map: dict[str, Any], hitl_status_map: dict[str, Any], **_kwargs: Any
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
    data: dict[str, Any], hitl_answered_map: dict[str, Any], hitl_status_map: dict[str, Any], **_kwargs: Any
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


def _build_permission_asked(
    data: dict[str, Any], hitl_answered_map: dict[str, Any], hitl_status_map: dict[str, Any], **_kwargs: Any
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


# Dispatch dict: event_type -> builder function
_EVENT_BUILDERS: dict[str, Any] = {
    "user_message": _build_user_message,
    "assistant_message": _build_assistant_message,
    "thought": _build_thought,
    "act": _build_act,
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
    "permission_requested": _build_permission_asked,
    "permission_asked": _build_permission_asked,
    "permission_granted": _build_permission_replied,
    "permission_replied": _build_permission_replied,
}


def _build_timeline(
    events: list[Any],
    tool_exec_map: dict[str, Any],
    hitl_answered_map: dict[str, Any],
    hitl_status_map: dict[str, Any],
    artifact_ready_map: dict[str, Any],
    artifact_error_map: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the timeline list from raw events using the dispatch dict."""
    timeline: list[dict[str, Any]] = []
    for event in events:
        event_type = event.event_type
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
        )
        if fields is _SKIP_EVENT_SENTINEL:
            continue

        item = {
            "id": f"{event_type}-{event.event_time_us}-{event.event_counter}",
            "type": event_type,
            "eventTimeUs": event.event_time_us,
            "eventCounter": event.event_counter,
            "timestamp": event.event_time_us // 1000
            if event.event_time_us
            else (int(event.created_at.timestamp() * 1000) if event.created_at else None),
        }
        item.update(fields)
        timeline.append(item)
    return timeline


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
    request: Request | None = None,
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
            raise HTTPException(status_code=404, detail="Conversation not found")

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

        artifact_ready_map, artifact_error_map = _build_artifact_maps(events)

        timeline = _build_timeline(
            events,
            tool_exec_map,
            hitl_answered_map,
            hitl_status_map,
            artifact_ready_map,
            artifact_error_map,
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
    except Exception as e:
        import traceback

        logger.error(f"Error getting conversation messages: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {e!s}") from e


@router.get("/conversations/{conversation_id}/execution")
async def get_conversation_execution(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=100, description="Maximum executions to return"),
    status_filter: str | None = Query(None, description="Filter by execution status"),
    tool_filter: str | None = Query(None, description="Filter by tool name"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting conversation execution history: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get execution history: {e!s}"
        ) from e


@router.get("/conversations/{conversation_id}/tool-executions")
async def get_conversation_tool_executions(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    message_id: str | None = Query(None, description="Filter by message ID"),
    limit: int = Query(100, ge=1, le=500, description="Maximum executions to return"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> dict[str, Any]:
    """Get the tool execution history for a conversation."""
    try:
        assert request is not None
        container = get_container_with_db(request, db)

        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        tool_execution_repo = container.tool_execution_record_repository()

        if message_id:
            records = await tool_execution_repo.list_by_message(message_id, limit=limit)
        else:
            records = await tool_execution_repo.list_by_conversation(conversation_id, limit=limit)

        return {
            "conversation_id": conversation_id,
            "tool_executions": [record.to_dict() for record in records],
            "total": len(records),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tool execution history: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get tool execution history: {e!s}"
        ) from e


@router.get("/conversations/{conversation_id}/status")
async def get_conversation_execution_status(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    include_recovery_info: bool = Query(
        False, description="Include event recovery information for stream resumption"
    ),
    from_time_us: int = Query(
        0, description="Client's last known event_time_us (for recovery calculation)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
) -> dict[str, Any]:
    """Get the current execution status of a conversation with optional recovery info."""
    try:
        assert request is not None
        container = get_container_with_db(request, db)

        conversation_repo = container.conversation_repository()
        conversation = await conversation_repo.find_by_id(conversation_id)

        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if conversation.user_id != current_user.id or conversation.project_id != project_id:
            raise HTTPException(status_code=403, detail="Access denied")

        redis_client = container._redis_client
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
    except Exception as e:
        logger.error(f"Error getting conversation execution status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution status: {e!s}") from e


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
            import redis.asyncio as redis

            if isinstance(redis_client, redis.Redis):
                stream_key = f"agent:events:{conversation_id}"
                try:
                    stream_info = await redis_client.xinfo_stream(stream_key)
                    if stream_info:
                        recovery_info["stream_exists"] = True
                        last_entry = await redis_client.xrevrange(stream_key, count=1)
                        if last_entry:
                            _, fields = last_entry[0]
                            data_raw = fields.get(b"data") or fields.get("data")
                            if data_raw:
                                import json

                                data_obj = json.loads(data_raw)
                                evt_time = data_obj.get("event_time_us", 0)
                                evt_counter = data_obj.get("event_counter", 0)
                                if evt_time:
                                    recovery_info["last_event_time_us"] = evt_time
                                    recovery_info["last_event_counter"] = evt_counter
                                    recovery_info["can_recover"] = True
                                    recovery_info["recovery_source"] = "stream"
                except redis.ResponseError:
                    pass

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

    time_buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "completed": 0, "failed": 0})

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
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request | None = None,
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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error getting execution statistics: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get execution statistics: {e!s}"
        ) from e


@router.get("/conversations/{conversation_id}/messages/{message_id}/replies")
async def get_message_replies(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get replies to a specific message."""
    try:
        query = (
            select(DBMessage)
            .where(
                DBMessage.conversation_id == conversation_id,
                DBMessage.reply_to_id == message_id,
            )
            .order_by(DBMessage.created_at)
        )
        result = await db.execute(query)
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
    except Exception as e:
        logger.error(f"Error getting message replies: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get message replies: {e!s}") from e
