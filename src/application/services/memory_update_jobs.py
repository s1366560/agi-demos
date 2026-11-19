"""Durable memory-update indexing jobs.

The saved memory row and its TaskLog are written in the caller's transaction.
A later worker performs extraction and chunk indexing. Restart recovery reads
the same TaskLog rows; nothing here depends on an in-process task surviving.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.memory.processing import MemoryProcessingSource
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.memory_processing import (
    update_memory_processing_status,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory as DBMemory, TaskLog

logger = logging.getLogger(__name__)

MEMORY_UPDATE_JOB = "memory_update_index"
MAX_ATTEMPTS = 3
_RUNNABLE = ("PENDING", "PROCESSING")

Extract = Callable[[dict[str, Any]], Awaitable[None]]
Index = Callable[[dict[str, Any]], Awaitable[None]]


class MemoryUpdateJobError(RuntimeError):
    """The saved row could not be paired with a durable indexing job."""


async def stage_memory_update_job(
    session: AsyncSession,
    *,
    memory_id: str,
    project_id: str,
    tenant_id: str,
    user_id: str,
    content_changed: bool,
    revision: int,
    content: str,
    title: str,
    tags: list[str],
    category: str,
) -> str:
    """Insert the indexing job and mark the memory pending. The caller commits."""
    from sqlalchemy import update

    task_id = str(uuid4())
    payload = {
        "task_type": MEMORY_UPDATE_JOB,
        "task_id": task_id,
        "memory_id": memory_id,
        "project_id": project_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "source_revision": revision,
        "content": content,
        "title": title,
        "tags": list(tags),
        "category": category,
        "content_changed": content_changed,
    }
    session.add(
        TaskLog(
            id=task_id,
            group_id=project_id,
            task_type=MEMORY_UPDATE_JOB,
            status="PENDING",
            payload=payload,
            entity_id=memory_id,
            entity_type="memory",
            retry_count=0,
            created_at=datetime.now(UTC),
        )
    )
    result = await session.execute(
        update(DBMemory)
        .where(DBMemory.id == memory_id, DBMemory.project_id == project_id)
        .values(processing_status="PENDING", task_id=task_id)
        .returning(DBMemory.id)
    )
    if result.scalar_one_or_none() is None:
        raise MemoryUpdateJobError("memory_update_job_not_staged")
    await session.flush()
    return task_id


def _source(payload: dict[str, Any]) -> MemoryProcessingSource | None:
    return MemoryProcessingSource.from_payload(payload)


async def _claim_job(
    session_factory: Callable[[], AsyncSession],
    task_id: str,
    stage_timeout_s: float | None,
) -> tuple[str, dict[str, Any]] | str:
    """Take a lease. A live PROCESSING claim is not stolen before it expires."""
    now = datetime.now(UTC)
    worker_id = str(uuid4())
    claimable = [
        TaskLog.status == "PENDING",
        and_(TaskLog.status == "FAILED", TaskLog.retry_count < MAX_ATTEMPTS),
    ]
    if stage_timeout_s is not None and stage_timeout_s > 0:
        claimable.append(
            and_(
                TaskLog.status == "PROCESSING",
                or_(
                    TaskLog.started_at.is_(None),
                    TaskLog.started_at < now - timedelta(seconds=stage_timeout_s),
                ),
            )
        )
    session = session_factory()
    try:
        claimed = await session.execute(
            update(TaskLog)
            .where(
                TaskLog.id == task_id,
                TaskLog.task_type == MEMORY_UPDATE_JOB,
                or_(*claimable),
            )
            .values(status="PROCESSING", worker_id=worker_id, started_at=now)
            .returning(TaskLog.payload)
        )
        payload = claimed.scalar_one_or_none()
        if payload is not None:
            await session.commit()
            return worker_id, dict(payload or {})
        found = (
            await session.execute(
                refresh_select_statement(
                    select(TaskLog.task_type, TaskLog.status, TaskLog.retry_count).where(
                        TaskLog.id == task_id
                    )
                )
            )
        ).one_or_none()
        await session.rollback()
        if found is None or found.task_type != MEMORY_UPDATE_JOB:
            return "missing"
        if found.status == "COMPLETED":
            return "already_completed"
        if found.status == "FAILED" and int(found.retry_count or 0) >= MAX_ATTEMPTS:
            return "retries_exhausted"
        if found.status == "PROCESSING":
            return "in_progress"
        return "not_runnable"
    finally:
        await session.close()


def _owns_claim(task: TaskLog, worker_id: str) -> bool:
    return task.worker_id == worker_id


async def execute_memory_update_job(  # noqa: C901
    session_factory: Callable[[], AsyncSession],
    task_id: str,
    *,
    extract: Extract,
    index: Index,
    stage_timeout_s: float | None = None,
) -> str:
    """Run one durable job. Returns a terminal outcome name.

    ``stage_timeout_s`` reuses the caller-supplied budget, normally the
    configured LLM timeout. ``None`` waits until the stage finishes.
    """
    claimed = await _claim_job(session_factory, task_id, stage_timeout_s)
    if isinstance(claimed, str):
        return claimed
    worker_id, payload = claimed

    stages: dict[str, str] = {}
    try:
        if payload.get("content_changed") is True:
            try:
                await _run_stage(extract, payload, stage_timeout_s)
                stages["extraction"] = "succeeded"
            except GraphNotReady:
                await _defer_until_ready(session_factory, task_id, worker_id)
                return "not_ready"
            except ExtractionQueued:
                stages["extraction"] = "queued"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                stages["extraction"] = type(exc).__name__
        try:
            await _run_stage(index, payload, stage_timeout_s)
            stages["index"] = "succeeded"
        except GraphNotReady:
            await _defer_until_ready(session_factory, task_id, worker_id)
            return "not_ready"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stages["index"] = type(exc).__name__
    except asyncio.CancelledError:
        await _record_attempt(
            session_factory,
            task_id,
            error="cancelled",
            failed=False,
            stages=stages,
            worker_id=worker_id,
        )
        raise

    if stages.get("extraction") == "queued" and stages.get("index") == "succeeded":
        await _record_queue_handoff(session_factory, task_id, stages, worker_id)
        return "queued"
    if stages.get("extraction") not in {None, "succeeded"} or stages.get("index") != "succeeded":
        failed_stage = (
            "extraction" if stages.get("extraction") not in {None, "succeeded"} else "index"
        )
        await _record_attempt(
            session_factory,
            task_id,
            error=f"{failed_stage}:{stages.get(failed_stage)}",
            failed=True,
            stages=stages,
            worker_id=worker_id,
        )
        logger.warning("memory_update job failed stage=%s", failed_stage)
        return "failed"

    return await _complete_current(session_factory, task_id, payload, worker_id)


async def resume_memory_update_jobs(
    session_factory: Callable[[], AsyncSession],
    *,
    extract: Extract,
    index: Index,
    limit: int = 20,
    stage_timeout_s: float | None = None,
) -> list[str]:
    """Replay durable jobs left pending or retryable after a worker stop."""
    session = session_factory()
    try:
        rows = (
            await session.scalars(
                select(TaskLog)
                .where(
                    TaskLog.task_type == MEMORY_UPDATE_JOB,
                    or_(
                        TaskLog.status.in_(_RUNNABLE),
                        and_(TaskLog.status == "FAILED", TaskLog.retry_count < MAX_ATTEMPTS),
                    ),
                )
                .order_by(TaskLog.created_at.asc(), TaskLog.id.asc())
                .limit(limit)
            )
        ).all()
        task_ids = [row.id for row in rows if not _handed_to_queue(row)]
    finally:
        await session.close()
    outcomes: list[str] = []
    for task_id in task_ids:
        outcomes.append(
            await execute_memory_update_job(
                session_factory,
                task_id,
                extract=extract,
                index=index,
                stage_timeout_s=stage_timeout_s,
            )
        )
    return outcomes


class GraphNotReady(RuntimeError):
    """The process has no graph or index runtime bound yet."""


class ExtractionQueued(RuntimeError):
    """The graph adapter accepted the episode onto its own queue."""


def _handed_to_queue(row: TaskLog) -> bool:
    raw_result = row.result
    result = raw_result if isinstance(raw_result, dict) else {}
    raw_stages = result.get("stages")
    stages = raw_stages if isinstance(raw_stages, dict) else {}
    return stages.get("extraction") == "queued"


async def _run_stage(func: Extract, payload: dict[str, Any], timeout_s: float | None) -> None:
    if timeout_s is None:
        await func(payload)
        return
    await asyncio.wait_for(func(payload), timeout_s)


async def _defer_until_ready(
    session_factory: Callable[[], AsyncSession],
    task_id: str,
    worker_id: str,
) -> None:
    session = session_factory()
    try:
        task = await session.get(TaskLog, task_id)
        if task is None or task.status == "COMPLETED" or not _owns_claim(task, worker_id):
            return
        task.status = "PENDING"
        task.worker_id = None
        await session.commit()
    finally:
        await session.close()


async def _record_queue_handoff(
    session_factory: Callable[[], AsyncSession],
    task_id: str,
    stages: dict[str, str],
    worker_id: str,
) -> None:
    session = session_factory()
    try:
        task = await session.get(TaskLog, task_id)
        if task is None or task.status == "COMPLETED" or not _owns_claim(task, worker_id):
            return
        task.status = "PENDING"
        task.worker_id = None
        task.error_message = "extraction_queued"
        task.result = {"stages": stages, "completed": False}
        await session.commit()
    finally:
        await session.close()


async def _record_attempt(
    session_factory: Callable[[], AsyncSession],
    task_id: str,
    *,
    error: str,
    failed: bool,
    stages: dict[str, str] | None = None,
    worker_id: str | None = None,
) -> None:
    session = session_factory()
    try:
        task = await session.get(TaskLog, task_id)
        if task is None or task.status == "COMPLETED":
            return
        if worker_id is not None and not _owns_claim(task, worker_id):
            return
        task.worker_id = None
        task.retry_count = int(task.retry_count or 0) + (1 if failed else 0)
        task.error_message = error
        if stages is not None:
            task.result = {"stages": stages, "completed": False}
        exhausted = failed and task.retry_count >= MAX_ATTEMPTS
        task.status = "FAILED" if exhausted else "PENDING"
        if exhausted:
            task.completed_at = datetime.now(UTC)
        payload = dict(task.payload or {})
        source = _source(payload)
        if source is not None and exhausted:
            _ = await update_memory_processing_status(session, source, "FAILED")
            memory = await session.get(DBMemory, source.memory_id)
            if memory is not None and memory.task_id == task_id:
                meta = dict(memory.meta or {})
                meta["index_error"] = error
                memory.meta = meta
        await session.commit()
    finally:
        await session.close()


async def _complete_current(
    session_factory: Callable[[], AsyncSession],
    task_id: str,
    payload: dict[str, Any],
    worker_id: str,
) -> str:
    session = session_factory()
    try:
        task = await session.get(TaskLog, task_id)
        memory = await session.get(DBMemory, str(payload.get("memory_id") or ""))
        source = _source(payload)
        if task is None:
            return "missing"
        if not _owns_claim(task, worker_id):
            return "in_progress"
        if (
            memory is None
            or memory.status != "ENABLED"
            or source is None
            or memory.project_id != source.project_id
            or memory.version != source.revision
            or memory.content != payload.get("content")
            or memory.task_id != task_id
        ):
            task.status = "FAILED"
            task.worker_id = None
            task.error_message = "stale_or_deleted"
            task.completed_at = datetime.now(UTC)
            await session.commit()
            return "stale_or_deleted"
        applied = await update_memory_processing_status(session, source, "COMPLETED")
        if not applied:
            task.status = "FAILED"
            task.worker_id = None
            task.error_message = "stale_or_deleted"
            task.completed_at = datetime.now(UTC)
            await session.commit()
            return "stale_or_deleted"
        task.status = "COMPLETED"
        task.worker_id = None
        task.error_message = None
        task.completed_at = datetime.now(UTC)
        task.progress = 100
        meta = dict(memory.meta or {})
        if "index_error" in meta:
            meta.pop("index_error", None)
            memory.meta = meta
        await session.commit()
        return "completed"
    finally:
        await session.close()
