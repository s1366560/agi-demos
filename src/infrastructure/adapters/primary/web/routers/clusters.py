"""Cluster Management API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.cluster_schemas import (
    ClusterCreate,
    ClusterListResponse,
    ClusterResponse,
    ClusterUpdate,
)
from src.configuration.di_container import DIContainer
from src.domain.model.cluster.enums import ClusterStatus
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container._redis_client,
    )


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/clusters", tags=["Clusters"])


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
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Create a new cluster."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.create_cluster(
            name=data.name,
            tenant_id=tenant_id,
            created_by=tenant_id,
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
        raise HTTPException(status_code=500, detail="Internal server error") from e


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
        clusters = await service.list_clusters(
            tenant_id=tenant_id,
            limit=page_size,
            offset=offset,
        )
        items = [ClusterResponse.model_validate(c, from_attributes=True) for c in clusters]
        return ClusterListResponse(
            clusters=items,
            total=len(items),
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing clusters")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: str,
    request: Request,
    _tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Get a cluster by ID."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.get_cluster(cluster_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Cluster {cluster_id} not found",
            )
        return ClusterResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting cluster")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: Request,
    data: ClusterUpdate,
    _tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> ClusterResponse:
    """Update a cluster."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        result = await service.update_cluster(
            cluster_id=cluster_id,
            name=data.name,
            proxy_endpoint=data.proxy_endpoint,
            provider_config=data.provider_config,
            credentials_encrypted=data.credentials_encrypted,
        )
        await db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating cluster")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.delete(
    "/{cluster_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_cluster(
    cluster_id: str,
    request: Request,
    _tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a cluster."""
    try:
        container = get_container_with_db(request, db)
        service = container.cluster_service()
        await service.delete_cluster(cluster_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting cluster")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put(
    "/{cluster_id}/health",
    response_model=ClusterResponse,
)
async def update_health_status(
    cluster_id: str,
    request: Request,
    data: HealthStatusUpdate,
    _tenant_id: str = Depends(get_current_user_tenant),
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
        )
        await db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating cluster health")
        raise HTTPException(status_code=500, detail="Internal server error") from e
