"""Task management API routes."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.application.use_cases.task import (
    GetTaskQuery,
    UpdateTaskCommand,
)
from src.configuration.di_container import DIContainer
from src.domain.model.task.task_log import TaskLog, TaskLogStatus
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import TaskLog as DBTaskLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


# --- Schemas ---


class TaskStatsResponse(BaseModel):
    total: int
    pending: int
    processing: int
    completed: int
    failed: int
    throughput_per_minute: float
    error_rate: float


class TaskLogResponse(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    worker_id: str | None
    retries: int
    duration: str | None
    entity_id: str | None
    entity_type: str | None
    progress: int = 0
    result: dict | None = None
    message: str | None = None


class QueueDepthPoint(BaseModel):
    timestamp: str
    depth: int


# --- FastAPI Dependencies ---


async def get_di_container(db: AsyncSession = Depends(get_db)) -> DIContainer:
    """Get DI container with use cases"""
    return DIContainer(db)


# --- Helper Functions ---


def task_to_response(task: TaskLog) -> TaskLogResponse:
    """Convert domain TaskLog to response DTO"""
    duration_str = "-"
    if task.started_at and task.completed_at:
        ms = int((task.completed_at - task.started_at).total_seconds() * 1000)
        if ms < 1000:
            duration_str = f"{ms}ms"
        else:
            duration_str = f"{ms / 1000:.1f}s"
    elif task.status == TaskLogStatus.FAILED and task.started_at and task.completed_at:
        ms = int((task.completed_at - task.started_at).total_seconds() * 1000)
        duration_str = f"{ms / 1000:.1f}s"

    return TaskLogResponse(
        id=task.id,
        name=task.task_type,
        status=task.status.lower().capitalize(),
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        error=task.error_message,
        worker_id=task.worker_id or "-",
        retries=task.retry_count,
        duration=duration_str,
        entity_id=task.entity_id,
        entity_type=task.entity_type,
        progress=getattr(task, "progress", 0),
        result=getattr(task, "result", None),
        message=getattr(task, "message", None),
    )


# --- Endpoints ---

# NOTE: Dynamic routes with path parameters must be defined AFTER specific routes
# to avoid route matching conflicts (e.g., "/stats" should match before "/{task_id}")


@router.get("/stats", response_model=TaskStatsResponse)
async def get_task_stats(db: AsyncSession = Depends(get_db)):
    """Get task statistics."""
    now = datetime.now(UTC)
    one_day_ago = now - timedelta(days=1)
    one_hour_ago = now - timedelta(hours=1)

    # Total tasks (24h)
    total_24h = (
        await db.scalar(select(func.count(DBTaskLog.id)).where(DBTaskLog.created_at >= one_day_ago))
        or 0
    )

    # Completed (24h)
    completed_24h = (
        await db.scalar(
            select(func.count(DBTaskLog.id)).where(
                DBTaskLog.status == "COMPLETED", DBTaskLog.created_at >= one_day_ago
            )
        )
        or 0
    )

    # Failed (24h) - for error rate
    failed_24h = (
        await db.scalar(
            select(func.count(DBTaskLog.id)).where(
                DBTaskLog.status == "FAILED", DBTaskLog.created_at >= one_day_ago
            )
        )
        or 0
    )

    # Failed (1h) - for dashboard card
    failed_1h = (
        await db.scalar(
            select(func.count(DBTaskLog.id)).where(
                DBTaskLog.status == "FAILED", DBTaskLog.completed_at >= one_hour_ago
            )
        )
        or 0
    )

    # Pending & Processing (Active)
    pending = (
        await db.scalar(select(func.count(DBTaskLog.id)).where(DBTaskLog.status == "PENDING")) or 0
    )
    processing = (
        await db.scalar(select(func.count(DBTaskLog.id)).where(DBTaskLog.status == "PROCESSING"))
        or 0
    )

    # Throughput (completed per minute in last hour)
    completed_1h = (
        await db.scalar(
            select(func.count(DBTaskLog.id)).where(
                DBTaskLog.status == "COMPLETED", DBTaskLog.completed_at >= one_hour_ago
            )
        )
        or 0
    )
    throughput = completed_1h / 60

    # Error Rate
    error_rate = (failed_24h / total_24h * 100) if total_24h > 0 else 0.0

    return TaskStatsResponse(
        total=total_24h,
        pending=pending,
        processing=processing,
        completed=completed_24h,
        failed=failed_1h,
        throughput_per_minute=throughput,
        error_rate=error_rate,
    )


@router.get("/queue-depth", response_model=list[QueueDepthPoint])
async def get_queue_depth(db: AsyncSession = Depends(get_db)):
    """Get queue depth over time."""
    now = datetime.now(UTC)
    points = []

    # Generate points every 3 hours for the last 24 hours
    times = []
    for i in range(8, -1, -1):
        t = now - timedelta(hours=i * 3)
        times.append(t)

    for t in times:
        # Count tasks that were created <= t AND (completed > t OR completed is NULL)
        count = (
            await db.scalar(
                select(func.count(DBTaskLog.id)).where(
                    DBTaskLog.created_at <= t,
                    (DBTaskLog.completed_at > t) | (DBTaskLog.completed_at.is_(None)),
                )
            )
            or 0
        )

        points.append(QueueDepthPoint(timestamp=t.strftime("%H:%M"), depth=count))

    return points


@router.get("/recent", response_model=list[TaskLogResponse])
async def get_recent_tasks(
    status: str | None = None,
    task_type: str | None = None,
    search: str | None = None,
    entity_id: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get recent tasks with filtering."""
    # For complex queries with multiple filters, use direct DB access
    # In a full refactoring, this would move to a use case with filter objects
    query = select(DBTaskLog).order_by(desc(DBTaskLog.created_at))

    if status and status != "All Statuses":
        query = query.where(DBTaskLog.status == status.upper())

    if task_type and task_type != "All Types":
        query = query.where(DBTaskLog.task_type == task_type)

    if entity_id:
        query = query.where(DBTaskLog.entity_id == entity_id)

    if entity_type:
        query = query.where(DBTaskLog.entity_type == entity_type)

    if search:
        query = query.where(
            (DBTaskLog.id.ilike(f"%{search}%")) | (DBTaskLog.worker_id.ilike(f"%{search}%"))
        )

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    db_tasks = result.scalars().all()

    # Convert to domain models for consistency
    response = []
    for t in db_tasks:
        duration_str = "-"
        if t.started_at and t.completed_at:
            ms = int((t.completed_at - t.started_at).total_seconds() * 1000)
            if ms < 1000:
                duration_str = f"{ms}ms"
            else:
                duration_str = f"{ms / 1000:.1f}s"
        elif t.status == "FAILED" and t.started_at and t.completed_at:
            ms = int((t.completed_at - t.started_at).total_seconds() * 1000)
            duration_str = f"{ms / 1000:.1f}s"

        response.append(
            TaskLogResponse(
                id=t.id,
                name=t.task_type,
                status=t.status.lower().capitalize(),
                created_at=t.created_at,
                started_at=t.started_at,
                completed_at=t.completed_at,
                error=t.error_message,
                worker_id=t.worker_id or "-",
                retries=t.retry_count,
                duration=duration_str,
                entity_id=t.entity_id,
                entity_type=t.entity_type,
            )
        )

    return response


