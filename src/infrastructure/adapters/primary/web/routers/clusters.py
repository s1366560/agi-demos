"""Cluster Management API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.cluster_schemas import (
    ClusterCreate,
    ClusterHealthResponse,
    ClusterListResponse,
    ClusterResponse,
    ClusterUpdate,
)
from src.configuration.di_container import DIContainer
from src.domain.model.cluster.cluster import Cluster
from src.domain.model.cluster.enums import ClusterStatus
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.i18n import gettext as _


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/clusters", tags=["Clusters"])


def _health_config(provider_config: dict[str, object]) -> dict[str, object]:
    health = provider_config.get("health")
    return dict(health) if isinstance(health, dict) else {}


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    numeric = _as_float(value)
    return int(numeric) if numeric is not None else None


def _usage_percent(used: object, total: object) -> float | None:
    used_value = _as_float(used)
    total_value = _as_float(total)
    if used_value is None or total_value is None or total_value <= 0:
        return None
    return round(min(max((used_value / total_value) * 100, 0), 100), 2)


def _cluster_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_("Cluster not found"),
    )


def _cluster_health_response(cluster: Cluster) -> ClusterHealthResponse:
    provider_config = cluster.provider_config or {}
    health = _health_config(provider_config)

    node_count = (
        _as_int(health.get("total_nodes"))
        or _as_int(provider_config.get("node_count"))
        or _as_int(provider_config.get("nodes"))
        or 0
    )
    cpu_usage = _as_float(health.get("cpu_usage"))
    if cpu_usage is None:
        cpu_usage = _usage_percent(health.get("used_cpu"), health.get("total_cpu"))
    memory_usage = _as_float(health.get("memory_usage"))
    if memory_usage is None:
        memory_usage = _usage_percent(
            health.get("used_memory_gb"),
            health.get("total_memory_gb"),
        )

    return ClusterHealthResponse(
        status=cluster.health_status or cluster.status.value,
        node_count=node_count,
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        checked_at=cluster.last_health_check,
    )


class HealthStatusUpdate(BaseModel):
    """Request model for updating cluster health status."""

    health_status: str = Field(..., description="Health status description")
    total_nodes: int = Field(..., ge=0, description="Total number of nodes")
    active_nodes: int = Field(..., ge=0, description="Number of active nodes")
    total_cpu: float = Field(..., ge=0.0, description="Total CPU cores")
    used_cpu: float = Field(..., ge=0.0, description="Used CPU cores")
    total_memory_gb: float = Field(..., ge=0.0, description="Total memory in GB")
    used_memory_gb: float = Field(..., ge=0.0, description="Used memory in GB")


@router.post(
    "/",
    response_model=ClusterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cluster(
    request: Request,
    data: ClusterCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    current_user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Create a new cluster."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.create_cluster(
            name=data.name,
            tenant_id=tenant_id,
            created_by=current_user.id,
            compute_provider=data.compute_provider,
            proxy_endpoint=data.proxy_endpoint,
            provider_config=data.provider_config,
            credentials_encrypted=data.credentials_encrypted,
        )
        await db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating cluster")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get("/", response_model=ClusterListResponse)
async def list_clusters(
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ClusterListResponse:
    """List clusters for the current tenant."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        offset = (page - 1) * page_size
        clusters, total = await service.list_clusters_with_total(
            tenant_id=tenant_id,
            limit=page_size,
            offset=offset,
        )
        items = [ClusterResponse.model_validate(c, from_attributes=True) for c in clusters]
        return ClusterListResponse(
            clusters=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing clusters")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Get a cluster by ID."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.get_cluster(cluster_id, tenant_id=tenant_id)
        if not result:
            raise _cluster_not_found_error()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting cluster")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.put("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: Request,
    data: ClusterUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Update a cluster."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.update_cluster(
            cluster_id=cluster_id,
            name=data.name,
            compute_provider=data.compute_provider,
            proxy_endpoint=data.proxy_endpoint,
            provider_config=data.provider_config,
            credentials_encrypted=data.credentials_encrypted,
            tenant_id=tenant_id,
        )
        await db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise _cluster_not_found_error() from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating cluster")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.delete(
    "/{cluster_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_cluster(
    cluster_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a cluster."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        await service.delete_cluster(cluster_id, tenant_id=tenant_id)
        await db.commit()
    except ValueError as e:
        raise _cluster_not_found_error() from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting cluster")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get(
    "/{cluster_id}/health",
    response_model=ClusterHealthResponse,
)
async def get_cluster_health(
    cluster_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ClusterHealthResponse:
    """Get the latest cluster health snapshot."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.get_cluster(cluster_id, tenant_id=tenant_id)
        if not result:
            raise _cluster_not_found_error()
        return _cluster_health_response(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting cluster health")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.put(
    "/{cluster_id}/health",
    response_model=ClusterResponse,
)
async def update_health_status(
    cluster_id: str,
    request: Request,
    data: HealthStatusUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Update cluster health status."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.update_health_status(
            cluster_id=cluster_id,
            status=ClusterStatus.connected,
            health_status=data.health_status,
            total_nodes=data.total_nodes,
            active_nodes=data.active_nodes,
            total_cpu=data.total_cpu,
            used_cpu=data.used_cpu,
            total_memory_gb=data.total_memory_gb,
            used_memory_gb=data.used_memory_gb,
            tenant_id=tenant_id,
        )
        await db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise _cluster_not_found_error() from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating cluster health")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e
