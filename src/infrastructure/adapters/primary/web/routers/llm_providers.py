"""
LLM Provider Management API endpoints.

Provides REST API for managing LLM provider configurations,
including CRUD operations, health checks, and tenant assignments.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.services.provider_service import ProviderService, get_provider_service
from src.domain.llm_providers.models import (
    NoActiveProviderError,
    OperationType,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
    ProviderHealth,
    ProviderType,
    TenantProviderMapping,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/llm-providers", tags=["LLM Providers"])


async def get_provider_service_with_session(
    session: AsyncSession = Depends(get_db),
) -> ProviderService:
    """Dependency that provides ProviderService with injected database session."""
    return get_provider_service(session=session)


async def get_current_user_with_roles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get current user with roles eagerly loaded.

    This is needed because the base get_current_user doesn't load roles
    to reduce query overhead, but this router needs role checks.
    """
    result = await db.execute(
        select(User)
        .where(User.id == current_user.id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    return result.scalar_one()


async def require_admin(current_user: User = Depends(get_current_user_with_roles)) -> User:
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
) -> ProviderConfigResponse | None:
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
        ) from e


@router.get("/", response_model=list[ProviderConfigResponse])
async def list_providers(
    include_inactive: bool = Query(False, description="Include inactive providers"),
    current_user: User = Depends(get_current_user_with_roles),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> list[ProviderConfigResponse]:
    """
    List all LLM providers.

    Regular users can only view active providers.
    Admins can view all providers.
    """
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    if not is_admin:
        include_inactive = False

    providers = await service.list_providers(include_inactive=include_inactive)
    return [r for p in providers if (r := await service.get_provider_response(p.id)) is not None]


# Static routes must be defined before dynamic /{provider_id} route


@router.get("/types", response_model=list[str])
async def list_provider_types(
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """
    List all supported provider types.
    """
    return [t.value for t in ProviderType]


# Model Catalog Endpoints (MUST be before /models/{provider_type}
# to avoid the path parameter catching 'catalog' as a provider_type)


@router.get("/models/catalog")
async def list_catalog_models(
    provider: str | None = Query(None, description="Filter by provider name"),
    include_deprecated: bool = Query(False, description="Include deprecated models"),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List all models from the model catalog.

    Returns enriched metadata from the embedded model snapshot.
    """
    from src.infrastructure.llm.model_catalog import (
        get_model_catalog_service,
    )

    catalog = get_model_catalog_service()
    models = catalog.list_models(
        provider=provider,
        include_deprecated=include_deprecated,
    )
    # Exclude internal-only fields from API response
    exclude_fields = {"input_budget_ratio", "chars_per_token", "interleaved"}
    return {
        "total": len(models),
        "models": [
            {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in m.model_dump().items()
                if k not in exclude_fields
            }
            for m in models
        ],
    }


@router.get("/models/catalog/search")
async def search_catalog_models(
    q: str = Query(..., description="Search query"),
    provider: str | None = Query(None, description="Filter by provider name"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Search models in the catalog by name, family, or description.
    """
    from src.infrastructure.llm.model_catalog import (
        get_model_catalog_service,
    )

    catalog = get_model_catalog_service()
    results = catalog.search_models(query=q, provider=provider, limit=limit)
    exclude_fields = {"input_budget_ratio", "chars_per_token", "interleaved"}
    return {
        "query": q,
        "total": len(results),
        "models": [
            {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in m.model_dump().items()
                if k not in exclude_fields
            }
            for m in results
        ],
    }


@router.get("/models/{provider_type}")
async def list_models_for_provider_type(
    provider_type: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List available models for a given provider type.

    Returns categorized models (chat, embedding, rerank) for the provider.
    """
    # Categorized models for each provider type
    models_data = {
        "openai": {
            "chat": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
            "embedding": ["text-embedding-3-small", "text-embedding-3-large"],
            "rerank": [],
        },
        "dashscope": {
            "chat": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
            "embedding": ["text-embedding-v3", "text-embedding-v2"],
            "rerank": ["qwen3-rerank", "qwen-turbo"],
        },
        "zai": {
            "chat": ["glm-4-plus", "glm-4-flash", "glm-4-air"],
            "embedding": ["embedding-3", "embedding-2"],
            "rerank": ["glm-4-flash"],
        },
        "kimi": {
            "chat": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            "embedding": ["kimi-embedding-1"],
            "rerank": ["kimi-rerank-1"],
        },
        "ollama": {
            "chat": ["llama3.1:8b", "qwen2.5:7b", "mistral-nemo"],
            "embedding": ["nomic-embed-text"],
            "rerank": ["llama3.1:8b"],
        },
        "lmstudio": {
            "chat": ["local-model"],
            "embedding": ["text-embedding-nomic-embed-text-v1.5"],
            "rerank": ["local-model"],
        },
        "gemini": {
            "chat": [
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.5-pro-002",
                "gemini-1.5-flash-002",
            ],
            "embedding": ["text-embedding-004"],
            "rerank": ["gemini-1.5-flash"],
        },
        "anthropic": {
            "chat": [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
            "embedding": [],
            "rerank": ["claude-3-5-haiku-20241022"],
        },
        "groq": {
            "chat": [
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
                "mixtral-8x7b-32768",
                "llama-3.1-8b-instant",
            ],
            "embedding": [],
            "rerank": [],
        },
        "deepseek": {
            "chat": ["deepseek-chat", "deepseek-coder"],
            "embedding": [],
            "rerank": ["deepseek-chat"],
        },
        "minimax": {
            "chat": ["abab6.5-chat", "abab6.5s-chat", "MiniMax-Text-01"],
            "embedding": ["embo-01"],
            "rerank": ["abab6.5-chat"],
        },
        "cohere": {
            "chat": ["command-r-plus", "command-r"],
            "embedding": ["embed-english-v3.0", "embed-multilingual-v3.0"],
            "rerank": ["rerank-english-v3.0", "rerank-multilingual-v3.0"],
        },
        "mistral": {
            "chat": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
            "embedding": ["mistral-embed"],
            "rerank": ["mistral-small-latest"],
        },
        "azure_openai": {
            "chat": ["gpt-4o", "gpt-4", "gpt-4o-mini", "gpt-35-turbo"],
            "embedding": ["text-embedding-3-small", "text-embedding-ada-002"],
            "rerank": [],
        },
        "bedrock": {
            "chat": [
                "anthropic.claude-3-sonnet-20240229-v1:0",
                "anthropic.claude-3-haiku-20240307-v1:0",
                "meta.llama3-70b-instruct-v1:0",
            ],
            "embedding": ["amazon.titan-embed-text-v1", "amazon.titan-embed-text-v2:0"],
            "rerank": [],
        },
        "vertex": {
            "chat": ["gemini-1.5-pro", "gemini-1.5-flash"],
            "embedding": ["textembedding-gecko"],
            "rerank": [],
        },
    }

    if provider_type not in models_data:
        # Return empty lists for unknown providers instead of error
        # This allows frontend to fallback to defaults or show empty dropdowns
        return {
            "provider_type": provider_type,
            "models": {"chat": [], "embedding": [], "rerank": []},
        }

    return {
        "provider_type": provider_type,
        "models": models_data[provider_type],
    }


@router.get("/env-detection")
async def detect_env_providers(
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """
    Detect LLM providers configured via environment variables.

    Returns provider configs found in server env vars for auto-fill.
    Requires admin access since it exposes API key values.
    """
    from src.infrastructure.llm.initializer import detect_env_providers as _detect

    detected = _detect()
    return {
        "detected_providers": {
            name: {
                "provider_type": name,
                "api_key": config.get("api_key"),
                "base_url": config.get("base_url"),
                "llm_model": config.get("llm_model"),
                "llm_small_model": config.get("llm_small_model"),
                "embedding_model": config.get("embedding_model"),
                "reranker_model": config.get("reranker_model"),
            }
            for name, config in detected.items()
        },
    }


@router.get("/{provider_id}", response_model=ProviderConfigResponse)
async def get_provider(
    provider_id: UUID,
    current_user: User = Depends(get_current_user_with_roles),
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
) -> ProviderConfigResponse | None:
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
) -> None:
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
        ) from e


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


@router.get("/tenants/{tenant_id}/assignments", response_model=list[TenantProviderMapping])
async def list_tenant_assignments(
    tenant_id: str,
    operation_type: OperationType | None = Query(
        None, description="Filter by operation type: llm, embedding, rerank"
    ),
    current_user: User = Depends(get_current_user_with_roles),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> list[TenantProviderMapping]:
    """
    List all provider assignments for a tenant.
    """
    # Check permissions: admin or user belongs to tenant
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    if not is_admin and current_user.tenant_id != tenant_id:  # type: ignore[attr-defined]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to tenant assignments",
        )

    return await service.get_tenant_providers(tenant_id, operation_type)


@router.post("/tenants/{tenant_id}/providers/{provider_id}")
async def assign_provider_to_tenant(
    tenant_id: str,
    provider_id: UUID,
    priority: int = Query(0, description="Priority for fallback (lower = higher priority)"),
    operation_type: OperationType = Query(
        OperationType.LLM,
        description="Operation type mapping: llm, embedding, rerank",
    ),
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> dict[str, Any]:
    """
    Assign a provider to a specific tenant.

    Requires admin access.
    """
    try:
        mapping = await service.assign_provider_to_tenant(
            tenant_id,
            provider_id,
            priority,
            operation_type,
        )
        logger.info(
            f"Provider {provider_id} assigned to tenant {tenant_id} by user {current_user.id}"
        )
        return {
            "message": "Provider assigned to tenant",
            "mapping_id": str(mapping.id),
            "operation_type": mapping.operation_type,
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.get("/tenants/{tenant_id}/provider", response_model=ProviderConfigResponse)
async def get_tenant_provider(
    tenant_id: str,
    operation_type: OperationType = Query(
        OperationType.LLM,
        description="Operation type to resolve: llm, embedding, rerank",
    ),
    current_user: User = Depends(get_current_user),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderConfigResponse | None:
    """
    Get the provider assigned to a specific tenant.

    Returns the resolved provider based on fallback hierarchy.
    """
    try:
        provider = await service.resolve_provider_for_tenant(tenant_id, operation_type)
        return await service.get_provider_response(provider.id)
    except NoActiveProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.delete("/tenants/{tenant_id}/providers/{provider_id}")
async def unassign_provider_from_tenant(
    tenant_id: str,
    provider_id: UUID,
    operation_type: OperationType = Query(
        OperationType.LLM,
        description="Operation type mapping: llm, embedding, rerank",
    ),
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> dict[str, Any]:
    """
    Unassign a provider from a tenant.

    Requires admin access.
    """
    success = await service.unassign_provider_from_tenant(tenant_id, provider_id, operation_type)
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
    start_date: datetime | None = Query(None, description="Start date filter"),
    end_date: datetime | None = Query(None, description="End date filter"),
    operation_type: str | None = Query(None, description="Filter by operation type"),
    current_user: User = Depends(get_current_user_with_roles),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> dict[str, Any]:
    """
    Get usage statistics for a provider.

    Regular users can only see usage for their tenant.
    Admins can see all usage.
    """
    is_admin = any(r.role.name == "admin" for r in current_user.roles)
    tenant_id = None if is_admin else current_user.tenant_id  # type: ignore[attr-defined]

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


# System Status Endpoints


@router.get("/system/status")
async def get_system_resilience_status(
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """
    Get system-wide resilience status for all LLM providers.

    Returns circuit breaker states, rate limiter stats, and health status
    for all registered provider types. Requires admin access.
    """
    from src.domain.llm_providers.models import ProviderType
    from src.infrastructure.llm.resilience import (
        get_circuit_breaker_registry,
        get_health_checker,
        get_provider_rate_limiter,
    )
    from src.infrastructure.llm.resilience.health_checker import HealthStatus

    cb_registry = get_circuit_breaker_registry()
    rate_limiter = get_provider_rate_limiter()
    health_checker = get_health_checker()

    status = {}
    for provider_type in ProviderType:
        circuit_breaker = cb_registry.get(provider_type)
        cb_status = circuit_breaker.get_status()
        rate_stats = rate_limiter.get_stats(provider_type)

        status[provider_type.value] = {
            "circuit_breaker": {
                "state": cb_status["state"],
                "failure_count": cb_status["failure_count"],
                "success_count": cb_status["success_count"],
                "can_execute": circuit_breaker.can_execute(),
            },
            "rate_limiter": rate_stats.get("stats", {}),
            "health": {
                "status": health_checker.get_current_status()
                .get(provider_type, HealthStatus.UNKNOWN)
                .value
            },
        }

    return {
        "providers": status,
        "summary": {
            "total_providers": len(ProviderType),
            "healthy_count": sum(1 for p in status.values() if p["circuit_breaker"]["can_execute"]),
        },
    }


@router.post("/system/reset-circuit-breaker/{provider_type}")
async def reset_circuit_breaker(
    provider_type: str,
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """
    Reset circuit breaker for a specific provider type.

    This forces the circuit breaker back to CLOSED state,
    allowing requests to the provider again.
    Requires admin access.
    """
    from src.infrastructure.llm.resilience import get_circuit_breaker_registry

    try:
        cb_registry = get_circuit_breaker_registry()
        circuit_breaker = cb_registry.get(provider_type)
        circuit_breaker.reset()

        logger.info(f"Circuit breaker reset for {provider_type} by user {current_user.id}")
        return {
            "message": f"Circuit breaker reset for {provider_type}",
            "new_state": circuit_breaker.get_status(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to reset circuit breaker: {e}",
        ) from e