@router.get("/status-breakdown")
async def get_status_breakdown(db: AsyncSession = Depends(get_db)):
    """Get task status breakdown."""
    now = datetime.now(UTC)
    one_day_ago = now - timedelta(days=1)

    query = (
        select(DBTaskLog.status, func.count(DBTaskLog.id))
        .where(DBTaskLog.created_at >= one_day_ago)
        .group_by(DBTaskLog.status)
    )

    result = await db.execute(query)
    breakdown = {row[0]: row[1] for row in result.all()}

    return {
        "Completed": breakdown.get("COMPLETED", 0),
        "Processing": breakdown.get("PROCESSING", 0),
        "Failed": breakdown.get("FAILED", 0),
        "Pending": breakdown.get("PENDING", 0),
    }


@router.post("/{task_id}/retry")
async def retry_task_endpoint(
    task_id: str,
    container: DIContainer = Depends(get_di_container),
):
    """Retry a failed task."""
    use_case = container.update_task_use_case()

    # Get the task first to check status
    task = await use_case.execute(
        UpdateTaskCommand(
            task_id=task_id,
            status="PENDING",
            error_message=None,
        )
    )

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status != TaskLogStatus.FAILED:
        raise HTTPException(status_code=400, detail="Task can only be retried if failed")

    # Update task to pending
    task = await use_case.execute(
        UpdateTaskCommand(
            task_id=task_id,
            status="PENDING",
            error_message=None,
        )
    )

    return {"message": "Task retried successfully"}


