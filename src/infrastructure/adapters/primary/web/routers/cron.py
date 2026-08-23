"""Cron job management API routes.

Scoped under ``/api/v1/projects/{project_id}/cron-jobs``.
"""

from __future__ import annotations

from typing import Never

from fastapi import APIRouter, Depends, HTTPException

from src.application.schemas.cron import (
    AutomationRunCommandV2,
    AutomationRunReceiptResponse,
    CronActionCapability,
    CronJobCapabilitiesResponse,
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
from src.application.services.automation_command_service import (
    AutomationActor,
    AutomationCommandIdempotencyConflictError,
    AutomationCommandRevisionConflictError,
    AutomationCommandTargetNotFoundError,
    QueueManualRunCommand,
)
from src.application.services.cron_service import (
    CronExecutionUnavailableError,
    CronMutationUnavailableError,
)
from src.infrastructure.adapters.primary.web.cron_application_authority_v2 import (
    CronApplicationAuthorityV2,
    cron_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.cron_services import (
    CronProjectAccessDeniedV2,
    remove_cron_schedule_v2,
    sync_cron_schedule_v2,
)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/cron-jobs",
    tags=["cron-jobs"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raise_mutation_unavailable(exc: CronMutationUnavailableError) -> Never:
    raise HTTPException(
        status_code=503,
        detail=_("Durable automation mutations are not available"),
    ) from exc


async def _require_project_access(
    authority: CronApplicationAuthorityV2,
    project_id: str,
) -> None:
    try:
        await authority.services.require_project_access(
            project_id=project_id,
            user_id=authority.user_id,
        )
    except CronProjectAccessDeniedV2 as error:
        raise HTTPException(
            status_code=403,
            detail=_("Access denied to project"),
        ) from error


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=CronJobListResponse)
async def list_cron_jobs(
    project_id: str,
    include_disabled: bool = False,
    limit: int = 50,
    offset: int = 0,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobListResponse:
    """List cron jobs for a project."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs
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


@router.get("/capabilities", response_model=CronJobCapabilitiesResponse)
async def get_cron_job_capabilities(
    project_id: str,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobCapabilitiesResponse:
    """Return structured automation availability without inferring from failed requests."""
    await _require_project_access(cron_application, project_id)
    mutation_unavailable = CronActionCapability(
        allowed=False,
        reason_code="durable_automation_runtime_unavailable",
    )
    return CronJobCapabilitiesResponse(
        read=True,
        revision_guarded=False,
        idempotency_guarded=False,
        durable_execution=False,
        supported_read_trigger_kinds=["manual", "schedule", "event"],
        create=mutation_unavailable,
        edit=mutation_unavailable,
        toggle=mutation_unavailable,
        run_now=CronActionCapability(
            allowed=False,
            reason_code="durable_automation_execution_unavailable",
        ),
        delete=mutation_unavailable,
    )


@router.post("", response_model=CronJobResponse, status_code=201)
async def create_cron_job(
    project_id: str,
    body: CronJobCreate,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobResponse:
    """Create a new cron job."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs

    project = await cron_application.services.projects.project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=_("Project not found"))

    try:
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
            created_by=cron_application.user_id,
        )
    except CronMutationUnavailableError as exc:
        _raise_mutation_unavailable(exc)
    await cron_application.db.commit()
    if job.enabled:
        await sync_cron_schedule_v2(cron_application.services, job=job, enabled=True)
    return cron_job_to_response(job)


@router.get("/{job_id}", response_model=CronJobResponse)
async def get_cron_job(
    project_id: str,
    job_id: str,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobResponse:
    """Get a single cron job by ID."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs
    job = await svc.get_job(job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Cron job not found"))
    return cron_job_to_response(job)


@router.patch("/{job_id}", response_model=CronJobResponse)
async def update_cron_job(
    project_id: str,
    job_id: str,
    body: CronJobUpdate,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobResponse:
    """Update a cron job (partial)."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs

    # Verify ownership
    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Cron job not found"))

    schedule = schedule_config_to_domain(body.schedule) if body.schedule is not None else None
    payload = payload_config_to_domain(body.payload) if body.payload is not None else None
    delivery = delivery_config_to_domain(body.delivery) if body.delivery is not None else None

    try:
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
    except CronMutationUnavailableError as exc:
        _raise_mutation_unavailable(exc)
    await cron_application.db.commit()
    await sync_cron_schedule_v2(
        cron_application.services,
        job=job,
        enabled=job.enabled,
    )
    return cron_job_to_response(job)


@router.delete("/{job_id}", status_code=204)
async def delete_cron_job(
    project_id: str,
    job_id: str,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> None:
    """Delete a cron job."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs

    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Cron job not found"))

    try:
        _deleted = await svc.delete_job(job_id)
    except CronMutationUnavailableError as exc:
        _raise_mutation_unavailable(exc)
    await cron_application.db.commit()
    await remove_cron_schedule_v2(cron_application.services, job_id=job_id)


@router.post("/{job_id}/toggle", response_model=CronJobResponse)
async def toggle_cron_job(
    project_id: str,
    job_id: str,
    enabled: bool = True,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobResponse:
    """Enable or disable a cron job."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs

    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Cron job not found"))

    try:
        job = await svc.toggle_job(job_id, enabled=enabled)
    except CronMutationUnavailableError as exc:
        _raise_mutation_unavailable(exc)
    await cron_application.db.commit()
    await sync_cron_schedule_v2(
        cron_application.services,
        job=job,
        enabled=enabled,
    )
    return cron_job_to_response(job)


@router.post(
    "/{job_id}/run",
    response_model=CronJobResponse | AutomationRunReceiptResponse,
    status_code=202,
)
async def trigger_manual_run(
    project_id: str,
    job_id: str,
    body: AutomationRunCommandV2 | ManualRunRequest | None = None,
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobResponse | AutomationRunReceiptResponse:
    """Trigger a manual execution of a cron job."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs

    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Cron job not found"))

    if isinstance(body, AutomationRunCommandV2):
        command_service = cron_application.services.commands
        try:
            receipt = await command_service.queue_manual_run(
                actor=AutomationActor(
                    tenant_id=existing.tenant_id,
                    project_id=project_id,
                    user_id=cron_application.user_id,
                ),
                command=QueueManualRunCommand(
                    job_id=job_id,
                    expected_revision=body.expected_revision,
                    idempotency_key=body.idempotency_key,
                    conversation_id=body.conversation_id,
                ),
            )
        except AutomationCommandTargetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=_("Cron job not found")) from exc
        except AutomationCommandRevisionConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason_code": "automation_revision_conflict",
                    "expected_revision": exc.expected_revision,
                    "current_revision": exc.current_revision,
                },
            ) from exc
        except AutomationCommandIdempotencyConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "automation_idempotency_conflict"},
            ) from exc
        await cron_application.db.commit()
        return AutomationRunReceiptResponse(
            receipt_id=receipt.receipt_id,
            operation_id=receipt.operation_id,
            run_id=receipt.run_id,
            runtime_execution_id=receipt.runtime_execution_id,
            job_id=receipt.job_id,
            job_revision=receipt.job_revision,
            status=receipt.status,
            duplicate=receipt.duplicate,
        )

    conversation_id_override = body.conversation_id if body else None
    try:
        _run = await svc.trigger_manual_run(job_id, conversation_id=conversation_id_override)
    except CronExecutionUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=_("Durable automation execution is not available"),
        ) from exc
    await cron_application.db.commit()

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
    cron_application: CronApplicationAuthorityV2 = Depends(
        cron_application_authority_dependency_v2
    ),
) -> CronJobRunListResponse:
    """List execution runs for a cron job."""
    await _require_project_access(cron_application, project_id)
    svc = cron_application.services.cron_jobs

    # Verify the job belongs to this project
    existing = await svc.get_job(job_id)
    if existing is None or existing.project_id != project_id:
        raise HTTPException(status_code=404, detail=_("Cron job not found"))

    runs = await svc.list_runs(job_id, limit=limit, offset=offset)
    total = await svc.count_runs(job_id)
    return CronJobRunListResponse(
        items=[cron_job_run_to_response(r) for r in runs],
        total=total,
    )
