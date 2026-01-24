"""
LLM Provider Management API endpoints.

Provides REST API for managing LLM provider configurations,
including CRUD operations, health checks, and tenant assignments.
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.provider_service import ProviderService, get_provider_service
from src.domain.llm_providers.models import (
    NoActiveProviderError,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
    ProviderHealth,
    ProviderType,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/llm-providers", tags=["LLM Providers"])


async def get_provider_service_with_session(
    session: AsyncSession = Depends(get_db),
) -> ProviderService:
    """Dependency that provides ProviderService with injected database session."""
    return get_provider_service(session=session)


async def require_admin(current_user: User = Depends(get_current_user)):
    """Dependency to require admin role."""
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# Provider CRUD Endpoints


@router.post(
    "/",
    response_model=ProviderConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    config: ProviderConfigCreate,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderConfigResponse:
    """
    Create a new LLM provider configuration.

    Requires admin access.
    """
    try:
        provider = await service.create_provider(config)
        logger.info(f"Provider created: {provider.id} by user {current_user.id}")
        return await service.get_provider_response(provider.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/", response_model=List[ProviderConfigResponse])
async def list_providers(
    include_inactive: bool = Query(False, description="Include inactive providers"),
    current_user: User = Depends(get_current_user),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> List[ProviderConfigResponse]:
    """
    List all LLM providers.

    Regular users can only view active providers.
    Admins can view all providers.
    """
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    if not is_admin:
        include_inactive = False

    providers = await service.list_providers(include_inactive=include_inactive)
    return [await service.get_provider_response(p.id) for p in providers]


# Static routes must be defined before dynamic /{provider_id} route


@router.get("/types", response_model=List[str])
async def list_provider_types(
    current_user: User = Depends(get_current_user),
) -> List[str]:
    """
    List all supported provider types.
    """
    return [t.value for t in ProviderType]


@router.get("/models/{provider_type}")
async def list_models_for_provider_type(
    provider_type: str,
    current_user: User = Depends(get_current_user),
):
    """
    List available models for a given provider type.

    Returns common model names for the provider.
    """
    # Common models for each provider type
    models = {
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo", "text-embedding-3-small"],
        "qwen": ["qwen-plus", "qwen-turbo", "text-embedding-v3"],
        "gemini": ["gemini-1.5-pro", "gemini-1.5-flash"],
        "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
        "groq": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    }

    if provider_type not in models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider type: {provider_type}",
        )

    return {
        "provider_type": provider_type,
        "models": models[provider_type],
    }


@router.get("/{provider_id}", response_model=ProviderConfigResponse)
async def get_provider(
    provider_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderConfigResponse:
    """
    Get a specific provider by ID.

    Regular users can only view active providers.
    Admins can view all providers.
    """
    provider_response = await service.get_provider_response(provider_id)
    if not provider_response:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    # Check if provider is active (non-admins can't see inactive providers)
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    if not is_admin and not provider_response.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    return provider_response


@router.put("/{provider_id}", response_model=ProviderConfigResponse)
async def update_provider(
    provider_id: UUID,
    config: ProviderConfigUpdate,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderConfigResponse:
    """
    Update a provider configuration.

    Requires admin access.
    """
    updated = await service.update_provider(provider_id, config)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    logger.info(f"Provider updated: {provider_id} by user {current_user.id}")
    return await service.get_provider_response(provider_id)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: UUID,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
):
    """
    Delete (soft delete) a provider configuration.

    Requires admin access.
    """
    success = await service.delete_provider(provider_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )

    logger.info(f"Provider deleted: {provider_id} by user {current_user.id}")


# Health Check Endpoints


@router.post("/{provider_id}/health-check", response_model=ProviderHealth)
async def check_provider_health(
    provider_id: UUID,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderHealth:
    """
    Trigger a health check for a provider.

    Requires admin access.
    """
    try:
        health = await service.check_provider_health(provider_id)
        logger.info(f"Health check completed for provider {provider_id}: {health.status}")
        return health
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.get("/{provider_id}/health", response_model=ProviderHealth)
async def get_provider_health(
    provider_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderHealth:
    """
    Get the latest health status for a provider.
    """
    health = await service.repository.get_latest_health(provider_id)

    if not health:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No health data available for this provider",
        )

    return health


# Tenant Assignment Endpoints


@router.post("/tenants/{tenant_id}/providers/{provider_id}")
async def assign_provider_to_tenant(
    tenant_id: str,
    provider_id: UUID,
    priority: int = Query(0, description="Priority for fallback (lower = higher priority)"),
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
):
    """
    Assign a provider to a specific tenant.

    Requires admin access.
    """
    try:
        mapping = await service.assign_provider_to_tenant(tenant_id, provider_id, priority)
        logger.info(
            f"Provider {provider_id} assigned to tenant {tenant_id} by user {current_user.id}"
        )
        return {
            "message": "Provider assigned to tenant",
            "mapping_id": str(mapping.id),
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/tenants/{tenant_id}/provider", response_model=ProviderConfigResponse)
async def get_tenant_provider(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderConfigResponse:
    """
    Get the provider assigned to a specific tenant.

    Returns the resolved provider based on fallback hierarchy.
    """
    try:
        provider = await service.resolve_provider_for_tenant(tenant_id)
        return await service.get_provider_response(provider.id)
    except NoActiveProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.delete("/tenants/{tenant_id}/providers/{provider_id}")
async def unassign_provider_from_tenant(
    tenant_id: str,
    provider_id: UUID,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
):
    """
    Unassign a provider from a tenant.

    Requires admin access.
    """
    success = await service.unassign_provider_from_tenant(tenant_id, provider_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant-provider mapping not found",
        )

    logger.info(
        f"Provider {provider_id} unassigned from tenant {tenant_id} by user {current_user.id}"
    )
    return {"message": "Provider unassigned from tenant"}


# Usage Statistics Endpoints


@router.get("/{provider_id}/usage")
async def get_provider_usage(
    provider_id: UUID,
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    operation_type: Optional[str] = Query(None, description="Filter by operation type"),
    current_user: User = Depends(get_current_user),
    service: ProviderService = Depends(get_provider_service_with_session),
):
    """
    Get usage statistics for a provider.

    Regular users can only see usage for their tenant.
    Admins can see all usage.
    """
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    tenant_id = None if is_admin else current_user.tenant_id

    stats = await service.get_usage_statistics(
        provider_id=provider_id,
        tenant_id=tenant_id,
        operation_type=operation_type,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "provider_id": str(provider_id),
        "tenant_id": tenant_id,
        "statistics": [s.model_dump() for s in stats],
    }