@router.post("/{task_id}/stop")
async def stop_task_endpoint(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    container: DIContainer = Depends(get_di_container),
):
    """Stop a running task."""
    get_use_case = container.get_task_use_case()
    update_use_case = container.update_task_use_case()

    # Get the task first
    task = await get_use_case.execute(GetTaskQuery(task_id=task_id))

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ["PENDING", "PROCESSING"]:
        raise HTTPException(
            status_code=400, detail="Task can only be stopped if pending or processing"
        )

    # Mark task as stopped
    now = datetime.now(UTC)
    await update_use_case.execute(
        UpdateTaskCommand(
            task_id=task_id,
            status="FAILED",
            error_message="Task stopped by user",
            completed_at=now,
            stopped_at=now,
        )
    )
    await db.commit()

    return {"message": "Task marked as stopped"}


@router.get("/{task_id}/stream", response_class=EventSourceResponse)
async def stream_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    """Stream task status updates using Server-Sent Events (SSE).

    This endpoint provides real-time updates for task progress, completion, and errors.
    Clients should connect using EventSource API and handle these event types:
    - progress: Task progress update (0-100)
    - completed: Task completed successfully
    - failed: Task failed with error

    Example:
        const eventSource = new EventSource('/api/v1/tasks/{task_id}/stream');
        eventSource.addEventListener('progress', (e) => {
            const data = JSON.parse(e.data);
            console.log('Progress:', data.progress, 'Message:', data.message);
        });
        eventSource.addEventListener('completed', (e) => {
            const data = JSON.parse(e.data);
            console.log('Completed:', data);
            eventSource.close();
        });
    """
    logger.info(f"SSE stream requested for task {task_id}")

    async def event_generator():
        """Generate SSE events for task status updates."""
        logger.info(f"Event generator started for task {task_id}")

        # Create a new session for the generator to avoid session closure issues
        from src.infrastructure.adapters.secondary.persistence.database import async_session_factory

        try:
            # Get initial task state with a fresh session
            async with async_session_factory() as session:
                result = await session.execute(select(DBTaskLog).where(DBTaskLog.id == task_id))
                task = result.scalar_one_or_none()

                if not task:
                    # Send error event and close
                    logger.error(f"Task {task_id} not found in database")
                    yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
                    return

                logger.info(f"Task {task_id} found with status: {task.status}")

                # If task is already in a final state, send final event directly
                if task.status in (TaskLogStatus.COMPLETED, TaskLogStatus.FAILED):
                    event_type = "completed" if task.status == TaskLogStatus.COMPLETED else "failed"
                    logger.info(
                        f"Task {task_id} is already in final state: {task.status}, sending {event_type} event"
                    )
                    response_dict = task_to_response(task).model_dump()
                    # Convert datetime objects to ISO format strings
                    response_dict["created_at"] = response_dict["created_at"].isoformat()
                    if response_dict.get("started_at"):
                        response_dict["started_at"] = response_dict["started_at"].isoformat()
                    if response_dict.get("completed_at"):
                        response_dict["completed_at"] = response_dict["completed_at"].isoformat()
                    yield {"event": event_type, "data": json.dumps(response_dict)}
                    logger.info(f"Sent {event_type} event for task {task_id}")
                    return

                # Send initial state for active tasks
                logger.info(f"Task {task_id} is active, sending initial progress event")
                yield {
                    "event": "progress",
                    "data": json.dumps(
                        {
                            "id": task.id,
                            "status": task.status.lower(),
                            "progress": getattr(task, "progress", 0),
                            "message": getattr(task, "message", None),
                            "result": getattr(task, "result", None),
                            "error": task.error_message,
                        }
                    ),
                }

            # Small delay to prevent rapid-fire events
            await asyncio.sleep(0.5)

            # Poll for updates (check every 1 second)
            last_progress = getattr(task, "progress", 0)
            last_status = task.status
            retry_count = 0
            max_retries = 3  # Allow 3 consecutive DB errors before giving up

            logger.info(
                f"Starting polling loop for task {task_id}: initial status={last_status}, initial progress={last_progress}"
            )

            poll_iteration = 0
            while True:
                poll_iteration += 1
                logger.info(f"Polling iteration {poll_iteration} for task {task_id}")
                try:
                    # Refresh task from database - use fresh session each time
                    async with async_session_factory() as session:
                        result = await session.execute(
                            select(DBTaskLog).where(DBTaskLog.id == task_id)
                        )
                        task = result.scalar_one_or_none()

                        if not task:
                            yield {
                                "event": "error",
                                "data": json.dumps({"error": "Task disappeared from database"}),
                            }
                            return

                        current_progress = getattr(task, "progress", 0)
                        current_status = task.status

                        logger.info(
                            f"Polling task {task_id}: status={current_status}, progress={current_progress}, last_status={last_status}, last_progress={last_progress}"
                        )

                        # Send progress update if changed
                        if current_progress != last_progress or current_status != last_status:
                            logger.info(
                                f"Task {task_id} status changed: {last_status}→{current_status}, progress: {last_progress}→{current_progress}"
                            )
                            yield {
                                "event": "progress",
                                "data": json.dumps(
                                    {
                                        "id": task.id,
                                        "status": current_status.lower(),
                                        "progress": current_progress,
                                        "message": getattr(task, "message", None),
                                        "result": getattr(task, "result", None),
                                        "error": task.error_message,
                                    }
                                ),
                            }
                            last_progress = current_progress
                            last_status = current_status

                        # Check for terminal states
                        if current_status == "COMPLETED":
                            response_dict = task_to_response(task).model_dump()
                            response_dict["created_at"] = response_dict["created_at"].isoformat()
                            if response_dict.get("started_at"):
                                response_dict["started_at"] = response_dict[
                                    "started_at"
                                ].isoformat()
                            if response_dict.get("completed_at"):
                                response_dict["completed_at"] = response_dict[
                                    "completed_at"
                                ].isoformat()
                            yield {"event": "completed", "data": json.dumps(response_dict)}
                            logger.info(f"SSE stream completed for task {task_id}")
                            return

                        if current_status == "FAILED":
                            response_dict = task_to_response(task).model_dump()
                            response_dict["created_at"] = response_dict["created_at"].isoformat()
                            if response_dict.get("started_at"):
                                response_dict["started_at"] = response_dict[
                                    "started_at"
                                ].isoformat()
                            if response_dict.get("completed_at"):
                                response_dict["completed_at"] = response_dict[
                                    "completed_at"
                                ].isoformat()
                            yield {"event": "failed", "data": json.dumps(response_dict)}
                            logger.info(f"SSE stream failed for task {task_id}")
                            return

                    # Reset retry count on success
                    retry_count = 0

                    # Wait before next poll (1 second)
                    await asyncio.sleep(1)

                except Exception as e:
                    retry_count += 1
                    logger.error(f"Error in SSE stream for task {task_id}: {e}")

                    if retry_count >= max_retries:
                        yield {
                            "event": "error",
                            "data": json.dumps({"error": "Stream error", "message": str(e)}),
                        }
                        return

                    # Wait before retry (2 seconds)
                    await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Exception in event generator for task {task_id}: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": json.dumps({"error": "Internal server error", "message": str(e)}),
            }

    logger.info(f"Creating EventSourceResponse for task {task_id}")
    return EventSourceResponse(event_generator())


# --- Dynamic Routes (must be last to avoid conflicts) ---


@router.get("/{task_id}", response_model=TaskLogResponse)
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single task by ID."""
    result = await db.execute(select(DBTaskLog).where(DBTaskLog.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task_to_response(task)


@router.post("/{task_id}/cancel")
async def cancel_task_endpoint(
    task_id: str,
    container: DIContainer = Depends(get_di_container),
):
    """Cancel a task (alias for stop)."""
    # Reuse the stop logic
    return await stop_task_endpoint(task_id, container)
