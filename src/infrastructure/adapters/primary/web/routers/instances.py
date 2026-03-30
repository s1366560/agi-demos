"""Instance Management API endpoints."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.deploy_schemas import DeployResponse
from src.application.schemas.instance_schemas import (
    InstanceCreate,
    InstanceListResponse,
    InstanceMemberCreate,
    InstanceMemberResponse,
    InstanceMemberUpdate,
    InstanceResponse,
    InstanceUpdate,
    UserSearchResult,
)
from src.configuration.di_container import DIContainer
from src.domain.model.instance.enums import ServiceType
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    User as UserModel,
)

logger = logging.getLogger(__name__)


def get_container_with_db(request: Request, db: AsyncSession) -> DIContainer:
    """Get DI container with database session for the current request."""
    app_container: DIContainer = request.app.state.container
    return DIContainer(
        db=db,
        graph_service=app_container.graph_service,
        redis_client=app_container.redis_client,
    )


router = APIRouter(prefix="/api/v1/instances", tags=["Instances"])


class ScaleRequest(BaseModel):
    """Request body for scaling an instance."""

    desired_replicas: int = Field(..., ge=0, description="Desired number of replicas")


class PendingConfigRequest(BaseModel):
    """Request body for saving pending configuration."""

    pending_config: dict[str, Any] = Field(..., description="Configuration to stage")


class InstanceLlmConfigResponse(BaseModel):
    """Response body for instance LLM configuration."""

    provider_id: str | None = Field(None, description="Selected LLM provider ID")
    model_name: str | None = Field(None, description="Selected model name")
    has_api_key_override: bool = Field(False, description="Whether an API key override is set")


class InstanceLlmConfigUpdate(BaseModel):
    """Request body for updating instance LLM configuration."""

    provider_id: str | None = Field(None, description="LLM provider ID to use")
    model_name: str | None = Field(None, description="Model name to use")
    api_key_override: str | None = Field(None, description="Optional API key override")


# ------------------------------------------------------------------
# Instance CRUD
# ------------------------------------------------------------------


@router.post(
    "/",
    response_model=InstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_instance(
    request: Request,
    data: InstanceCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    """Create a new instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.create_instance(
            name=data.name,
            slug=data.slug,
            tenant_id=tenant_id,
            created_by=tenant_id,
            cluster_id=data.cluster_id,
            namespace=data.namespace,
            image_version=data.image_version,
            replicas=data.replicas,
            cpu_request=data.cpu_request,
            cpu_limit=data.cpu_limit,
            mem_request=data.mem_request,
            mem_limit=data.mem_limit,
            service_type=ServiceType(data.service_type),
            ingress_domain=data.ingress_domain,
            env_vars=data.env_vars,
            advanced_config=data.advanced_config,
            llm_providers=data.llm_providers,
            workspace_id=data.workspace_id,
        )
        await db.commit()
        return InstanceResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating instance")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.get("/", response_model=InstanceListResponse)
