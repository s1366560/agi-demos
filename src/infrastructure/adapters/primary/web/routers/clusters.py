"""Cluster Management API endpoints."""

import logging
from typing import Any, cast
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.acp_runner_schemas import (
    ACPRunnerPoolCreate,
    ACPRunnerPoolResponse,
    ACPRunnerPoolUpdate,
    ACPRunnerTokenRequest,
    ACPRunnerTokenResponse,
)
from src.application.schemas.cluster_schemas import (
    ClusterCreate,
    ClusterHealthResponse,
    ClusterListResponse,
    ClusterResponse,
    ClusterUpdate,
)
from src.configuration.config import get_settings
from src.domain.model.cluster.cluster import Cluster
from src.domain.model.cluster.enums import ClusterStatus
from src.infrastructure.adapters.primary.web.cluster_application_authority_v2 import (
    ClusterApplicationAuthorityV2,
    cluster_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.agent.access import require_tenant_access
from src.infrastructure.adapters.secondary.persistence.models import (
    ACPRunnerInstanceModel,
    ACPRunnerPoolModel,
    User as DBUser,
)
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/clusters", tags=["Clusters"])


def _health_config(provider_config: dict[str, object]) -> dict[str, object]:
    health = provider_config.get("health")
    return dict(cast(dict[str, object], health)) if isinstance(health, dict) else {}


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


async def _require_cluster_admin(
    db: AsyncSession,
    current_user: DBUser,
    tenant_id: str,
) -> None:
    await require_tenant_access(
        db,
        cast(Any, current_user),
        tenant_id,
        require_admin=True,
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


def _pool_response(
    pool: ACPRunnerPoolModel,
    instances: list[ACPRunnerInstanceModel],
) -> ACPRunnerPoolResponse:
    pool_instances = [instance for instance in instances if instance.pool_id == pool.id]
    ready = [instance for instance in pool_instances if instance.status == "ready"]
    return ACPRunnerPoolResponse(
        id=pool.id,
        tenantId=pool.tenant_id,
        clusterId=pool.cluster_id,
        poolKey=pool.pool_key,
        name=pool.name,
        mode=pool.mode,
        enabled=pool.enabled,
        labels=dict(pool.labels or {}),
        capacityPolicy=dict(pool.capacity_policy or {}),
        schedulingPolicy=dict(pool.scheduling_policy or {}),
        runnerCount=len(pool_instances),
        readyRunnerCount=len(ready),
        activeSessionCount=sum(int(instance.current_sessions or 0) for instance in pool_instances),
        createdAt=pool.created_at,
        updatedAt=pool.updated_at,
    )


async def _require_cluster_for_tenant(
    authority: ClusterApplicationAuthorityV2,
    *,
    cluster_id: str,
) -> Cluster:
    cluster = await authority.services.clusters.get_cluster(
        cluster_id,
        tenant_id=authority.tenant_id,
    )
    if not cluster:
        raise _cluster_not_found_error()
    return cluster


def _runner_connect_url() -> str:
    base_url = get_settings().acp_http_base_url
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/v1/acp/runners/connect"):
        path = f"{path}/api/v1/acp/runners/connect"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def _runner_install_command(connect_url: str, token: str) -> str:
    return f"memstack-acp-runner --connect {connect_url} --token {token}"


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
    data: ClusterCreate,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ClusterResponse:
    """Create a new cluster."""
    try:
        await _require_cluster_admin(
            authority.db,
            authority.current_user,
            authority.tenant_id,
        )

        result = await authority.services.clusters.create_cluster(
            name=data.name,
            tenant_id=authority.tenant_id,
            created_by=authority.current_user.id,
            compute_provider=data.compute_provider,
            proxy_endpoint=data.proxy_endpoint,
            provider_config=data.provider_config,
            credentials_encrypted=data.credentials_encrypted,
        )
        await authority.db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating cluster")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get("/", response_model=ClusterListResponse)
async def list_clusters(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ClusterListResponse:
    """List clusters for the current tenant."""
    try:
        offset = (page - 1) * page_size
        clusters, total = await authority.services.clusters.list_clusters_with_total(
            tenant_id=authority.tenant_id,
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
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ClusterResponse:
    """Get a cluster by ID."""
    try:
        result = await authority.services.clusters.get_cluster(
            cluster_id,
            tenant_id=authority.tenant_id,
        )
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
    data: ClusterUpdate,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ClusterResponse:
    """Update a cluster."""
    try:
        await _require_cluster_admin(
            authority.db,
            authority.current_user,
            authority.tenant_id,
        )

        result = await authority.services.clusters.update_cluster(
            cluster_id=cluster_id,
            name=data.name,
            compute_provider=data.compute_provider,
            proxy_endpoint=data.proxy_endpoint,
            provider_config=data.provider_config,
            credentials_encrypted=data.credentials_encrypted,
            tenant_id=authority.tenant_id,
        )
        await authority.db.commit()
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
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> None:
    """Delete a cluster."""
    try:
        await _require_cluster_admin(
            authority.db,
            authority.current_user,
            authority.tenant_id,
        )

        await authority.services.clusters.delete_cluster(
            cluster_id,
            tenant_id=authority.tenant_id,
        )
        await authority.db.commit()
    except ValueError as e:
        raise _cluster_not_found_error() from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting cluster")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e


@router.get(
    "/{cluster_id}/acp-runner-pools",
    response_model=list[ACPRunnerPoolResponse],
)
async def list_cluster_acp_runner_pools(
    cluster_id: str,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> list[ACPRunnerPoolResponse]:
    """List ACP runner pools attached to a cluster."""
    _cluster = await _require_cluster_for_tenant(authority, cluster_id=cluster_id)
    pools, instances = await authority.services.runner_pools.list_for_cluster(
        tenant_id=authority.tenant_id,
        cluster_id=cluster_id,
    )
    return [_pool_response(pool, instances) for pool in pools]


@router.post(
    "/{cluster_id}/acp-runner-pools",
    response_model=ACPRunnerPoolResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_cluster_acp_runner_pool(
    cluster_id: str,
    data: ACPRunnerPoolCreate,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ACPRunnerPoolResponse:
    """Create an ACP runner pool attached to a cluster."""
    await _require_cluster_admin(
        authority.db,
        authority.current_user,
        authority.tenant_id,
    )
    _cluster = await _require_cluster_for_tenant(authority, cluster_id=cluster_id)
    existing = await authority.services.runner_pools.get_by_tenant_key(
        tenant_id=authority.tenant_id,
        pool_key=data.pool_key,
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=_("ACP runner pool already exists"))
    pool = await authority.services.runner_pools.create(
        tenant_id=authority.tenant_id,
        cluster_id=cluster_id,
        pool_key=data.pool_key,
        name=data.name,
        mode=data.mode,
        enabled=data.enabled,
        labels=data.labels,
        capacity_policy=data.capacity_policy,
        scheduling_policy=data.scheduling_policy,
        created_by=authority.current_user.id,
    )
    await authority.db.commit()
    return _pool_response(pool, [])


@router.put(
    "/{cluster_id}/acp-runner-pools/{pool_key}",
    response_model=ACPRunnerPoolResponse,
)
async def update_cluster_acp_runner_pool(
    cluster_id: str,
    pool_key: str,
    data: ACPRunnerPoolUpdate,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ACPRunnerPoolResponse:
    """Update an ACP runner pool attached to a cluster."""
    await _require_cluster_admin(
        authority.db,
        authority.current_user,
        authority.tenant_id,
    )
    _cluster = await _require_cluster_for_tenant(authority, cluster_id=cluster_id)
    pool = await authority.services.runner_pools.get_by_cluster_key(
        tenant_id=authority.tenant_id,
        cluster_id=cluster_id,
        pool_key=pool_key,
    )
    if pool is None:
        raise HTTPException(status_code=404, detail=_("ACP runner pool not found"))
    pool = await authority.services.runner_pools.update(
        pool,
        name=data.name,
        mode=data.mode,
        enabled=data.enabled,
        labels=data.labels,
        capacity_policy=data.capacity_policy,
        scheduling_policy=data.scheduling_policy,
    )
    await authority.db.commit()
    instances = await authority.services.runner_pools.list_instances(pool.id)
    return _pool_response(pool, instances)


@router.post(
    "/{cluster_id}/acp-runner-pools/{pool_key}/registration-token",
    response_model=ACPRunnerTokenResponse,
)
async def create_cluster_acp_runner_registration_token(
    cluster_id: str,
    pool_key: str,
    data: ACPRunnerTokenRequest,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ACPRunnerTokenResponse:
    """Create a plaintext registration token shown once to tenant admins."""
    await _require_cluster_admin(
        authority.db,
        authority.current_user,
        authority.tenant_id,
    )
    _cluster = await _require_cluster_for_tenant(authority, cluster_id=cluster_id)
    pool = await authority.services.runner_pools.get_by_cluster_key(
        tenant_id=authority.tenant_id,
        cluster_id=cluster_id,
        pool_key=pool_key,
    )
    if pool is None:
        raise HTTPException(status_code=404, detail=_("ACP runner pool not found"))
    token_row, token = await authority.services.runner_pools.create_registration_token(
        pool=pool,
        created_by=authority.current_user.id,
        name=data.name,
        expires_in_hours=data.expires_in_hours,
    )
    await authority.db.commit()
    connect_url = _runner_connect_url()
    return ACPRunnerTokenResponse(
        token=token,
        expiresAt=token_row.expires_at,
        connectUrl=connect_url,
        installCommand=_runner_install_command(connect_url, token),
    )


@router.get(
    "/{cluster_id}/health",
    response_model=ClusterHealthResponse,
)
async def get_cluster_health(
    cluster_id: str,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ClusterHealthResponse:
    """Get the latest cluster health snapshot."""
    try:
        result = await authority.services.clusters.get_cluster(
            cluster_id,
            tenant_id=authority.tenant_id,
        )
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
    data: HealthStatusUpdate,
    authority: ClusterApplicationAuthorityV2 = Depends(cluster_application_authority_dependency_v2),
) -> ClusterResponse:
    """Update cluster health status."""
    try:
        await _require_cluster_admin(
            authority.db,
            authority.current_user,
            authority.tenant_id,
        )

        result = await authority.services.clusters.update_health_status(
            cluster_id=cluster_id,
            status=ClusterStatus.connected,
            health_status=data.health_status,
            total_nodes=data.total_nodes,
            active_nodes=data.active_nodes,
            total_cpu=data.total_cpu,
            used_cpu=data.used_cpu,
            total_memory_gb=data.total_memory_gb,
            used_memory_gb=data.used_memory_gb,
            tenant_id=authority.tenant_id,
        )
        await authority.db.commit()
        return ClusterResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise _cluster_not_found_error() from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating cluster health")
        raise HTTPException(status_code=500, detail=_("Internal server error")) from e
