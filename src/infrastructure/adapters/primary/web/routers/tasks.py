"""Task management API routes."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, case, desc, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from src.application.services.auth_service_v2 import AuthService
from src.application.use_cases.task import (
    GetTaskQuery,
    UpdateTaskCommand,
)
from src.configuration.di_container import DIContainer
from src.domain.model.task.task_log import TaskLog, TaskLogStatus
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_workflow_engine,
)
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_api_key_from_header_or_query,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory, get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    Project,
    TaskLog as DBTaskLog,
    User,
    UserProject,
)
from src.infrastructure.adapters.secondary.persistence.sql_api_key_repository import (
    SqlAPIKeyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_user_repository import SqlUserRepository
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

_RETRYABLE_WORKFLOWS = {
    "add_episode": "episode_processing",
    "incremental_refresh": "incremental_refresh",
    "rebuild_communities": "rebuild_communities",
}
_UNRETRYABLE_RETRY_MESSAGE = "Retry skipped: unrecoverable task"


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
    result: dict[str, Any] | None = None
    message: str | None = None


class RecentTasksResponse(BaseModel):
    tasks: list[TaskLogResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class QueueDepthPoint(BaseModel):
    timestamp: str
    depth: int


class RetryPendingResponse(BaseModel):
    submitted: int
    skipped: int
    limit: int
    task_ids: list[str]


@dataclass(frozen=True)
class TaskAccessPrincipal:
    id: str
    is_superuser: bool = False


# --- FastAPI Dependencies ---


async def get_di_container(db: AsyncSession = Depends(get_db)) -> DIContainer:
    """Get DI container with use cases"""
    return DIContainer(db)


async def get_task_stream_principal(api_key: str) -> TaskAccessPrincipal:
    """Resolve a stream caller without holding a DB session for the SSE lifetime."""
    async with async_session_factory() as session:
        auth_service = AuthService(
            user_repository=SqlUserRepository(session),
            api_key_repository=SqlAPIKeyRepository(session),
        )
        try:
            domain_api_key = await auth_service.verify_api_key_read_only(api_key)
            if domain_api_key is None:
                raise ValueError("Invalid API key")
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=_("Invalid API key"),
            ) from exc

        result = await session.execute(
            refresh_select_statement(select(User).where(User.id == domain_api_key.user_id))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("User not found"))
        await session.commit()
        return TaskAccessPrincipal(id=user.id, is_superuser=bool(user.is_superuser))


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


def _db_task_to_domain(task: DBTaskLog) -> TaskLog:
    return TaskLog(
        id=task.id,
        group_id=task.group_id,
        task_type=task.task_type,
        status=TaskLogStatus(task.status),
        payload=task.payload,
        entity_id=task.entity_id,
        entity_type=task.entity_type,
        parent_task_id=task.parent_task_id,
        worker_id=task.worker_id,
        retry_count=task.retry_count,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        stopped_at=task.stopped_at,
    )


def _is_superuser(current_user: Any) -> bool:
    return bool(getattr(current_user, "is_superuser", False))


async def _task_access_project_ids(
    db: AsyncSession,
    current_user: Any,
) -> list[str] | None:
    """Return allowed project ids, or None when the caller may see all tasks."""
    if _is_superuser(current_user):
        return None

    result = await db.execute(
        refresh_select_statement(
            select(UserProject.project_id).where(UserProject.user_id == current_user.id)
        )
    )
    return list(result.scalars().all())


def _task_project_scope_filter(project_ids: list[str] | None) -> Any | None:
    if project_ids is None:
        return None
    if not project_ids:
        return false()
    return or_(
        DBTaskLog.group_id.in_(project_ids),
        DBTaskLog.payload["project_id"].as_string().in_(project_ids),
        DBTaskLog.payload["group_id"].as_string().in_(project_ids),
        DBTaskLog.payload["task_group_id"].as_string().in_(project_ids),
    )


def _apply_task_scope(statement: Any, scope_filter: Any | None) -> Any:
    if scope_filter is None:
        return statement
    return statement.where(scope_filter)


def _task_project_id(task: Any) -> str | None:
    payload = getattr(task, "payload", None)
    if isinstance(payload, dict):
        payload_dict = cast(dict[str, Any], payload)
        for key in ("project_id", "group_id", "task_group_id"):
            value = payload_dict.get(key)
            if isinstance(value, str) and value:
                return value

    group_id = getattr(task, "group_id", None)
    return group_id if isinstance(group_id, str) and group_id else None


async def _ensure_task_access(db: AsyncSession, current_user: Any, task: Any) -> None:
    if _is_superuser(current_user):
        return

    project_id = _task_project_id(task)
    if project_id is None:
        raise HTTPException(status_code=403, detail=_("Access denied to task"))

    result = await db.execute(
        refresh_select_statement(
            select(UserProject.id)
            .where(
                and_(
                    UserProject.user_id == current_user.id,
                    UserProject.project_id == project_id,
                )
            )
            .limit(1)
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail=_("Access denied to task"))


# --- Endpoints ---

# NOTE: Dynamic routes with path parameters must be defined AFTER specific routes
# to avoid route matching conflicts (e.g., "/stats" should match before "/{task_id}")


@router.get("/stats", response_model=TaskStatsResponse)
async def get_task_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskStatsResponse:
    """Get task statistics."""
    now = datetime.now(UTC)
    one_day_ago = now - timedelta(days=1)
    one_hour_ago = now - timedelta(hours=1)
    scope_filter = _task_project_scope_filter(await _task_access_project_ids(db, current_user))

    stats_query = select(
        func.count(DBTaskLog.id).label("total"),
        func.coalesce(
            func.sum(case((DBTaskLog.status == "COMPLETED", 1), else_=0)),
            0,
        ).label("completed"),
        func.coalesce(
            func.sum(case((DBTaskLog.status == "FAILED", 1), else_=0)),
            0,
        ).label("failed"),
        func.coalesce(
            func.sum(case((DBTaskLog.status == "PENDING", 1), else_=0)),
            0,
        ).label("pending"),
        func.coalesce(
            func.sum(case((DBTaskLog.status == "PROCESSING", 1), else_=0)),
            0,
        ).label("processing"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            DBTaskLog.status == "COMPLETED",
                            DBTaskLog.completed_at >= one_hour_ago,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("completed_1h"),
        func.coalesce(
            func.sum(case((DBTaskLog.created_at >= one_day_ago, 1), else_=0)),
            0,
        ).label("total_24h"),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(DBTaskLog.status == "FAILED", DBTaskLog.created_at >= one_day_ago),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("failed_24h"),
    )
    stats = (
        await db.execute(refresh_select_statement(_apply_task_scope(stats_query, scope_filter)))
    ).one()

    total = int(stats.total or 0)
    completed = int(stats.completed or 0)
    failed = int(stats.failed or 0)
    pending = int(stats.pending or 0)
    processing = int(stats.processing or 0)
    completed_1h = int(stats.completed_1h or 0)
    throughput = completed_1h / 60
    total_24h = int(stats.total_24h or 0)
    failed_24h = int(stats.failed_24h or 0)
    error_rate = (failed_24h / total_24h * 100) if total_24h > 0 else 0.0

    return TaskStatsResponse(
        total=total,
        pending=pending,
        processing=processing,
        completed=completed,
        failed=failed,
        throughput_per_minute=throughput,
        error_rate=error_rate,
    )


@router.get("/queue-depth", response_model=list[QueueDepthPoint])
async def get_queue_depth(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get queue depth over time."""
    now = datetime.now(UTC)
    points: list[QueueDepthPoint] = []
    scope_filter = _task_project_scope_filter(await _task_access_project_ids(db, current_user))

    # Generate points every 3 hours for the last 24 hours
    times: list[datetime] = []
    for i in range(8, -1, -1):
        t = now - timedelta(hours=i * 3)
        times.append(t)

    depth_columns: list[Any] = []
    for index, t in enumerate(times):
        depth_columns.append(
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                DBTaskLog.created_at <= t,
                                or_(
                                    DBTaskLog.completed_at > t,
                                    DBTaskLog.completed_at.is_(None),
                                ),
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label(f"depth_{index}")
        )

    depth_row = (
        await db.execute(
            refresh_select_statement(_apply_task_scope(select(*depth_columns), scope_filter))
        )
    ).one()

    for index, t in enumerate(times):
        count = int(getattr(depth_row, f"depth_{index}") or 0)
        points.append(QueueDepthPoint(timestamp=t.strftime("%H:%M"), depth=count))

    return points


