from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.audit_schemas import (
    AuditEntryResponse,
    AuditLogListResponse,
    RuntimeHookAuditSummaryResponse,
)
from src.application.services.audit_query_service import AuditQueryService
from src.domain.model.audit.audit_entry import AuditEntry
from src.domain.model.auth.user import User
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.sql_audit_repository import (
    SqlAuditRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/audit-logs",
    tags=["audit-logs"],
)

AUDIT_EXPORT_LIMIT = 10_000
AUDIT_EXPORT_COLUMNS = [
    "id",
    "timestamp",
    "actor",
    "action",
    "resource_type",
    "resource_id",
    "tenant_id",
    "details",
    "ip_address",
    "user_agent",
]


def _build_service(db: AsyncSession) -> AuditQueryService:
    return AuditQueryService(audit_repo=SqlAuditRepository(db))


def _entry_to_export_row(entry: AuditEntry) -> dict[str, str]:
    details = json.dumps(entry.details, ensure_ascii=False, sort_keys=True)
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat(),
        "actor": entry.actor or "",
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id or "",
        "tenant_id": entry.tenant_id or "",
        "details": details,
        "ip_address": entry.ip_address or "",
        "user_agent": entry.user_agent or "",
    }


def _render_audit_export(entries: list[AuditEntry], export_format: Literal["csv", "json"]) -> str:
    rows = [_entry_to_export_row(entry) for entry in entries]
    if export_format == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=AUDIT_EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditLogListResponse:
    await require_tenant_access(db, current_user, tenant_id)
    service = _build_service(db)
    items, total = await service.list_entries(tenant_id, limit=limit, offset=offset)
    return AuditLogListResponse(
        items=[
            AuditEntryResponse(
                id=e.id,
                timestamp=e.timestamp,
                actor=e.actor,
                action=e.action,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                tenant_id=e.tenant_id,
                details=e.details,
                ip_address=e.ip_address,
                user_agent=e.user_agent,
            )
            for e in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/filter", response_model=AuditLogListResponse)
async def list_audit_logs_filtered(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditLogListResponse:
    await require_tenant_access(db, current_user, tenant_id)
    service = _build_service(db)
    items, total = await service.list_entries_filtered(
        tenant_id,
        action=action,
        resource_type=resource_type,
        actor=actor,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return AuditLogListResponse(
        items=[
            AuditEntryResponse(
                id=e.id,
                timestamp=e.timestamp,
                actor=e.actor,
                action=e.action,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                tenant_id=e.tenant_id,
                details=e.details,
                ip_address=e.ip_address,
                user_agent=e.user_agent,
            )
            for e in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runtime-hooks", response_model=AuditLogListResponse)
async def list_runtime_hook_audit_logs(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    action: str | None = Query(default=None),
    hook_name: str | None = Query(default=None),
    executor_kind: str | None = Query(default=None),
    hook_family: str | None = Query(default=None),
    isolation_mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditLogListResponse:
    """List runtime hook audit entries with hook-specific filters."""
    await require_tenant_access(db, current_user, tenant_id)
    service = _build_service(db)
    items, total = await service.list_runtime_hook_entries(
        tenant_id,
        action=action,
        hook_name=hook_name,
        executor_kind=executor_kind,
        hook_family=hook_family,
        isolation_mode=isolation_mode,
        limit=limit,
        offset=offset,
    )
    return AuditLogListResponse(
        items=[
            AuditEntryResponse(
                id=e.id,
                timestamp=e.timestamp,
                actor=e.actor,
                action=e.action,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                tenant_id=e.tenant_id,
                details=e.details,
                ip_address=e.ip_address,
                user_agent=e.user_agent,
            )
            for e in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export", response_model=None)
async def export_audit_logs(  # noqa: PLR0913
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    export_format: Literal["csv", "json"] = Query(default="csv", alias="format"),
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    hook_name: str | None = Query(default=None),
    executor_kind: str | None = Query(default=None),
    hook_family: str | None = Query(default=None),
    isolation_mode: str | None = Query(default=None),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
) -> Response:
    await require_tenant_access(db, current_user, tenant_id)
    service = _build_service(db)
    is_runtime_hook_export = (
        hook_name is not None
        or executor_kind is not None
        or hook_family is not None
        or isolation_mode is not None
        or (action is not None and action.startswith("runtime_hook."))
    )
    if is_runtime_hook_export:
        items, _total = await service.list_runtime_hook_entries(
            tenant_id,
            action=action,
            hook_name=hook_name,
            executor_kind=executor_kind,
            hook_family=hook_family,
            isolation_mode=isolation_mode,
            limit=AUDIT_EXPORT_LIMIT,
            offset=0,
        )
    else:
        items, _total = await service.list_entries_filtered(
            tenant_id,
            action=action,
            resource_type=resource_type,
            actor=actor,
            start_time=start_time,
            end_time=end_time,
            limit=AUDIT_EXPORT_LIMIT,
            offset=0,
        )
    body = _render_audit_export(items, export_format)
    extension = "json" if export_format == "json" else "csv"
    media_type = "application/json" if export_format == "json" else "text/csv"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="audit-logs.{extension}"'},
    )


@router.get("/runtime-hooks/summary", response_model=RuntimeHookAuditSummaryResponse)
async def get_runtime_hook_audit_summary(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    action: str | None = Query(default=None),
    hook_name: str | None = Query(default=None),
    executor_kind: str | None = Query(default=None),
    hook_family: str | None = Query(default=None),
    isolation_mode: str | None = Query(default=None),
) -> RuntimeHookAuditSummaryResponse:
    """Return aggregate runtime hook audit information for observability."""
    await require_tenant_access(db, current_user, tenant_id)
    service = _build_service(db)
    summary = await service.summarize_runtime_hook_entries(
        tenant_id,
        action=action,
        hook_name=hook_name,
        executor_kind=executor_kind,
        hook_family=hook_family,
        isolation_mode=isolation_mode,
    )
    return RuntimeHookAuditSummaryResponse(**cast(dict[str, Any], summary))
