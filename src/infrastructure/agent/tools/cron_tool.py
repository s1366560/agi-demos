"""Cron job management tool -- allows the agent to manage scheduled tasks.

Provides CRUD operations on cron jobs plus manual triggering and run history.
Uses the ``@tool_define`` decorator pattern with module-level DI via
``configure_cron_tool()``.

Ported from OpenClaw's cron-tool.ts, adapted for MemStack's DDD + Hexagonal
Architecture.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from src.application.schemas.cron import (
    DeliveryConfig,
    PayloadConfig,
    ScheduleConfig,
    delivery_config_to_domain,
    payload_config_to_domain,
    schedule_config_to_domain,
)
from src.application.services.cron_service import CronJobService
from src.domain.model.cron.cron_job import CronJob
from src.domain.model.cron.cron_job_run import CronJobRun
from src.domain.model.cron.value_objects import ConversationMode
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level DI state
# ---------------------------------------------------------------------------

_cron_session_factory: Callable[..., Any] | None = None


def configure_cron_tool(
    session_factory: Callable[..., Any],
) -> None:
    """Inject the DB session factory at agent startup.

    Each tool invocation creates its own session, builds repos/service,
    performs work, commits, and closes -- matching the todowrite pattern.

    Args:
        session_factory: An ``async_session_factory`` callable that returns
            an async context manager yielding ``AsyncSession``.
    """
    global _cron_session_factory
    _cron_session_factory = session_factory


def _get_session_factory() -> Callable[..., Any]:
    """Return the configured session factory or raise."""
    if _cron_session_factory is None:
        raise RuntimeError("cron tool not configured -- call configure_cron_tool() first")
    return _cron_session_factory


def _build_service(session: Any) -> CronJobService:
    """Build a ``CronJobService`` from a live DB session."""
    from src.infrastructure.adapters.secondary.persistence.sql_cron_job_repository import (
        SqlCronJobRepository,
        SqlCronJobRunRepository,
    )

    return CronJobService(
        cron_job_repo=SqlCronJobRepository(session),
        cron_job_run_repo=SqlCronJobRunRepository(session),
    )


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _job_summary(job: CronJob) -> dict[str, Any]:
    """Build a concise dict summary of a cron job."""
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule": job.schedule.to_dict(),
        "payload": {"kind": job.payload.kind.value},
        "timezone": job.timezone,
        "conversation_mode": job.conversation_mode.value,
        "conversation_id": job.conversation_id,
        "state": job.state,
    }


def _job_detail(job: CronJob) -> dict[str, Any]:
    """Build a full dict representation of a cron job."""
    return {
        "id": job.id,
        "name": job.name,
        "description": job.description,
        "enabled": job.enabled,
        "delete_after_run": job.delete_after_run,
        "schedule": job.schedule.to_dict(),
        "payload": job.payload.to_dict(),
        "delivery": job.delivery.to_dict(),
        "conversation_mode": job.conversation_mode.value,
        "conversation_id": job.conversation_id,
        "timezone": job.timezone,
        "stagger_seconds": job.stagger_seconds,
        "timeout_seconds": job.timeout_seconds,
        "max_retries": job.max_retries,
        "state": job.state,
        "created_at": str(job.created_at),
        "updated_at": str(job.updated_at) if job.updated_at else None,
    }


def _run_summary(run: CronJobRun) -> dict[str, Any]:
    """Build a concise dict summary of a cron job run."""
    return {
        "id": run.id,
        "job_id": run.job_id,
        "status": run.status.value,
        "trigger_type": run.trigger_type.value,
        "started_at": str(run.started_at),
        "finished_at": str(run.finished_at) if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
    }


# ---------------------------------------------------------------------------
# Scheduler registration helper (best-effort, non-fatal)
# ---------------------------------------------------------------------------


async def _try_register_job(job: CronJob) -> None:
    """Register a cron job with APScheduler (best-effort)."""
    try:
        from src.infrastructure.scheduler.scheduler_service import (
            register_job,
        )

        if job.enabled:
            await register_job(
                job_id=job.id,
                schedule_type=job.schedule.kind.value,
                schedule_config=job.schedule.config,
                timezone=job.timezone,
            )
    except Exception:
        logger.warning(
            "Failed to register job %s with scheduler (non-fatal)",
            job.id,
            exc_info=True,
        )


async def _try_unregister_job(job_id: str) -> None:
    """Unregister a cron job from APScheduler (best-effort)."""
    try:
        from src.infrastructure.scheduler.scheduler_service import (
            unregister_job,
        )

        await unregister_job(job_id)
    except Exception:
        logger.warning(
            "Failed to unregister job %s from scheduler (non-fatal)",
            job_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


async def _handle_status(
    ctx: ToolContext,
    *,
    include_disabled: bool,
) -> ToolResult:
    """Return a status summary of cron jobs in the project."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)
        total = await svc.count_jobs(project_id, include_disabled=True)
        enabled = await svc.count_jobs(project_id, include_disabled=False)
        disabled = total - enabled
        jobs = await svc.list_jobs(
            project_id,
            include_disabled=include_disabled,
            limit=20,
        )
        summaries = [_job_summary(j) for j in jobs]

    return ToolResult(
        output=_json(
            {
                "total": total,
                "enabled": enabled,
                "disabled": disabled,
                "jobs": summaries,
            }
        ),
        metadata={"total": total, "enabled": enabled},
    )