@router.get("/recent", response_model=RecentTasksResponse)
async def get_recent_tasks(
    status: str | None = None,
    task_type: str | None = None,
    search: str | None = None,
    entity_id: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get recent tasks with filtering."""
    # For complex queries with multiple filters, use direct DB access
    # In a full refactoring, this would move to a use case with filter objects
    scope_filter = _task_project_scope_filter(await _task_access_project_ids(db, current_user))
    conditions: list[Any] = []

    if status and status != "All Statuses":
        conditions.append(DBTaskLog.status == status.upper())

    if task_type and task_type != "All Types":
        conditions.append(DBTaskLog.task_type == task_type)

    if entity_id:
        conditions.append(DBTaskLog.entity_id == entity_id)

    if entity_type:
        conditions.append(DBTaskLog.entity_type == entity_type)

    if search:
        conditions.append(
            (DBTaskLog.id.ilike(f"%{search}%")) | (DBTaskLog.worker_id.ilike(f"%{search}%"))
        )

    total_query = _apply_task_scope(
        select(func.count(DBTaskLog.id)).where(*conditions),
        scope_filter,
    )
    total = await db.scalar(refresh_select_statement(total_query)) or 0

    query = _apply_task_scope(
        select(DBTaskLog)
        .where(*conditions)
        .order_by(desc(DBTaskLog.created_at), DBTaskLog.id.asc())
        .limit(limit)
        .offset(offset),
        scope_filter,
    )

    result = await db.execute(refresh_select_statement(query))
    db_tasks = result.scalars().all()
    tasks = [task_to_response(_db_task_to_domain(task)) for task in db_tasks]

    return RecentTasksResponse(
        tasks=tasks,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(tasks) < total,
    )


@router.get("/status-breakdown")
async def get_status_breakdown(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get task status breakdown."""
    query = select(DBTaskLog.status, func.count(DBTaskLog.id)).group_by(DBTaskLog.status)
    scope_filter = _task_project_scope_filter(await _task_access_project_ids(db, current_user))
    query = _apply_task_scope(query, scope_filter)

    result = await db.execute(refresh_select_statement(query))
    breakdown = {row[0]: row[1] for row in result.all()}

    return {
        "Completed": breakdown.get("COMPLETED", 0),
        "Processing": breakdown.get("PROCESSING", 0),
        "Failed": breakdown.get("FAILED", 0),
        "Pending": breakdown.get("PENDING", 0),
    }


def _retry_payload_for_task(task: DBTaskLog) -> tuple[str, dict[str, Any]]:
    workflow_name = _RETRYABLE_WORKFLOWS.get(task.task_type)
    if workflow_name is None:
        raise HTTPException(
            status_code=400,
            detail=_("Task type cannot be retried from the task dashboard"),
        )

    payload = dict(task.payload or {})
    if task.task_type == "add_episode":
        if not isinstance(payload.get("uuid"), str) or not isinstance(payload.get("content"), str):
            raise HTTPException(
                status_code=400,
                detail=_("Task payload is missing episode processing data"),
            )
    elif task.task_type == "incremental_refresh":
        payload.setdefault("group_id", task.group_id)
    elif task.task_type == "rebuild_communities":
        payload.setdefault("task_group_id", task.group_id)
        payload.setdefault("project_id", payload.get("task_group_id") or task.group_id)

    payload["task_id"] = task.id
    return workflow_name, payload


def _reset_task_for_retry(task: DBTaskLog, payload: dict[str, Any]) -> None:
    task.payload = payload
    task.status = "PENDING"
    task.error_message = None
    task.started_at = None
    task.completed_at = None
    task.stopped_at = None
    task.progress = 0
    task.message = "Queued for retry"
    task.retry_count += 1


async def _project_exists(db: AsyncSession, project_id: str) -> bool:
    result = await db.execute(
        refresh_select_statement(select(Project.id).where(Project.id == project_id).limit(1))
    )
    return result.scalar_one_or_none() is not None


def _payload_project_id(task: DBTaskLog, payload: dict[str, Any]) -> str | None:
    value = payload.get("project_id") or payload.get("group_id") or task.group_id
    return value if isinstance(value, str) and value else None


async def _retry_blocker_for_task(
    db: AsyncSession,
    task: DBTaskLog,
    payload: dict[str, Any],
) -> str | None:
    project_id = _payload_project_id(task, payload)
    if project_id and not await _project_exists(db, project_id):
        return f"Project {project_id} no longer exists; task cannot be retried"
    return None


def _mark_task_unretryable(task: DBTaskLog, reason: str) -> None:
    task.status = "FAILED"
    task.error_message = reason
    task.completed_at = datetime.now(UTC)
    task.progress = 100
    task.message = _UNRETRYABLE_RETRY_MESSAGE


def _task_payload_for_memory(memory: Memory, project: Project, task_id: str) -> dict[str, Any]:
    """Build the episode-processing payload for an orphaned pending memory."""
    return {
        "group_id": memory.project_id,
        "name": memory.title or str(memory.id),
        "content": memory.content,
        "source_description": "Historical memory retry",
        "episode_type": memory.content_type or "text",
        "entity_types": None,
        "uuid": memory.id,
        "tenant_id": project.tenant_id,
        "project_id": memory.project_id,
        "user_id": str(memory.author_id),
        "memory_id": memory.id,
        "task_id": task_id,
    }


def _create_task_for_memory_retry(
    memory: Memory,
    project: Project,
    now: datetime,
) -> tuple[DBTaskLog, dict[str, Any]]:
    task_id = str(uuid4())
    payload = _task_payload_for_memory(memory, project, task_id)
    task = DBTaskLog(
        id=task_id,
        group_id=memory.project_id,
        task_type="add_episode",
        status="PENDING",
        payload=payload,
        entity_id=memory.id,
        entity_type="episode",
        progress=0,
        message="Queued historical memory for graph processing",
        created_at=now,
    )
    memory.task_id = task_id
    memory.processing_status = "PENDING"
    memory.updated_at = now
    return task, payload


async def _prepare_orphan_memory_retries(
    db: AsyncSession,
    limit: int,
    allowed_project_ids: list[str] | None,
) -> list[tuple[DBTaskLog, str, dict[str, Any]]]:
    if limit <= 0:
        return []
    if allowed_project_ids == []:
        return []

    query = (
        select(Memory, Project)
        .join(Project, Project.id == Memory.project_id)
        .where(
            Memory.processing_status == "PENDING",
            Memory.task_id.is_(None),
        )
        .order_by(desc(Memory.created_at))
        .limit(limit)
    )
    if allowed_project_ids is not None:
        query = query.where(Memory.project_id.in_(allowed_project_ids))

    result = await db.execute(refresh_select_statement(query))

    now = datetime.now(UTC)
    prepared: list[tuple[DBTaskLog, str, dict[str, Any]]] = []
    for memory, project in result.all():
        task, payload = _create_task_for_memory_retry(memory, project, now)
        db.add(task)
        prepared.append((task, "episode_processing", payload))
    return prepared


async def _start_retry_workflow(
    *,
    task: DBTaskLog,
    workflow_name: str,
    payload: dict[str, Any],
    workflow_engine: WorkflowEnginePort,
) -> None:
    workflow_id = f"{workflow_name.replace('_', '-')}-retry-{task.id}"
    _workflow_result = await workflow_engine.start_workflow(
        workflow_name=workflow_name,
        workflow_id=workflow_id,
        input_data=payload,
        task_queue="default",
    )
    del _workflow_result


async def _mark_retry_start_failed(db: AsyncSession, task: DBTaskLog, exc: Exception) -> None:
    task.status = "FAILED"
    task.error_message = str(exc)
    task.completed_at = datetime.now(UTC)
    task.progress = 100
    task.message = "Retry failed to start"
    await db.commit()


@router.post("/retry-pending", response_model=RetryPendingResponse)
async def retry_pending_tasks_endpoint(
    limit: int = Query(10, ge=1, le=10),
    task_type: str | None = Query(None),
    include_failed: bool = Query(False),
    include_stale_processing: bool = Query(False),
    stale_after_minutes: int = Query(15, ge=1, le=1440),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> RetryPendingResponse:
    """Resume a bounded batch of stale pending tasks from the dashboard."""
    include_failed = include_failed is True
    include_stale_processing = include_stale_processing is True
    raw_stale_after_minutes: Any = stale_after_minutes
    if not isinstance(raw_stale_after_minutes, int):
        raw_stale_after_minutes = 15
    stale_after_minutes = raw_stale_after_minutes

    retryable_types = set(_RETRYABLE_WORKFLOWS)
    if task_type:
        if task_type not in retryable_types:
            raise HTTPException(
                status_code=400,
                detail=_("Task type cannot be retried from the task dashboard"),
            )
        retryable_types = {task_type}
    status_filter = DBTaskLog.status == "PENDING"
    if include_failed:
        status_filter = or_(
            DBTaskLog.status == "PENDING",
            and_(
                DBTaskLog.status == "FAILED",
                or_(
                    DBTaskLog.message.is_(None),
                    DBTaskLog.message != _UNRETRYABLE_RETRY_MESSAGE,
                ),
            ),
        )
    if include_stale_processing:
        stale_before = datetime.now(UTC) - timedelta(minutes=stale_after_minutes)
        stale_processing_filter = and_(
            DBTaskLog.status == "PROCESSING",
            DBTaskLog.started_at.is_not(None),
            DBTaskLog.started_at < stale_before,
        )
        status_filter = or_(status_filter, stale_processing_filter)

    allowed_project_ids = await _task_access_project_ids(db, current_user)
    scope_filter = _task_project_scope_filter(allowed_project_ids)
    query = (
        select(DBTaskLog)
        .where(
            status_filter,
            DBTaskLog.task_type.in_(retryable_types),
        )
        .order_by(desc(DBTaskLog.created_at))
        .limit(limit)
    )
    query = _apply_task_scope(query, scope_filter)

    result = await db.execute(refresh_select_statement(query))
    tasks = list(result.scalars().all())

    prepared: list[tuple[DBTaskLog, str, dict[str, Any]]] = []
    skipped = 0
    for task in tasks:
        try:
            workflow_name, payload = _retry_payload_for_task(task)
        except HTTPException:
            skipped += 1
            continue
        blocker = await _retry_blocker_for_task(db, task, payload)
        if blocker:
            _mark_task_unretryable(task, blocker)
            skipped += 1
            continue
        _reset_task_for_retry(task, payload)
        prepared.append((task, workflow_name, payload))

    remaining_limit = limit - len(prepared)
    if (task_type is None or task_type == "add_episode") and remaining_limit > 0:
        prepared.extend(
            await _prepare_orphan_memory_retries(db, remaining_limit, allowed_project_ids)
        )

    await db.commit()

    submitted_ids: list[str] = []
    for task, workflow_name, payload in prepared:
        try:
            await _start_retry_workflow(
                task=task,
                workflow_name=workflow_name,
                payload=payload,
                workflow_engine=workflow_engine,
            )
            submitted_ids.append(task.id)
        except Exception as exc:
            await _mark_retry_start_failed(db, task, exc)
            skipped += 1

    return RetryPendingResponse(
        submitted=len(submitted_ids),
        skipped=skipped,
        limit=limit,
        task_ids=submitted_ids,
    )


@router.post("/{task_id}/retry")
async def retry_task_endpoint(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    workflow_engine: WorkflowEnginePort = Depends(get_workflow_engine),
) -> dict[str, Any]:
    """Retry or resume a restartable background task."""
    result = await db.execute(
        refresh_select_statement(select(DBTaskLog).where(DBTaskLog.id == task_id))
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail=_("Task not found"))

    await _ensure_task_access(db, current_user, task)

    if task.status not in {"FAILED", "PENDING", "STOPPED"}:
        raise HTTPException(
            status_code=400,
            detail=_("Task can only be retried if failed, stopped, or pending"),
        )

    workflow_name, payload = _retry_payload_for_task(task)
    blocker = await _retry_blocker_for_task(db, task, payload)
    if blocker:
        _mark_task_unretryable(task, blocker)
        await db.commit()
        raise HTTPException(
            status_code=400,
            detail=_("Task project no longer exists; task cannot be retried"),
        )

    _reset_task_for_retry(task, payload)
    await db.commit()

    try:
        await _start_retry_workflow(
            task=task,
            workflow_name=workflow_name,
            payload=payload,
            workflow_engine=workflow_engine,
        )
    except Exception as exc:
        await _mark_retry_start_failed(db, task, exc)
        raise HTTPException(status_code=500, detail=_("Failed to restart task")) from exc

    return {"message": "Task retry submitted", "task_id": task.id}


@router.post("/{task_id}/stop")
async def stop_task_endpoint(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container: DIContainer = Depends(get_di_container),
) -> dict[str, Any]:
    """Stop a running task."""
    get_use_case = container.get_task_use_case()
    update_use_case = container.update_task_use_case()

    # Get the task first
    task = await get_use_case.execute(refresh_select_statement(GetTaskQuery(task_id=task_id)))

    if not task:
        raise HTTPException(status_code=404, detail=_("Task not found"))

    await _ensure_task_access(db, current_user, task)

    if task.status not in ["PENDING", "PROCESSING"]:
        raise HTTPException(
            status_code=400, detail=_("Task can only be stopped if pending or processing")
        )

    # Mark task as stopped
    now = datetime.now(UTC)
    _update_result = await update_use_case.execute(
        refresh_select_statement(
            UpdateTaskCommand(
                task_id=task_id,
                status="FAILED",
                error_message="Task stopped by user",
                completed_at=now,
                stopped_at=now,
            )
        )
    )
    del _update_result
    await db.commit()

    return {"message": "Task marked as stopped"}


def _serialize_task_response_dict(task: Any) -> dict[str, Any]:
    """Convert task to a JSON-serializable dict with ISO datetime strings."""
    response_dict = task_to_response(task).model_dump()
    response_dict["created_at"] = response_dict["created_at"].isoformat()
    if response_dict.get("started_at"):
        response_dict["started_at"] = response_dict["started_at"].isoformat()
    if response_dict.get("completed_at"):
        response_dict["completed_at"] = response_dict["completed_at"].isoformat()
    return response_dict


def _build_progress_event(task: Any) -> dict[str, Any]:
    """Build a progress SSE event dict from a task."""
    return {
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


async def _poll_task_updates(
    task_id: str,
    last_progress: int,
    last_status: str,
    retry_sleep_seconds: float = 2.0,
    poll_sleep_seconds: float = 1.0,
) -> AsyncGenerator[dict[str, Any], None]:
    """Poll database for task updates, yielding SSE events on changes."""
    retry_count = 0
    max_retries = 3
    poll_iteration = 0

    while True:
        poll_iteration += 1
        logger.info(f"Polling iteration {poll_iteration} for task {task_id}")
        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    refresh_select_statement(select(DBTaskLog).where(DBTaskLog.id == task_id))
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
                    "Polling task %s: status=%s, progress=%s, last_status=%s, last_progress=%s",
                    task_id,
                    current_status,
                    current_progress,
                    last_status,
                    last_progress,
                )

                if current_progress != last_progress or current_status != last_status:
                    logger.info(
                        "Task %s status changed: %s->%s, progress: %s->%s",
                        task_id,
                        last_status,
                        current_status,
                        last_progress,
                        current_progress,
                    )
                    yield _build_progress_event(task)
                    last_progress = current_progress
                    last_status = current_status

                if current_status in ("COMPLETED", "FAILED"):
                    event_type = "completed" if current_status == "COMPLETED" else "failed"
                    yield {
                        "event": event_type,
                        "data": json.dumps(_serialize_task_response_dict(task)),
                    }
                    logger.info(f"SSE stream {event_type} for task {task_id}")
                    return

            retry_count = 0
            await asyncio.sleep(poll_sleep_seconds)

        except Exception:
            retry_count += 1
            logger.exception("Error in SSE stream for task %s", task_id)

            if retry_count >= max_retries:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {
                            "error": "Stream error",
                            "message": _("Task stream failed"),
                        }
                    ),
                }
                return

            await asyncio.sleep(retry_sleep_seconds)


