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
from typing import Any

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
    router = APIRouter(
        prefix=prefix,
        tags=tags or ["Agent Pool Admin"],
    )

    async def get_pool_manager_optional() -> AgentPoolManager | None:
        """获取池管理器 (可选，不抛出异常)."""
        if pool_manager:
            return pool_manager

        try:
            adapter = await get_global_adapter()
            if adapter and adapter._pool_manager:
                return adapter._pool_manager
        except Exception:
            pass

        return None

    async def get_pool_manager() -> AgentPoolManager:
        """获取池管理器 (必需，抛出异常)."""
        manager = await get_pool_manager_optional()
        if manager:
            return manager

        raise HTTPException(
            status_code=503,
            detail="Agent pool manager not available. Enable pool with AGENT_POOL_ENABLED=true",
        )

    # ========================================================================
    # Status Endpoints
    # ========================================================================

    @router.get("/status", response_model=PoolStatusResponse)
    async def get_pool_status() -> PoolStatusResponse:
        """获取池状态概览.

        此端点始终返回200，即使池未启用也会返回disabled状态。
        """
        from src.configuration.config import get_settings

        settings = get_settings()

        # 如果池未启用，返回disabled状态
        if not settings.agent_pool_enabled:
            return PoolStatusResponse(
                enabled=False,
                status="disabled",
                total_instances=0,
                hot_instances=0,
                warm_instances=0,
                cold_instances=0,
                ready_instances=0,
                executing_instances=0,
                unhealthy_instances=0,
                prewarm_pool={"l1": 0, "l2": 0, "l3": 0},
                resource_usage={
                    "total_memory_mb": 0,
                    "used_memory_mb": 0,
                    "total_cpu_cores": 0,
                    "used_cpu_cores": 0,
                },
            )

        # 尝试获取池管理器
        manager = await get_pool_manager_optional()
        if not manager:
            return PoolStatusResponse(
                enabled=True,
                status="initializing",
                total_instances=0,
                hot_instances=0,
                warm_instances=0,
                cold_instances=0,
                ready_instances=0,
                executing_instances=0,
                unhealthy_instances=0,
                prewarm_pool={"l1": 0, "l2": 0, "l3": 0},
                resource_usage={
                    "total_memory_mb": 0,
                    "used_memory_mb": 0,
                    "total_cpu_cores": 0,
                    "used_cpu_cores": 0,
                },
            )

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

    # ========================================================================
    # Instance Endpoints
    # ========================================================================

    @router.get("/instances", response_model=InstanceListResponse)
    async def list_instances(
        manager: AgentPoolManager = Depends(get_pool_manager),
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

            info = InstanceInfo(
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
            all_instances.append(info)

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

    @router.get("/instances/{instance_key}", response_model=InstanceInfo)
    async def get_instance(
        instance_key: str,
        manager: AgentPoolManager = Depends(get_pool_manager),
    ) -> InstanceInfo:
        """获取实例详情."""
        instance = manager._instances.get(instance_key)
        if not instance:
            raise HTTPException(status_code=404, detail=f"Instance not found: {instance_key}")

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

    @router.post("/instances/{instance_key}/pause", response_model=OperationResponse)
    async def pause_instance(
        instance_key: str,
        manager: AgentPoolManager = Depends(get_pool_manager),
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

    @router.post("/instances/{instance_key}/resume", response_model=OperationResponse)
    async def resume_instance(
        instance_key: str,
        manager: AgentPoolManager = Depends(get_pool_manager),
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

    @router.delete("/instances/{instance_key}", response_model=OperationResponse)
    async def terminate_instance(
        instance_key: str,
        graceful: bool = Query(True, description="是否优雅终止"),
        manager: AgentPoolManager = Depends(get_pool_manager),
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

    # ========================================================================
    # Tier Endpoints
    # ========================================================================

    @router.post("/projects/{project_id}/tier", response_model=SetTierResponse)
    async def set_project_tier(
        project_id: str,
        request: SetTierRequest,
        tenant_id: str = Query(..., description="租户ID"),
        manager: AgentPoolManager = Depends(get_pool_manager),
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

    @router.get("/projects/{project_id}/tier")
    async def get_project_tier(
        project_id: str,
        tenant_id: str = Query(..., description="租户ID"),
        manager: AgentPoolManager = Depends(get_pool_manager),
    ) -> dict[str, Any]:
        """获取项目分级."""
        tier = await manager.classify_project(tenant_id, project_id)
        return {
            "project_id": project_id,
            "tenant_id": tenant_id,
            "tier": tier.value,
        }

    # ========================================================================
    # Metrics Endpoints
    # ========================================================================

    @router.get("/metrics", response_model=MetricsResponse)
    async def get_metrics_json(
        manager: AgentPoolManager = Depends(get_pool_manager),
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

    @router.get("/metrics/prometheus", response_class=None)
    async def get_metrics_prometheus(
        manager: AgentPoolManager = Depends(get_pool_manager),
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

    return router
