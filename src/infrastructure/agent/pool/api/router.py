"""
Pool Status API Router.

提供 Agent Pool 状态查询和管理的 REST API 端点。

端点:
- GET /api/v1/admin/pool/status - 获取池状态概览
- GET /api/v1/admin/pool/instances - 列出所有实例
- GET /api/v1/admin/pool/instances/{instance_key} - 获取实例详情
- POST /api/v1/admin/pool/instances/{instance_key}/pause - 暂停实例
- POST /api/v1/admin/pool/instances/{instance_key}/resume - 恢复实例
- DELETE /api/v1/admin/pool/instances/{instance_key} - 终止实例
- GET /api/v1/admin/pool/metrics - 获取指标 (JSON)
- GET /api/v1/admin/pool/metrics/prometheus - 获取指标 (Prometheus)
- POST /api/v1/admin/pool/projects/{project_id}/tier - 设置项目分级
"""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse

from ..integration.session_adapter import get_global_adapter
from ..manager import AgentPoolManager
from ..metrics import get_metrics_collector
from ..types import ProjectTier

logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================


class PoolStatusResponse(BaseModel):
    """池状态响应."""

    enabled: bool = Field(..., description="池管理是否启用")
    status: str = Field(..., description="池状态 (running/stopped)")
    total_instances: int = Field(..., description="总实例数")
    hot_instances: int = Field(..., description="HOT tier 实例数")
    warm_instances: int = Field(..., description="WARM tier 实例数")
    cold_instances: int = Field(..., description="COLD tier 实例数")
    ready_instances: int = Field(..., description="就绪实例数")
    executing_instances: int = Field(..., description="执行中实例数")
    unhealthy_instances: int = Field(..., description="不健康实例数")
    prewarm_pool: dict[str, int] = Field(..., description="预热池状态")
    resource_usage: dict[str, Any] = Field(..., description="资源使用情况")


class InstanceInfo(BaseModel):
    """实例信息."""

    instance_key: str = Field(..., description="实例键")
    tenant_id: str = Field(..., description="租户ID")
    project_id: str = Field(..., description="项目ID")
    agent_mode: str = Field(..., description="Agent模式")
    tier: str = Field(..., description="分级")
    status: str = Field(..., description="状态")
    created_at: str | None = Field(None, description="创建时间")
    last_request_at: str | None = Field(None, description="最后请求时间")
    active_requests: int = Field(0, description="活跃请求数")
    total_requests: int = Field(0, description="总请求数")
    memory_used_mb: float = Field(0.0, description="内存使用 (MB)")
    health_status: str = Field("unknown", description="健康状态")


class InstanceListResponse(BaseModel):
    """实例列表响应."""

    instances: list[InstanceInfo] = Field(..., description="实例列表")
    total: int = Field(..., description="总数")
    page: int = Field(1, description="当前页")
    page_size: int = Field(20, description="每页大小")


class SetTierRequest(BaseModel):
    """设置分级请求."""

    tier: str = Field(..., description="目标分级 (hot/warm/cold)")


class SetTierResponse(BaseModel):
    """设置分级响应."""

    project_id: str = Field(..., description="项目ID")
    previous_tier: str | None = Field(None, description="之前的分级")
    current_tier: str = Field(..., description="当前分级")
    message: str = Field(..., description="操作结果")


class MetricsResponse(BaseModel):
    """指标响应 (JSON 格式)."""

    instances: dict[str, Any] = Field(..., description="实例指标")
    health: dict[str, Any] = Field(..., description="健康指标")
    prewarm: dict[str, Any] = Field(..., description="预热池指标")