async def list_instances(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceListResponse:
    """List instances for the current tenant."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        offset = (page - 1) * page_size
        items = await service.list_instances(
            tenant_id=tenant_id,
            limit=page_size,
            offset=offset,
        )
        return InstanceListResponse(
            instances=[InstanceResponse.model_validate(i, from_attributes=True) for i in items],
            total=len(items),
            page=page,
            page_size=page_size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing instances")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    """Get a specific instance by ID."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.get_instance(instance_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )
        return InstanceResponse.model_validate(result, from_attributes=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting instance")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.put("/{instance_id}", response_model=InstanceResponse)
async def update_instance(
    request: Request,
    instance_id: str,
    data: InstanceUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    """Update an existing instance."""
    try:
        svc_type: ServiceType | None = None
        if data.service_type is not None:
            svc_type = ServiceType(data.service_type)

        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.update_instance(
            instance_id,
            name=data.name,
            image_version=data.image_version,
            replicas=data.replicas,
            cpu_request=data.cpu_request,
            cpu_limit=data.cpu_limit,
            mem_request=data.mem_request,
            mem_limit=data.mem_limit,
            service_type=svc_type,
            ingress_domain=data.ingress_domain,
            env_vars=data.env_vars,
            advanced_config=data.advanced_config,
            llm_providers=data.llm_providers,
            workspace_id=data.workspace_id,
            agent_display_name=data.agent_display_name,
            agent_label=data.agent_label,
            theme_color=data.theme_color,
        )
        await db.commit()
        return InstanceResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating instance")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.delete(
    "/{instance_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_instance(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        await service.delete_instance(instance_id)
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting instance")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


# ------------------------------------------------------------------
# Scaling & Restart
# ------------------------------------------------------------------


@router.post(
    "/{instance_id}/scale",
    response_model=DeployResponse,
)
async def scale_instance(
    request: Request,
    instance_id: str,
    data: ScaleRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Scale an instance to a desired replica count."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.scale_instance(
            instance_id=instance_id,
            replicas=data.desired_replicas,
            triggered_by=tenant_id,
        )
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error scaling instance")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.post(
    "/{instance_id}/restart",
    response_model=DeployResponse,
)
async def restart_instance(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Restart an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.restart_instance(
            instance_id=instance_id,
            triggered_by=tenant_id,
        )
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error restarting instance")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------


@router.put(
    "/{instance_id}/config/pending",
    response_model=InstanceResponse,
)
async def save_pending_config(
    request: Request,
    instance_id: str,
    data: PendingConfigRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    """Save pending configuration for an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.save_pending_config(
            instance_id=instance_id,
            config=data.pending_config,
        )
        await db.commit()
        return InstanceResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error saving pending config")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.post(
    "/{instance_id}/config/apply",
    response_model=DeployResponse,
)
async def apply_pending_config(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> DeployResponse:
    """Apply the pending configuration and create a deploy record."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.apply_pending_config(
            instance_id=instance_id,
            triggered_by=tenant_id,
        )
        await db.commit()
        return DeployResponse.model_validate(result, from_attributes=True)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error applying pending config")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


# ------------------------------------------------------------------
# Member Management
# ------------------------------------------------------------------


@router.post(
    "/{instance_id}/members",
    response_model=InstanceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    request: Request,
    instance_id: str,
    data: InstanceMemberCreate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceMemberResponse:
    """Add a member to an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.add_member(
            instance_id=instance_id,
            user_id=data.user_id,
            role=data.role,
        )
        await db.commit()

        user_row = await db.execute(select(UserModel).where(UserModel.id == data.user_id))
        user = user_row.scalar_one_or_none()
        return InstanceMemberResponse(
            id=result.id,
            instance_id=result.instance_id,
            user_id=result.user_id,
            role=result.role.value if hasattr(result.role, "value") else str(result.role),
            user_name=user.full_name if user else None,
            user_email=user.email if user else None,
            user_avatar_url=None,
            created_at=result.created_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error adding member")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.get(
    "/{instance_id}/members/search-users",
    response_model=list[UserSearchResult],
)
async def search_users(
    request: Request,
    instance_id: str,
    q: str = Query("", description="Search query for email or name"),
    limit: int = Query(20, ge=1, le=100),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[UserSearchResult]:
    """Search for users that can be added to an instance."""
    try:
        query = select(UserModel).where(
            UserModel.is_active.is_(True),
        )
        if q:
            pattern = f"%{q}%"
            query = query.where(UserModel.email.ilike(pattern) | UserModel.full_name.ilike(pattern))
        query = query.limit(limit)
        result = await db.execute(query)
        users = result.scalars().all()
        return [
            UserSearchResult(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
            )
            for u in users
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error searching users")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.put(
    "/{instance_id}/members/{member_id}",
    response_model=InstanceMemberResponse,
)
async def update_member_role(
    request: Request,
    instance_id: str,
    member_id: str,
    data: InstanceMemberUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceMemberResponse:
    """Update a member's role in an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        result = await service.update_member_role(
            instance_id=instance_id,
            member_id=member_id,
            role=data.role,
        )
        await db.commit()

        user_row = await db.execute(select(UserModel).where(UserModel.id == result.user_id))
        user = user_row.scalar_one_or_none()
        return InstanceMemberResponse(
            id=result.id,
            instance_id=result.instance_id,
            user_id=result.user_id,
            role=result.role.value if hasattr(result.role, "value") else str(result.role),
            user_name=user.full_name if user else None,
            user_email=user.email if user else None,
            user_avatar_url=None,
            created_at=result.created_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating member role")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.delete(
    "/{instance_id}/members/{user_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    request: Request,
    instance_id: str,
    user_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a member from an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        await service.remove_member(
            instance_id=instance_id,
            user_id=user_id,
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error removing member")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.get(
    "/{instance_id}/members",
    response_model=list[InstanceMemberResponse],
)
async def list_members(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[InstanceMemberResponse]:
    """List all members of an instance."""
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        members = await service.list_members(instance_id)

        user_ids = [m.user_id for m in members]
        user_map: dict[str, UserModel] = {}
        if user_ids:
            user_result = await db.execute(select(UserModel).where(UserModel.id.in_(user_ids)))
            for u in user_result.scalars().all():
                user_map[u.id] = u

        return [
            InstanceMemberResponse(
                id=m.id,
                instance_id=m.instance_id,
                user_id=m.user_id,
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                user_name=user_map[m.user_id].full_name if m.user_id in user_map else None,
                user_email=user_map[m.user_id].email if m.user_id in user_map else None,
                user_avatar_url=None,
                created_at=m.created_at,
            )
            for m in members
        ]
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing members")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


# ------------------------------------------------------------------
# Instance LLM Configuration
# ------------------------------------------------------------------


@router.get(
    "/{instance_id}/llm-config",
    response_model=InstanceLlmConfigResponse,
)
async def get_instance_llm_config(
    request: Request,
    instance_id: str,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceLlmConfigResponse:
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        instance = await service.get_instance(instance_id)
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )
        llm_cfg = instance.llm_providers or {}
        return InstanceLlmConfigResponse(
            provider_id=llm_cfg.get("provider_id"),
            model_name=llm_cfg.get("model_name"),
            has_api_key_override=bool(llm_cfg.get("api_key_override")),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting instance LLM config")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e


@router.put(
    "/{instance_id}/llm-config",
    response_model=InstanceLlmConfigResponse,
)
async def update_instance_llm_config(
    request: Request,
    instance_id: str,
    data: InstanceLlmConfigUpdate,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceLlmConfigResponse:
    try:
        container = get_container_with_db(request, db)
        service = container.instance_service()
        instance = await service.get_instance(instance_id)
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Instance not found",
            )
        llm_cfg: dict[str, Any] = dict(instance.llm_providers or {})
        llm_cfg["provider_id"] = data.provider_id
        llm_cfg["model_name"] = data.model_name
        if data.api_key_override is not None:
            llm_cfg["api_key_override"] = data.api_key_override
        elif "api_key_override" not in llm_cfg:
            llm_cfg["api_key_override"] = None
        await service.update_instance(instance_id, llm_providers=llm_cfg)
        await db.commit()
        return InstanceLlmConfigResponse(
            provider_id=llm_cfg.get("provider_id"),
            model_name=llm_cfg.get("model_name"),
            has_api_key_override=bool(llm_cfg.get("api_key_override")),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating instance LLM config")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from e
