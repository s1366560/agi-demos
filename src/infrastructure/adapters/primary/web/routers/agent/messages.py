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
    from_sequence: int = Query(
        0, description="Starting sequence number (inclusive) for forward pagination"
    ),
    before_sequence: Optional[int] = Query(
        None, description="For backward pagination, get events before this sequence"
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
        }

        calculated_from_sequence = from_sequence
        calculated_before_sequence = before_sequence

        if from_sequence == 0 and before_sequence is None:
            last_seq = await event_repo.get_last_sequence(conversation_id)
            if last_seq > 0:
                calculated_before_sequence = last_seq + 1
                calculated_from_sequence = 0

        events = await event_repo.get_events(
            conversation_id=conversation_id,
            from_sequence=calculated_from_sequence,
            limit=limit,
            event_types=DISPLAYABLE_EVENTS,
            before_sequence=calculated_before_sequence,
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

        timeline = []
        for event in events:
            event_type = event.event_type
            data = event.event_data or {}
            item = {
                "id": f"{event_type}-{event.sequence_number}",
                "type": event_type,
                "sequenceNumber": event.sequence_number,
                "timestamp": int(event.created_at.timestamp() * 1000) if event.created_at else None,
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
                item["artifactId"] = data.get("artifact_id", "")
                item["filename"] = data.get("filename", "")
                item["mimeType"] = data.get("mime_type", "")
                item["category"] = data.get("category", "other")
                item["sizeBytes"] = data.get("size_bytes", 0)
                item["url"] = data.get("url", "")
                item["previewUrl"] = data.get("preview_url", "")
                item["sourceTool"] = data.get("source_tool", "")
                item["metadata"] = data.get("metadata", {})

            timeline.append(item)

        first_sequence = None
        last_sequence = None
        if timeline:
            first_sequence = timeline[0]["sequenceNumber"]
            last_sequence = timeline[-1]["sequenceNumber"]

        has_more = False
        if first_sequence is not None and before_sequence is None:
            if first_sequence > 0:
                has_more = True
        elif first_sequence is not None and before_sequence is not None:
            check_events = await event_repo.get_events(
                conversation_id=conversation_id,
                from_sequence=0,
                limit=1,
                event_types=DISPLAYABLE_EVENTS,
                before_sequence=first_sequence,
            )
            has_more = len(check_events) > 0

        return {
            "conversationId": conversation_id,
            "timeline": timeline,
            "total": len(timeline),
            "has_more": has_more,
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
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
    from_sequence: int = Query(
        0, description="Client's last known sequence (for recovery calculation)"
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
                from_sequence=from_sequence,
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
    from_sequence: int,
) -> dict:
    """Get event stream recovery information."""
    recovery_info = {
        "can_recover": False,
        "last_sequence": -1,
        "missed_events_count": 0,
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
                            seq_raw = fields.get(b"seq") or fields.get("seq")
                            if seq_raw:
                                recovery_info["last_sequence"] = int(seq_raw)
                                recovery_info["can_recover"] = True
                                recovery_info["recovery_source"] = "stream"
                                recovery_info["missed_events_count"] = max(
                                    0, recovery_info["last_sequence"] - from_sequence
                                )
                except redis.ResponseError:
                    pass

        if not recovery_info["stream_exists"]:
            event_repo = container.agent_execution_event_repository()
            last_db_seq = await event_repo.get_last_sequence(conversation_id)
            if last_db_seq >= 0:
                recovery_info["last_sequence"] = last_db_seq
                recovery_info["can_recover"] = True
                recovery_info["recovery_source"] = "database"
                recovery_info["missed_events_count"] = max(0, last_db_seq - from_sequence)

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