class OperationResponse(BaseModel):
    """通用操作响应."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="操作结果消息")


# ============================================================================
# Dependency helpers (shared across endpoint handlers)
# ============================================================================

# Module-level reference set by create_pool_router
_pool_manager_ref: AgentPoolManager | None = None


async def _get_pool_manager_optional() -> AgentPoolManager | None:
    """获取池管理器 (可选，不抛出异常)."""
    if _pool_manager_ref:
        return _pool_manager_ref

    try:
        adapter = await get_global_adapter()
        if adapter and adapter._pool_manager:
            return adapter._pool_manager
    except Exception:
        pass

    return None


async def _get_pool_manager() -> AgentPoolManager:
    """获取池管理器 (必需，抛出异常)."""
    manager = await _get_pool_manager_optional()
    if manager:
        return manager

    raise HTTPException(
        status_code=503,
        detail="Agent pool manager not available. Enable pool with AGENT_POOL_ENABLED=true",
    )


# ============================================================================
# Helper: build InstanceInfo from an instance
# ============================================================================


def _build_instance_info(instance_key: str, instance: Any) -> InstanceInfo:
    """Build an InstanceInfo from a pool instance object."""
    return InstanceInfo(
        instance_key=instance_key,
        tenant_id=instance.config.tenant_id,
        project_id=instance.config.project_id,
        agent_mode=instance.config.agent_mode,
        tier=instance.config.tier.value,
        status=instance.status.value,
        created_at=instance.created_at.isoformat() if instance.created_at else None,
        last_request_at=(
            instance.last_request_at.isoformat() if instance.last_request_at else None
        ),
        active_requests=instance._metrics.active_requests if instance._metrics else 0,
        total_requests=instance._metrics.total_requests if instance._metrics else 0,
        memory_used_mb=instance._metrics.memory_used_mb if instance._metrics else 0.0,
        health_status=instance._last_health_status.value
        if instance._last_health_status
        else "unknown",
    )


# ============================================================================
# Helper: build a "disabled" or "initializing" PoolStatusResponse
# ============================================================================

_EMPTY_PREWARM: dict[str, int] = {"l1": 0, "l2": 0, "l3": 0}
_EMPTY_RESOURCE: dict[str, Any] = {
    "total_memory_mb": 0,
    "used_memory_mb": 0,
    "total_cpu_cores": 0,
    "used_cpu_cores": 0,
}


def _empty_pool_status(enabled: bool, status: str) -> PoolStatusResponse:
    """Return a PoolStatusResponse with zero counts."""
    return PoolStatusResponse(
        enabled=enabled,
        status=status,
        total_instances=0,
        hot_instances=0,
        warm_instances=0,
        cold_instances=0,
        ready_instances=0,
        executing_instances=0,
        unhealthy_instances=0,
        prewarm_pool=dict(_EMPTY_PREWARM),
        resource_usage=dict(_EMPTY_RESOURCE),
    )


# ============================================================================
# Endpoint handlers (module-level async functions)
# ============================================================================


async def _get_pool_status() -> PoolStatusResponse:
    """获取池状态概览.

    此端点始终返回200，即使池未启用也会返回disabled状态。
    """
    from src.configuration.config import get_settings

    settings = get_settings()

    # 如果池未启用，返回disabled状态
    if not settings.agent_pool_enabled:
        return _empty_pool_status(enabled=False, status="disabled")

    # 尝试获取池管理器
    manager = await _get_pool_manager_optional()
    if not manager:
        return _empty_pool_status(enabled=True, status="initializing")

    stats = manager.get_stats()

    return PoolStatusResponse(
        enabled=True,
        status="running",
        total_instances=stats.total_instances,
        hot_instances=stats.hot_instances,
        warm_instances=stats.warm_instances,
        cold_instances=stats.cold_instances,
        ready_instances=stats.ready_instances,
        executing_instances=stats.executing_instances,
        unhealthy_instances=stats.unhealthy_instances,
        prewarm_pool={
            "l1": stats.prewarm_l1_count,
            "l2": stats.prewarm_l2_count,
            "l3": stats.prewarm_l3_count,
        },
        resource_usage={
            "total_memory_mb": stats.total_memory_mb,
            "used_memory_mb": stats.used_memory_mb,
            "total_cpu_cores": stats.total_cpu_cores,
            "used_cpu_cores": stats.used_cpu_cores,
        },
    )


async def _list_instances(
    manager: AgentPoolManager = Depends(_get_pool_manager),
    tier: str | None = Query(None, description="按分级筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页大小"),
) -> InstanceListResponse:
    """列出所有实例."""
    all_instances = []

    # 从池管理器获取实例
    for instance_key, instance in manager._instances.items():
        if tier and instance.config.tier.value != tier:
            continue
        if status and instance.status.value != status:
            continue

        all_instances.append(_build_instance_info(instance_key, instance))

    # 分页
    total = len(all_instances)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = all_instances[start:end]

    return InstanceListResponse(
        instances=paginated,
        total=total,
        page=page,
        page_size=page_size,
    )


async def _get_instance(
    instance_key: str,
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> InstanceInfo:
    """获取实例详情."""
    instance = manager._instances.get(instance_key)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance not found: {instance_key}")

    return _build_instance_info(instance_key, instance)


async def _pause_instance(
    instance_key: str,
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> OperationResponse:
    """暂停实例."""
    instance = manager._instances.get(instance_key)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance not found: {instance_key}")

    try:
        await instance.pause()
        return OperationResponse(
            success=True,
            message=f"Instance {instance_key} paused",
        )
    except Exception as e:
        logger.error(f"Failed to pause instance {instance_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _resume_instance(
    instance_key: str,
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> OperationResponse:
    """恢复实例."""
    instance = manager._instances.get(instance_key)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance not found: {instance_key}")

    try:
        await instance.resume()
        return OperationResponse(
            success=True,
            message=f"Instance {instance_key} resumed",
        )
    except Exception as e:
        logger.error(f"Failed to resume instance {instance_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _terminate_instance(
    instance_key: str,
    graceful: bool = Query(True, description="是否优雅终止"),
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> OperationResponse:
    """终止实例."""
    instance = manager._instances.get(instance_key)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Instance not found: {instance_key}")

    try:
        # 解析 instance_key
        parts = instance_key.split(":")
        if len(parts) >= 3:
            tenant_id, project_id, agent_mode = parts[0], parts[1], parts[2]
            await manager.terminate_instance(tenant_id, project_id, agent_mode)
        else:
            await instance.stop(graceful=graceful)

        return OperationResponse(
            success=True,
            message=f"Instance {instance_key} terminated",
        )
    except Exception as e:
        logger.error(f"Failed to terminate instance {instance_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


async def _set_project_tier(
    project_id: str,
    request: SetTierRequest,
    tenant_id: str = Query(..., description="租户ID"),
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> SetTierResponse:
    """设置项目分级."""
    # 验证 tier
    try:
        new_tier = ProjectTier(request.tier)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier: {request.tier}. Must be one of: hot, warm, cold",
        ) from None

    # 获取当前分级
    current_tier = await manager.classify_project(tenant_id, project_id)

    # 设置新分级
    await manager.set_project_tier(tenant_id, project_id, new_tier)

    return SetTierResponse(
        project_id=project_id,
        previous_tier=current_tier.value if current_tier else None,
        current_tier=new_tier.value,
        message=f"Project tier updated from {current_tier.value if current_tier else 'auto'} to {new_tier.value}",
    )


async def _get_project_tier(
    project_id: str,
    tenant_id: str = Query(..., description="租户ID"),
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> dict[str, Any]:
    """获取项目分级."""
    tier = await manager.classify_project(tenant_id, project_id)
    return {
        "project_id": project_id,
        "tenant_id": tenant_id,
        "tier": tier.value,
    }


async def _get_metrics_json(
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> MetricsResponse:
    """获取指标 (JSON 格式)."""
    metrics = get_metrics_collector()
    stats = manager.get_stats()
    metrics.update_from_pool_stats(stats)

    data = metrics.to_dict()
    return MetricsResponse(
        instances=data.get("instances", {}),
        health=data.get("health", {}),
        prewarm=data.get("prewarm", {}),
    )


async def _get_metrics_prometheus(
    manager: AgentPoolManager = Depends(_get_pool_manager),
) -> PlainTextResponse:
    """获取指标 (Prometheus 格式)."""
    from fastapi.responses import PlainTextResponse

    metrics = get_metrics_collector()
    stats = manager.get_stats()
    metrics.update_from_pool_stats(stats)

    return PlainTextResponse(
        content=metrics.to_prometheus_format(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ============================================================================
# Router Factory
# ============================================================================


def create_pool_router(
    pool_manager: AgentPoolManager | None = None,
    prefix: str = "/api/v1/admin/pool",
    tags: list[str] | None = None,
) -> APIRouter:
    """创建池管理 API 路由器.

    Args:
        pool_manager: 可选的池管理器实例，如果不提供则使用全局适配器
        prefix: API 前缀
        tags: OpenAPI 标签

    Returns:
        FastAPI 路由器
    """
    global _pool_manager_ref
    _pool_manager_ref = pool_manager

    router = APIRouter(
        prefix=prefix,
        tags=cast("list[str | Enum]", tags or ["Agent Pool Admin"]),
    )

    # Status
    router.get("/status", response_model=PoolStatusResponse)(_get_pool_status)

    # Instances
    router.get("/instances", response_model=InstanceListResponse)(_list_instances)
    router.get("/instances/{instance_key}", response_model=InstanceInfo)(_get_instance)
    router.post("/instances/{instance_key}/pause", response_model=OperationResponse)(
        _pause_instance
    )
    router.post("/instances/{instance_key}/resume", response_model=OperationResponse)(
        _resume_instance
    )
    router.delete("/instances/{instance_key}", response_model=OperationResponse)(
        _terminate_instance
    )

    # Tier
    router.post("/projects/{project_id}/tier", response_model=SetTierResponse)(_set_project_tier)
    router.get("/projects/{project_id}/tier")(_get_project_tier)

    # Metrics
    router.get("/metrics", response_model=MetricsResponse)(_get_metrics_json)
    router.get("/metrics/prometheus", response_class=PlainTextResponse)(_get_metrics_prometheus)

    return router
