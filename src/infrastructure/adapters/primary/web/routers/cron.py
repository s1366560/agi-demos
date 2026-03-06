"""Cron job management API routes.

Scoped under ``/api/v1/projects/{project_id}/cron-jobs``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.cron import (
    CronJobCreate,
    CronJobListResponse,
    CronJobResponse,
    CronJobRunListResponse,
    CronJobUpdate,
    ManualRunRequest,
    cron_job_run_to_response,
    cron_job_to_response,
    delivery_config_to_domain,
    payload_config_to_domain,
    schedule_config_to_domain,
)
from src.configuration.di_container import DIContainer
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.database import (
    get_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/cron-jobs",
    tags=["cron-jobs"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _container(db: AsyncSession) -> DIContainer:
    return DIContainer(db)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=CronJobListResponse)
async def list_cron_jobs(
    project_id: str,
    include_disabled: bool = False,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobListResponse:
    """List cron jobs for a project."""
    svc = _container(db).cron_job_service()
    jobs = await svc.list_jobs(
        project_id,
        include_disabled=include_disabled,
        limit=limit,
        offset=offset,
    )
    total = await svc.count_jobs(project_id, include_disabled=include_disabled)
    return CronJobListResponse(
        items=[cron_job_to_response(j) for j in jobs],
        total=total,
    )


@router.post("", response_model=CronJobResponse, status_code=201)
async def create_cron_job(
    project_id: str,
    body: CronJobCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobResponse:
    """Create a new cron job."""
    container = _container(db)
    svc = container.cron_job_service()

    # Resolve tenant_id from the project (User entity has no tenant_id)
    project_svc = container.project_service()
    project = await project_svc.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    job = await svc.create_job(
        project_id=project_id,
        tenant_id=project.tenant_id,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        delete_after_run=body.delete_after_run,
        schedule=schedule_config_to_domain(body.schedule),
        payload=payload_config_to_domain(body.payload),
        delivery=delivery_config_to_domain(body.delivery),
        conversation_mode=body.conversation_mode,
        conversation_id=body.conversation_id,
        timezone=body.timezone,
        stagger_seconds=body.stagger_seconds,
        timeout_seconds=body.timeout_seconds,
        max_retries=body.max_retries,
        created_by=current_user.id,
    )
    await db.commit()
    # Best-effort APScheduler registration
    if job.enabled:
        try:
            from src.infrastructure.scheduler.scheduler_service import register_job

            await register_job(
                job_id=job.id,
                schedule_type=job.schedule.kind.value,
                schedule_config=job.schedule.config,
                timezone=job.timezone,
            )
        except Exception:
            logger.debug("Scheduler not available -- skipping registration for %s", job.id)
    return cron_job_to_response(job)


@router.get("/{job_id}", response_model=CronJobResponse)
async def get_cron_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobResponse:
    """Get a single cron job by ID."""
    svc = _container(db).cron_job_service()
    job = await svc.get_job(job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")
    return cron_job_to_response(job)


@router.patch("/{job_id}", response_model=CronJobResponse)
async def update_cron_job(
    project_id: str,
    job_id: str,
    body: CronJobUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobResponse:
    """Update a cron job (partial)."""
    svc = _container(db).cron_job_service()

    # Verify ownership
    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")

    schedule = schedule_config_to_domain(body.schedule) if body.schedule is not None else None
    payload = payload_config_to_domain(body.payload) if body.payload is not None else None
    delivery = delivery_config_to_domain(body.delivery) if body.delivery is not None else None

    job = await svc.update_job(
        job_id,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        delete_after_run=body.delete_after_run,
        schedule=schedule,
        payload=payload,
        delivery=delivery,
        conversation_mode=body.conversation_mode,
        conversation_id=body.conversation_id,
        timezone=body.timezone,
        stagger_seconds=body.stagger_seconds,
        timeout_seconds=body.timeout_seconds,
        max_retries=body.max_retries,
    )
    await db.commit()
    # Best-effort APScheduler re-registration
    try:
        if job.enabled:
            from src.infrastructure.scheduler.scheduler_service import register_job

            await register_job(
                job_id=job.id,
                schedule_type=job.schedule.kind.value,
                schedule_config=job.schedule.config,
                timezone=job.timezone,
            )
        else:
            from src.infrastructure.scheduler.scheduler_service import unregister_job

            await unregister_job(job.id)
    except Exception:
        logger.debug("Scheduler not available -- skipping re-registration for %s", job.id)
    return cron_job_to_response(job)


@router.delete("/{job_id}", status_code=204)
async def delete_cron_job(
    project_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a cron job."""
    svc = _container(db).cron_job_service()

    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")

    await svc.delete_job(job_id)
    await db.commit()
    # Best-effort APScheduler unregistration
    try:
        from src.infrastructure.scheduler.scheduler_service import unregister_job

        await unregister_job(job_id)
    except Exception:
        logger.debug("Scheduler not available -- skipping unregistration for %s", job_id)


@router.post("/{job_id}/toggle", response_model=CronJobResponse)
async def toggle_cron_job(
    project_id: str,
    job_id: str,
    enabled: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobResponse:
    """Enable or disable a cron job."""
    svc = _container(db).cron_job_service()

    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")

    job = await svc.toggle_job(job_id, enabled=enabled)
    await db.commit()
    # Best-effort APScheduler toggle
    try:
        if enabled:
            from src.infrastructure.scheduler.scheduler_service import register_job

            await register_job(
                job_id=job.id,
                schedule_type=job.schedule.kind.value,
                schedule_config=job.schedule.config,
                timezone=job.timezone,
            )
        else:
            from src.infrastructure.scheduler.scheduler_service import unregister_job

            await unregister_job(job.id)
    except Exception:
        logger.debug("Scheduler not available -- skipping toggle for %s", job.id)
    return cron_job_to_response(job)


@router.post(
    "/{job_id}/run",
    response_model=CronJobResponse,
    status_code=202,
)
async def trigger_manual_run(
    project_id: str,
    job_id: str,
    body: ManualRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobResponse:
    """Trigger a manual execution of a cron job."""
    svc = _container(db).cron_job_service()

    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")

    conversation_id_override = body.conversation_id if body else None
    await svc.trigger_manual_run(job_id, conversation_id=conversation_id_override)
    await db.commit()

    # Return the refreshed job (state may have changed)
    refreshed = await svc.get_job(job_id)
    assert refreshed is not None
    return cron_job_to_response(refreshed)


@router.get("/{job_id}/runs", response_model=CronJobRunListResponse)
async def list_cron_job_runs(
    project_id: str,
    job_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CronJobRunListResponse:
    """List execution runs for a cron job."""
    svc = _container(db).cron_job_service()

    # Verify the job belongs to this project
    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail="Cron job not found")

    runs = await svc.list_runs(job_id, limit=limit, offset=offset)
    total = await svc.count_runs(job_id)
    return CronJobRunListResponse(
        items=[cron_job_run_to_response(r) for r in runs],
        total=total,
    )