async def _handle_list(
    ctx: ToolContext,
    *,
    include_disabled: bool,
) -> ToolResult:
    """List cron jobs in the project."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)
        jobs = await svc.list_jobs(
            project_id,
            include_disabled=include_disabled,
            limit=50,
        )
        total = await svc.count_jobs(
            project_id,
            include_disabled=include_disabled,
        )

    return ToolResult(
        output=_json(
            {
                "items": [_job_summary(j) for j in jobs],
                "total": total,
            }
        ),
        metadata={"count": len(jobs), "total": total},
    )


async def _handle_add(  # noqa: PLR0911
    ctx: ToolContext,
    *,
    job: dict[str, Any] | None,
) -> ToolResult:
    """Create a new cron job."""
    project_id = ctx.project_id
    if not project_id:
        return ToolResult(
            output=_json({"error": "No project_id in context"}),
            is_error=True,
        )
    if not job:
        return ToolResult(
            output=_json({"error": "Missing 'job' parameter for add action"}),
            is_error=True,
        )

    name = job.get("name")
    if not name:
        return ToolResult(
            output=_json({"error": "Job must have a 'name'"}),
            is_error=True,
        )

    # Parse schedule
    schedule_raw = job.get("schedule")
    if not schedule_raw:
        return ToolResult(
            output=_json({"error": "Job must have a 'schedule'"}),
            is_error=True,
        )
    try:
        schedule_cfg = (
            ScheduleConfig(**schedule_raw) if isinstance(schedule_raw, dict) else schedule_raw
        )
        schedule = schedule_config_to_domain(schedule_cfg)
    except Exception as exc:
        return ToolResult(
            output=_json({"error": f"Invalid schedule: {exc}"}),
            is_error=True,
        )

    # Parse payload
    payload_raw = job.get("payload")
    if not payload_raw:
        return ToolResult(
            output=_json({"error": "Job must have a 'payload'"}),
            is_error=True,
        )
    try:
        payload_cfg = PayloadConfig(**payload_raw) if isinstance(payload_raw, dict) else payload_raw
        payload = payload_config_to_domain(payload_cfg)
    except Exception as exc:
        return ToolResult(
            output=_json({"error": f"Invalid payload: {exc}"}),
            is_error=True,
        )

    # Parse delivery (optional)
    delivery = None
    delivery_raw = job.get("delivery")
    if delivery_raw:
        try:
            delivery_cfg = (
                DeliveryConfig(**delivery_raw) if isinstance(delivery_raw, dict) else delivery_raw
            )
            delivery = delivery_config_to_domain(delivery_cfg)
        except Exception as exc:
            return ToolResult(
                output=_json({"error": f"Invalid delivery: {exc}"}),
                is_error=True,
            )

    # Parse conversation mode
    conv_mode_raw = job.get("conversation_mode", "reuse")
    try:
        conv_mode = ConversationMode(conv_mode_raw)
    except ValueError:
        conv_mode = ConversationMode.REUSE

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)

        # Resolve tenant_id from project
        from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
            SqlProjectRepository,
        )

        project_repo = SqlProjectRepository(session)
        project = await project_repo.find_by_id(project_id)
        tenant_id = project.tenant_id if project else ""
        if not tenant_id:
            return ToolResult(
                output=_json({"error": "Cannot resolve tenant_id for project"}),
                is_error=True,
            )

        created = await svc.create_job(
            project_id=project_id,
            tenant_id=tenant_id,
            name=name,
            schedule=schedule,
            payload=payload,
            description=job.get("description"),
            enabled=job.get("enabled", True),
            delete_after_run=job.get("delete_after_run", False),
            delivery=delivery,
            conversation_mode=conv_mode,
            conversation_id=job.get("conversation_id"),
            timezone=job.get("timezone", "UTC"),
            stagger_seconds=job.get("stagger_seconds", 0),
            timeout_seconds=job.get("timeout_seconds", 300),
            max_retries=job.get("max_retries", 3),
            created_by=ctx.user_id,
        )
        await session.commit()

    # Register with APScheduler (after commit, outside session context)
    await _try_register_job(created)

    return ToolResult(
        output=_json(
            {
                "created": True,
                "job": _job_detail(created),
            }
        ),
        metadata={"job_id": created.id},
    )


async def _handle_update(
    ctx: ToolContext,
    *,
    job_id: str | None,
    patch: dict[str, Any] | None,
) -> ToolResult:
    """Update an existing cron job."""
    if not job_id:
        return ToolResult(
            output=_json({"error": "Missing 'job_id' for update action"}),
            is_error=True,
        )
    if not patch:
        return ToolResult(
            output=_json({"error": "Missing 'patch' for update action"}),
            is_error=True,
        )

    # Convert nested configs to domain objects
    updates: dict[str, Any] = {}
    for key, value in patch.items():
        if key == "schedule" and isinstance(value, dict):
            updates["schedule"] = schedule_config_to_domain(ScheduleConfig(**value))
        elif key == "payload" and isinstance(value, dict):
            updates["payload"] = payload_config_to_domain(PayloadConfig(**value))
        elif key == "delivery" and isinstance(value, dict):
            updates["delivery"] = delivery_config_to_domain(DeliveryConfig(**value))
        elif key == "conversation_mode" and isinstance(value, str):
            updates["conversation_mode"] = ConversationMode(value)
        else:
            updates[key] = value

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)
        try:
            updated = await svc.update_job(job_id, **updates)
        except ValueError as exc:
            return ToolResult(
                output=_json({"error": str(exc)}),
                is_error=True,
            )
        await session.commit()

    # Re-register with APScheduler to pick up new schedule/enabled state
    if updated.enabled:
        await _try_register_job(updated)
    else:
        await _try_unregister_job(updated.id)

    return ToolResult(
        output=_json(
            {
                "updated": True,
                "job": _job_detail(updated),
            }
        ),
        metadata={"job_id": updated.id},
    )


async def _handle_remove(
    ctx: ToolContext,
    *,
    job_id: str | None,
) -> ToolResult:
    """Remove a cron job."""
    if not job_id:
        return ToolResult(
            output=_json({"error": "Missing 'job_id' for remove action"}),
            is_error=True,
        )

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)
        deleted = await svc.delete_job(job_id)
        if not deleted:
            return ToolResult(
                output=_json({"error": f"CronJob {job_id} not found"}),
                is_error=True,
            )
        await session.commit()

    # Unregister from APScheduler
    await _try_unregister_job(job_id)

    return ToolResult(
        output=_json({"deleted": True, "job_id": job_id}),
        metadata={"job_id": job_id},
    )


async def _handle_run(
    ctx: ToolContext,
    *,
    job_id: str | None,
    conversation_id: str | None,
) -> ToolResult:
    """Manually trigger a cron job."""
    if not job_id:
        return ToolResult(
            output=_json({"error": "Missing 'job_id' for run action"}),
            is_error=True,
        )

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)
        try:
            run = await svc.trigger_manual_run(
                job_id,
                conversation_id=conversation_id,
            )
        except ValueError as exc:
            return ToolResult(
                output=_json({"error": str(exc)}),
                is_error=True,
            )
        await session.commit()

    return ToolResult(
        output=_json(
            {
                "triggered": True,
                "run": _run_summary(run),
            }
        ),
        metadata={"run_id": run.id, "job_id": job_id},
    )


async def _handle_runs(
    ctx: ToolContext,
    *,
    job_id: str | None,
) -> ToolResult:
    """List recent runs for a cron job."""
    if not job_id:
        return ToolResult(
            output=_json({"error": "Missing 'job_id' for runs action"}),
            is_error=True,
        )

    factory = _get_session_factory()
    async with factory() as session:
        svc = _build_service(session)
        runs = await svc.list_runs(job_id, limit=20)
        total = await svc.count_runs(job_id)

    return ToolResult(
        output=_json(
            {
                "items": [_run_summary(r) for r in runs],
                "total": total,
            }
        ),
        metadata={"count": len(runs), "total": total, "job_id": job_id},
    )


# ---------------------------------------------------------------------------
# cron_tool definition
# ---------------------------------------------------------------------------

VALID_ACTIONS = ["status", "list", "add", "update", "remove", "run", "runs"]


@tool_define(
    name="cron",
    description=(
        "Manage scheduled/cron jobs for the current project. "
        "Actions: status (overview), list (all jobs), add (create), "
        "update (modify), remove (delete), run (manual trigger), "
        "runs (execution history). "
        "Schedule types: 'at' (one-shot), 'every' (interval), 'cron' (expression). "
        "Payload types: 'system_event' (inject text), 'agent_turn' (run agent)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": VALID_ACTIONS,
                "description": ("Action to perform: status, list, add, update, remove, run, runs."),
            },
            "job_id": {
                "type": "string",
                "description": ("Target job ID. Required for: update, remove, run, runs."),
            },
            "job": {
                "type": "object",
                "description": (
                    "Job definition for 'add'. Must include: name, schedule "
                    "(object with kind + config), payload (object with kind + "
                    "config). Optional: description, enabled, delete_after_run, "
                    "delivery, conversation_mode, conversation_id, timezone, "
                    "stagger_seconds, timeout_seconds, max_retries."
                ),
            },
            "patch": {
                "type": "object",
                "description": (
                    "Partial update object for 'update'. Only include fields "
                    "to change. Same shape as 'job' fields."
                ),
            },
            "include_disabled": {
                "type": "boolean",
                "description": ("Include disabled jobs in 'status' and 'list'. Default: false."),
            },
            "conversation_id": {
                "type": "string",
                "description": ("Override conversation ID for 'run' action."),
            },
        },
        "required": ["action"],
    },
    permission=None,
    category="cron",
)
async def cron_tool(  # noqa: PLR0911
    ctx: ToolContext,
    *,
    action: str,
    job_id: str | None = None,
    job: dict[str, Any] | None = None,
    patch: dict[str, Any] | None = None,
    include_disabled: bool = False,
    conversation_id: str | None = None,
) -> ToolResult:
    """Manage scheduled/cron jobs for the current project."""
    if action not in VALID_ACTIONS:
        return ToolResult(
            output=_json(
                {
                    "error": (
                        f"Invalid action '{action}'. Must be one of: {', '.join(VALID_ACTIONS)}"
                    )
                }
            ),
            is_error=True,
        )

    try:
        if action == "status":
            return await _handle_status(
                ctx,
                include_disabled=include_disabled,
            )
        elif action == "list":
            return await _handle_list(
                ctx,
                include_disabled=include_disabled,
            )
        elif action == "add":
            return await _handle_add(ctx, job=job)
        elif action == "update":
            return await _handle_update(ctx, job_id=job_id, patch=patch)
        elif action == "remove":
            return await _handle_remove(ctx, job_id=job_id)
        elif action == "run":
            return await _handle_run(
                ctx,
                job_id=job_id,
                conversation_id=conversation_id,
            )
        elif action == "runs":
            return await _handle_runs(ctx, job_id=job_id)
        else:
            return ToolResult(
                output=_json({"error": f"Unknown action: {action}"}),
                is_error=True,
            )
    except Exception as exc:
        logger.exception("cron tool error: action=%s", action)
        return ToolResult(
            output=_json({"error": f"Cron tool error: {exc}"}),
            is_error=True,
        )