@router.get("/{task_id}/stream", response_class=EventSourceResponse, response_model=None)
async def stream_task_status(
    task_id: str,
    api_key: str = Depends(get_api_key_from_header_or_query),
) -> EventSourceResponse:
    """Stream task status updates using Server-Sent Events (SSE).

    This endpoint deliberately does NOT take a request-scoped
    ``Depends(get_db)`` session: the SSE stream holds the response open for
    the lifetime of the task, and a request-scoped session would pin one
    DB connection from the pool for the same duration. Inside the generator
    we open a short-lived ``async_session_factory()`` for the initial
    snapshot read; the polling loop talks to its own session via
    ``_poll_task_updates``.

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
    principal = await get_task_stream_principal(api_key)

    async with async_session_factory() as session:
        result = await session.execute(
            refresh_select_statement(select(DBTaskLog).where(DBTaskLog.id == task_id))
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail=_("Task not found"))
        await _ensure_task_access(session, principal, task)

    async def event_generator() -> AsyncGenerator[Any, None]:
        """Generate SSE events for task status updates."""
        logger.info(f"Event generator started for task {task_id}")

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    refresh_select_statement(select(DBTaskLog).where(DBTaskLog.id == task_id))
                )
                task = result.scalar_one_or_none()

                if not task:
                    logger.error(f"Task {task_id} not found in database")
                    yield {"event": "error", "data": json.dumps({"error": "Task not found"})}
                    return

                logger.info(f"Task {task_id} found with status: {task.status}")
                # If task is already in a final state, send final event directly
                if task.status in (TaskLogStatus.COMPLETED, TaskLogStatus.FAILED):
                    event_type = "completed" if task.status == TaskLogStatus.COMPLETED else "failed"
                    logger.info(f"Task {task_id} already in final state: {task.status}")
                    yield {
                        "event": event_type,
                        "data": json.dumps(_serialize_task_response_dict(task)),
                    }
                    return
                # Send initial state for active tasks
                logger.info(f"Task {task_id} is active, sending initial progress event")
                yield _build_progress_event(task)

            await asyncio.sleep(0.5)
            last_progress = getattr(task, "progress", 0)
            last_status = task.status
            logger.info(
                "Starting polling loop for task %s: initial status=%s, initial progress=%s",
                task_id,
                last_status,
                last_progress,
            )

            async for event in _poll_task_updates(task_id, last_progress, last_status):
                yield event

        except Exception as e:
            logger.exception(
                "Exception in event generator for task %s",
                task_id,
            )
            del e  # avoid leaking via locals
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "error": "Internal server error",
                        "task_id": task_id,
                    }
                ),
            }

    logger.info(f"Creating EventSourceResponse for task {task_id}")
    return EventSourceResponse(event_generator())


# --- Dynamic Routes (must be last to avoid conflicts) ---


@router.get("/{task_id}", response_model=TaskLogResponse)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get a single task by ID."""
    result = await db.execute(
        refresh_select_statement(select(DBTaskLog).where(DBTaskLog.id == task_id))
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail=_("Task not found"))

    await _ensure_task_access(db, current_user, task)

    return task_to_response(
        TaskLog(
            id=task.id,
            group_id=task.group_id,
            task_type=task.task_type,
            status=TaskLogStatus(task.status),
            payload=task.payload,
            entity_id=task.entity_id,
            entity_type=task.entity_type,
            parent_task_id=task.parent_task_id,
            worker_id=task.worker_id,
            retry_count=task.retry_count,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
            stopped_at=task.stopped_at,
        )
    )


@router.post("/{task_id}/cancel")
async def cancel_task_endpoint(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container: DIContainer = Depends(get_di_container),
) -> Any:
    """Cancel a task (alias for stop)."""
    # Reuse the stop logic
    return await stop_task_endpoint(task_id, current_user, db, container)
