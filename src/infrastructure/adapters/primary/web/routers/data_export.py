"""Data export and management API routes."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Use Cases & DI Container
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
    get_graph_store,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import (
    has_global_admin_access,
    require_tenant_access,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    Project,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["data"])


async def _is_global_admin(db: AsyncSession, current_user: User) -> bool:
    """Return whether the caller can perform cross-tenant graph operations."""
    return bool(getattr(current_user, "is_superuser", False)) or await has_global_admin_access(
        db, cast(Any, current_user)
    )


async def _default_tenant_id_for_user(db: AsyncSession, current_user: User) -> str:
    """Return the caller's default tenant from persisted membership."""
    result = await db.execute(
        refresh_select_statement(
            select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id).limit(1)
        )
    )
    tenant_id = result.scalar_one_or_none()
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Tenant access required"),
        )
    return str(tenant_id)


async def _resolve_tenant_scope(
    requested_tenant_id: str | None,
    db: AsyncSession,
    current_user: User,
    *,
    require_admin: bool = False,
) -> str | None:
    """Resolve and authorize the tenant filter for graph data operations."""
    if await _is_global_admin(db, current_user):
        return requested_tenant_id

    tenant_id = requested_tenant_id or await _default_tenant_id_for_user(db, current_user)
    await require_tenant_access(
        db,
        cast(Any, current_user),
        tenant_id,
        require_admin=require_admin,
    )
    return tenant_id


async def _resolve_graph_export_scope(
    requested_tenant_id: str | None,
    requested_project_id: str | None,
    db: AsyncSession,
    current_user: User,
    *,
    require_admin: bool = False,
) -> tuple[str | None, str | None]:
    """Resolve tenant/project filters and authorize the requested graph data scope."""
    if requested_project_id is None:
        tenant_id = await _resolve_tenant_scope(
            requested_tenant_id,
            db,
            current_user,
            require_admin=require_admin,
        )
        return tenant_id, None

    project_result = await db.execute(
        refresh_select_statement(select(Project).where(Project.id == requested_project_id))
    )
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_("Project not found"))

    project_tenant_id = str(project.tenant_id)
    if requested_tenant_id is not None and requested_tenant_id != project_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Project does not belong to tenant"),
        )

    if await _is_global_admin(db, current_user):
        return project_tenant_id, requested_project_id

    membership_query = select(UserProject).where(
        UserProject.user_id == current_user.id,
        UserProject.project_id == requested_project_id,
    )
    if require_admin:
        membership_query = membership_query.where(UserProject.role.in_(["owner", "admin"]))

    membership_result = await db.execute(refresh_select_statement(membership_query))
    if membership_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Project access required"),
        )

    return project_tenant_id, requested_project_id


def _cleanup_body_value(body: dict[str, Any] | None, key: str, fallback: Any) -> Any:
    if body is not None and key in body:
        return body[key]
    return fallback


def _normalize_cleanup_dry_run(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=_("Invalid dry_run value"),
    )


def _normalize_cleanup_days(value: Any) -> int:
    if value is None:
        return 90
    if isinstance(value, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("older_than_days must be a positive integer"),
        )
    if isinstance(value, int):
        days = value
    elif isinstance(value, str) and value.strip().isdecimal():
        days = int(value.strip())
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("older_than_days must be a positive integer"),
        )
    if days < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("older_than_days must be a positive integer"),
        )
    return days


# --- Endpoints ---


@router.post("/export")
async def export_data(
    tenant_id: str | None = Body(None, description="Filter by tenant ID"),
    project_id: str | None = Body(None, description="Filter by project ID"),
    include_episodes: bool = Body(True, description="Include episode data"),
    include_entities: bool = Body(True, description="Include entity data"),
    include_relationships: bool = Body(True, description="Include relationship data"),
    include_communities: bool = Body(True, description="Include community data"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Export graph data as JSON.
    """
    try:
        effective_tenant_id, effective_project_id = await _resolve_graph_export_scope(
            tenant_id,
            project_id,
            db,
            current_user,
        )
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))
        export = await graph_store.data_export(
            tenant_id=effective_tenant_id,
            project_id=effective_project_id,
            include_episodes=include_episodes,
            include_entities=include_entities,
            include_relationships=include_relationships,
            include_communities=include_communities,
        )
        return export.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to export data")
        raise HTTPException(status_code=500, detail=_("Failed to export data")) from e


@router.get("/stats")
async def get_graph_stats(
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    project_id: str | None = Query(None, description="Filter by project ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Get graph statistics.

    Returns statistics about the knowledge graph including:
    - Number of entities
    - Number of episodes
    - Number of communities
    - Number of relationships (edges)
    """
    try:
        effective_tenant_id, effective_project_id = await _resolve_graph_export_scope(
            tenant_id,
            project_id,
            db,
            current_user,
        )
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))
        counts = await graph_store.count_stats(
            tenant_id=effective_tenant_id,
            project_id=effective_project_id,
        )
        return {
            **counts,
            "tenant_id": effective_tenant_id,
            "project_id": effective_project_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to get graph stats")) from e


@router.post("/cleanup")
async def cleanup_data(
    dry_run: bool | None = Query(None, description="If true, only report what would be deleted"),
    older_than_days: int | None = Query(
        None, ge=1, description="Delete data older than this many days"
    ),
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    project_id: str | None = Query(None, description="Filter by project ID"),
    body: dict[str, Any] | None = Body(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    graph_store: GraphStorePort | None = Depends(get_graph_store),
) -> dict[str, Any]:
    """
    Clean up old graph data.

    This endpoint can be used to remove old episodes and their associated
    entities and relationships. Use with caution!
    """
    try:
        effective_dry_run = _normalize_cleanup_dry_run(
            _cleanup_body_value(body, "dry_run", dry_run)
        )
        effective_days = _normalize_cleanup_days(
            _cleanup_body_value(body, "older_than_days", older_than_days)
        )
        effective_tenant = _cleanup_body_value(body, "tenant_id", tenant_id)
        effective_project = _cleanup_body_value(body, "project_id", project_id)
        effective_tenant, effective_project = await _resolve_graph_export_scope(
            effective_tenant,
            effective_project,
            db,
            current_user,
            require_admin=not effective_dry_run,
        )
        if graph_store is None:
            raise HTTPException(status_code=503, detail=_("Graph backend unavailable"))

        cutoff_date = datetime.now(UTC) - timedelta(days=int(effective_days))
        cutoff_iso = cutoff_date.isoformat()

        if effective_dry_run:
            count = await graph_store.count_episodes_by_age(
                cutoff_iso=cutoff_iso,
                tenant_id=effective_tenant,
                project_id=effective_project,
            )
            return {
                "dry_run": True,
                "would_delete": count,
                "cutoff_date": cutoff_iso,
                "tenant_id": effective_tenant,
                "project_id": effective_project,
                "message": f"Would delete {count} episodes older than {effective_days} days",
            }
        else:
            deleted = await graph_store.delete_episodes_by_age(
                cutoff_iso=cutoff_iso,
                tenant_id=effective_tenant,
                project_id=effective_project,
            )
            logger.warning(
                "Deleted %s episodes older than %s days for tenant: %s project: %s",
                deleted,
                effective_days,
                effective_tenant,
                effective_project,
            )
            return {
                "dry_run": False,
                "deleted": deleted,
                "cutoff_date": cutoff_iso,
                "tenant_id": effective_tenant,
                "project_id": effective_project,
                "message": f"Deleted {deleted} episodes older than {effective_days} days",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cleanup data: {e}")
        raise HTTPException(status_code=500, detail=_("Failed to cleanup data")) from e
