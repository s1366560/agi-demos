"""Message and execution endpoints.

Endpoints for conversation messages, execution history, and status.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.factories import create_llm_client
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

from .schemas import ExecutionStatsResponse
from .utils import get_container_with_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=500, description="Maximum events to return"),
    from_time_us: Optional[int] = Query(
        None, description="Starting event_time_us (inclusive) for forward pagination"
    ),
    from_counter: Optional[int] = Query(
        None, description="Starting event_counter (inclusive) for forward pagination"
    ),
    before_time_us: Optional[int] = Query(
        None, description="For backward pagination, get events before this event_time_us"
    ),
    before_counter: Optional[int] = Query(
        None, description="For backward pagination, event_counter for the cursor"
    ),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Get conversation timeline from unified event stream with bidirectional pagination.

    Returns timeline of all events in the conversation, ordered by sequence number.
    """
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
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

        DISPLAYABLE_EVENTS = {
            "user_message",
            "assistant_message",
            "thought",
            "act",
            "observe",
            "work_plan",
            "step_start",
            "step_end",
            "artifact_created",
            "artifact_ready",
            "artifact_error",
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

        calc_from_time_us = from_time_us or 0
        calc_from_counter = from_counter or 0
        calc_before_time_us = before_time_us
        calc_before_counter = before_counter

        if calc_from_time_us == 0 and calc_before_time_us is None:
            last_time_us, last_counter = await event_repo.get_last_event_time(conversation_id)
            if last_time_us > 0:
                # Load latest events by backward pagination from end
                calc_before_time_us = last_time_us + 1
                calc_before_counter = 0
                calc_from_time_us = 0

        events = await event_repo.get_events(
            conversation_id=conversation_id,
            from_time_us=calc_from_time_us,
            from_counter=calc_from_counter,
            limit=limit,
            event_types=DISPLAYABLE_EVENTS,
            before_time_us=calc_before_time_us,
            before_counter=calc_before_counter,
        )

        tool_executions = await tool_exec_repo.list_by_conversation(conversation_id)
        tool_exec_map = {}
        for te in tool_executions:
            key = f"{te.message_id}:{te.tool_name}"
            tool_exec_map[key] = {
                "startTime": te.started_at.timestamp() * 1000 if te.started_at else None,
                "endTime": te.completed_at.timestamp() * 1000 if te.completed_at else None,
                "duration": te.duration_ms,
            }

        # Build HITL answered map: collect all answered events by request_id
        # This allows us to determine if a *_asked event has been answered
        hitl_answered_map: dict = {}  # request_id -> answer data
        for event in events:
            event_type = event.event_type
            data = event.event_data or {}
            request_id = data.get("request_id", "")
            if event_type == "clarification_answered" and request_id:
                hitl_answered_map[request_id] = {"answer": data.get("answer", "")}
            elif event_type == "decision_answered" and request_id:
                hitl_answered_map[request_id] = {"decision": data.get("decision", "")}
            elif event_type == "env_var_provided" and request_id:
                hitl_answered_map[request_id] = {"values": data.get("values", {})}
            elif event_type in ("permission_granted", "permission_replied") and request_id:
                hitl_answered_map[request_id] = {"granted": data.get("granted", False)}

        # Also query HITL requests table for status (handles cases where answered event
        # might not be in current page, or HITL was answered but agent hasn't resumed)
        hitl_repo = container.hitl_request_repository()
        hitl_requests = await hitl_repo.get_by_conversation(conversation_id)
        hitl_status_map: dict = {}  # request_id -> status info
        for req in hitl_requests:
            hitl_status_map[req.id] = {
                "status": req.status.value if hasattr(req.status, "value") else req.status,
                "response": req.response,
                "response_metadata": req.response_metadata or {},
            }

        # Build artifact status map: merge artifact_ready/error into artifact_created
        artifact_ready_map: dict = {}  # artifact_id -> {url, preview_url, ...}
        artifact_error_map: dict = {}  # artifact_id -> {error}
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

        timeline = []
        for event in events:
            event_type = event.event_type
            data = event.event_data or {}
            item = {
                "id": f"{event_type}-{event.event_time_us}-{event.event_counter}",
                "type": event_type,
                "eventTimeUs": event.event_time_us,
                "eventCounter": event.event_counter,
                "timestamp": event.event_time_us // 1000 if event.event_time_us else (
                    int(event.created_at.timestamp() * 1000) if event.created_at else None
                ),
            }

            if event_type == "user_message":
                item["message_id"] = data.get("message_id")
                item["content"] = data.get("content", "")
                item["role"] = "user"

            elif event_type == "assistant_message":
                item["message_id"] = data.get("message_id")
                item["content"] = data.get("content", "")
                item["role"] = "assistant"

            elif event_type == "thought":
                thought_content = data.get("thought", "")
                if not thought_content or not thought_content.strip():
                    continue
                item["content"] = thought_content

            elif event_type == "act":
                item["toolName"] = data.get("tool_name", "")
                item["toolInput"] = data.get("tool_input", {})
                key = f"{event.message_id}:{data.get('tool_name', '')}"
                if key in tool_exec_map:
                    item["execution"] = tool_exec_map[key]

            elif event_type == "observe":
                item["toolName"] = data.get("tool_name", "")
                item["toolOutput"] = data.get("observation", "")
                item["isError"] = data.get("is_error", False)

            elif event_type == "work_plan":
                item["steps"] = data.get("steps", [])
                item["status"] = data.get("status", "planning")

            elif event_type == "step_start":
                item["stepIndex"] = data.get("step_index", 0)
                item["stepDescription"] = data.get("description", "")

            elif event_type == "step_end":
                item["stepIndex"] = data.get("step_index", 0)
                item["status"] = data.get("status", "completed")

            elif event_type == "artifact_created":
                artifact_id = data.get("artifact_id", "")
                item["artifactId"] = artifact_id
                item["filename"] = data.get("filename", "")
                item["mimeType"] = data.get("mime_type", "")
                item["category"] = data.get("category", "other")
                item["sizeBytes"] = data.get("size_bytes", 0)
                item["url"] = data.get("url", "")
                item["previewUrl"] = data.get("preview_url", "")
                item["sourceTool"] = data.get("source_tool", "")
                item["metadata"] = data.get("metadata", {})
                # Merge artifact_ready data if available
                if artifact_id in artifact_ready_map:
                    ready = artifact_ready_map[artifact_id]
                    item["url"] = ready.get("url") or item["url"]
                    item["previewUrl"] = ready.get("preview_url") or item["previewUrl"]
                # Merge artifact_error data if available
                if artifact_id in artifact_error_map:
                    item["error"] = artifact_error_map[artifact_id].get("error", "")

            # Skip artifact_ready/error - merged into artifact_created above
            elif event_type in ("artifact_ready", "artifact_error"):
                continue

            # HITL events - determine answered status from:
            # 1. Corresponding *_answered event in timeline
            # 2. HITL request status from database
            elif event_type == "clarification_asked":
                request_id = data.get("request_id", "")
                item["requestId"] = request_id
                item["question"] = data.get("question", "")
                item["options"] = data.get("options", [])
                item["allowCustom"] = data.get("allow_custom", True)
                # Check if answered
                answered = False
                answer = None
                if request_id in hitl_answered_map:
                    answered = True
                    answer = hitl_answered_map[request_id].get("answer")
                elif request_id in hitl_status_map:
                    status_info = hitl_status_map[request_id]
                    if status_info["status"] in ("answered", "completed"):
                        answered = True
                        # response holds the raw answer, response_metadata may have structured data
                        answer = status_info.get("response") or status_info.get("response_metadata", {}).get("answer")
                item["answered"] = answered
                item["answer"] = answer

            elif event_type == "clarification_answered":
                item["requestId"] = data.get("request_id", "")
                item["answer"] = data.get("answer", "")

            elif event_type == "decision_asked":
                request_id = data.get("request_id", "")
                item["requestId"] = request_id
                item["question"] = data.get("question", "")
                item["options"] = data.get("options", [])
                item["decisionType"] = data.get("decision_type", "branch")
                item["allowCustom"] = data.get("allow_custom", False)
                item["defaultOption"] = data.get("default_option")
                # Check if answered
                answered = False
                decision = None
                if request_id in hitl_answered_map:
                    answered = True
                    decision = hitl_answered_map[request_id].get("decision")
                elif request_id in hitl_status_map:
                    status_info = hitl_status_map[request_id]
                    if status_info["status"] in ("answered", "completed"):
                        answered = True
                        # response holds the raw decision, response_metadata may have structured data
                        decision = status_info.get("response") or status_info.get("response_metadata", {}).get("decision")
                item["answered"] = answered
                item["decision"] = decision

            elif event_type == "decision_answered":
                item["requestId"] = data.get("request_id", "")
                item["decision"] = data.get("decision", "")

            elif event_type == "env_var_requested":
                request_id = data.get("request_id", "")
                item["requestId"] = request_id
                item["variables"] = data.get("variables", [])
                item["reason"] = data.get("reason", "")
                # Check if answered
                answered = False
                values = {}
                if request_id in hitl_answered_map:
                    answered = True
                    values = hitl_answered_map[request_id].get("values", {})
                elif request_id in hitl_status_map:
                    status_info = hitl_status_map[request_id]
                    if status_info["status"] in ("answered", "completed"):
                        answered = True
                        # For env_var, values are stored in response_metadata
                        values = status_info.get("response_metadata", {}).get("values", {})
                item["answered"] = answered
                item["values"] = values

            elif event_type == "env_var_provided":
                item["requestId"] = data.get("request_id", "")
                item["variables"] = list(data.get("values", {}).keys())

            elif event_type in ("permission_requested", "permission_asked"):
                request_id = data.get("request_id", "")
                item["requestId"] = request_id
                item["action"] = data.get("action", "")
                item["resource"] = data.get("resource", "")
                item["reason"] = data.get("reason", "")
                # SSE format fields
                item["toolName"] = data.get("tool_name", "")
                item["toolDisplayName"] = data.get("tool_display_name", "")
                item["riskLevel"] = data.get("risk_level", "medium")
                item["description"] = data.get("description", "")
                item["allowRemember"] = data.get("allow_remember", True)
                # Check if answered
                answered = False
                granted = None
                if request_id in hitl_answered_map:
                    answered = True
                    granted = hitl_answered_map[request_id].get("granted")
                elif request_id in hitl_status_map:
                    status_info = hitl_status_map[request_id]
                    if status_info["status"] in ("answered", "completed"):
                        answered = True
                        # For permission, granted is stored in response_metadata
                        granted = status_info.get("response_metadata", {}).get("granted")
                item["answered"] = answered
                item["granted"] = granted

            elif event_type in ("permission_granted", "permission_replied"):
                item["requestId"] = data.get("request_id", "")
                item["granted"] = data.get("granted", False)

            timeline.append(item)

        first_time_us = None
        first_counter = None
        last_time_us = None
        last_counter = None
        if timeline:
            first_time_us = timeline[0]["eventTimeUs"]
            first_counter = timeline[0]["eventCounter"]
            last_time_us = timeline[-1]["eventTimeUs"]
            last_counter = timeline[-1]["eventCounter"]

        has_more = False
        if first_time_us is not None:
            check_events = await event_repo.get_events(
                conversation_id=conversation_id,
                from_time_us=0,
                limit=1,
                event_types=DISPLAYABLE_EVENTS,
                before_time_us=first_time_us,
                before_counter=first_counter,
            )
            has_more = len(check_events) > 0

        return {
            "conversationId": conversation_id,
            "timeline": timeline,
            "total": len(timeline),
            "has_more": has_more,
            "first_time_us": first_time_us,
            "first_counter": first_counter,
            "last_time_us": last_time_us,
            "last_counter": last_counter,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.error(f"Error getting conversation messages: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to get messages: {str(e)}")


@router.get("/conversations/{conversation_id}/execution")
async def get_conversation_execution(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    limit: int = Query(50, ge=1, le=100, description="Maximum executions to return"),
    status_filter: Optional[str] = Query(None, description="Filter by execution status"),
    tool_filter: Optional[str] = Query(None, description="Filter by tool name"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """Get the agent execution history for a conversation."""
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
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
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting conversation execution history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution history: {str(e)}")


@router.get("/conversations/{conversation_id}/tool-executions")
async def get_conversation_tool_executions(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    message_id: Optional[str] = Query(None, description="Filter by message ID"),
    limit: int = Query(100, ge=1, le=500, description="Maximum executions to return"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> dict:
    """Get the tool execution history for a conversation."""
    try:
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
            status_code=500, detail=f"Failed to get tool execution history: {str(e)}"
        )


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
    request: Request = None,
) -> dict:
    """Get the current execution status of a conversation with optional recovery info."""
    try:
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
        raise HTTPException(status_code=500, detail=f"Failed to get execution status: {str(e)}")


async def _get_recovery_info(
    container,
    redis_client,
    conversation_id: str,
    message_id: Optional[str],
    from_time_us: int,
) -> dict:
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


@router.get("/conversations/{conversation_id}/execution/stats")
async def get_execution_stats(
    conversation_id: str,
    project_id: str = Query(..., description="Project ID for authorization"),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> ExecutionStatsResponse:
    """Get execution statistics for a conversation."""
    try:
        container = get_container_with_db(request, db)
        llm = create_llm_client(tenant_id)
        agent_service = container.agent_service(llm)

        executions = await agent_service.get_execution_history(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=current_user.id,
            limit=1000,
        )

        total_executions = len(executions)
        completed_count = sum(1 for e in executions if e.get("status") == "COMPLETED")
        failed_count = sum(1 for e in executions if e.get("status") == "FAILED")

        durations = []
        for e in executions:
            if e.get("started_at") and e.get("completed_at"):
                from datetime import datetime

                started = datetime.fromisoformat(e["started_at"].replace("Z", "+00:00"))
                completed = datetime.fromisoformat(e["completed_at"].replace("Z", "+00:00"))
                duration_ms = (completed - started).total_seconds() * 1000
                durations.append(duration_ms)

        average_duration_ms = sum(durations) / len(durations) if durations else 0.0

        tool_usage: dict[str, int] = {}
        for e in executions:
            tool_name = e.get("tool_name")
            if tool_name:
                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1

        status_distribution: dict[str, int] = {}
        for e in executions:
            status = e.get("status", "UNKNOWN")
            status_distribution[status] = status_distribution.get(status, 0) + 1

        timeline_data = []
        if executions:
            from collections import defaultdict
            from datetime import datetime

            time_buckets: dict[str, dict] = defaultdict(
                lambda: {"count": 0, "completed": 0, "failed": 0}
            )

            for e in executions:
                if e.get("started_at"):
                    started = datetime.fromisoformat(e["started_at"].replace("Z", "+00:00"))
                    bucket_key = started.strftime("%Y-%m-%d %H:00")
                    time_buckets[bucket_key]["count"] += 1

                    if e.get("status") == "COMPLETED":
                        time_buckets[bucket_key]["completed"] += 1
                    elif e.get("status") == "FAILED":
                        time_buckets[bucket_key]["failed"] += 1

            timeline_data = [{"time": k, **v} for k, v in sorted(time_buckets.items())]

        return ExecutionStatsResponse(
            total_executions=total_executions,
            completed_count=completed_count,
            failed_count=failed_count,
            average_duration_ms=average_duration_ms,
            tool_usage=tool_usage,
            status_distribution=status_distribution,
            timeline_data=timeline_data,
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting execution statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution statistics: {str(e)}")
