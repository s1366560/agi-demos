"""
LLM Provider Management API endpoints.

Provides REST API for managing LLM provider configurations,
including CRUD operations, health checks, and tenant assignments.
"""

import logging
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.services.provider_service import ProviderService, get_provider_service
from src.domain.llm_providers.models import (
    NoActiveProviderError,
    OperationType,
    ProviderAuthMethod,
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
    ProviderCredentialRequiredError,
    ProviderHealth,
    ProviderProbeRequest,
    ProviderRevisionConflictError,
    ProviderStatus,
    ProviderType,
    ProviderTypeDescriptor,
    ProviderValidationResponse,
    TenantProviderMapping,
    UnsupportedProviderAuthError,
    infer_operation_type_from_provider_type,
    provider_environment_variables,
    validate_provider_base_url_transport,
)
from src.domain.llm_providers.security_policy import (
    provider_persistent_auth_supported,
    provider_probe_supported,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserRole
from src.infrastructure.i18n import gettext as _

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
    Get current user with roles and tenant memberships eagerly loaded.

    This is needed because the base get_current_user doesn't load roles or
    tenant memberships to reduce query overhead, but this router needs both
    role and tenant-scope checks.
    """
    result = await db.execute(
        refresh_select_statement(
            select(User)
            .where(User.id == current_user.id)
            .options(
                selectinload(User.roles).selectinload(UserRole.role),
                selectinload(User.tenants),
            )
        )
    )
    return cast(User, result.scalar_one())


def _is_admin(current_user: User) -> bool:
    return any(user_role.role.name == "admin" for user_role in current_user.roles)


def _tenant_ids_for_user(current_user: User) -> list[str]:
    tenant_ids: list[str] = []
    for membership in current_user.tenants:
        if membership.tenant_id not in tenant_ids:
            tenant_ids.append(membership.tenant_id)
    return tenant_ids


def _require_tenant_access(current_user: User, tenant_id: str) -> None:
    if _is_admin(current_user):
        return

    if tenant_id not in _tenant_ids_for_user(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to tenant assignments"),
        )


def _default_tenant_id_for_user(current_user: User) -> str:
    tenant_ids = _tenant_ids_for_user(current_user)
    if not tenant_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("User does not belong to any tenant"),
        )
    return tenant_ids[0]


def _catalog_provider_key(provider_type: str) -> str:
    """Normalize specialized provider variants to model catalog provider keys."""
    normalized = provider_type.strip().lower()
    for suffix in ("_coding", "_embedding", "_reranker"):
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break
    if normalized == "azure_openai":
        return "azure_openai"
    return normalized


def _categorize_catalog_models(provider_type: str) -> dict[str, list[str]]:
    """Build chat/embedding/rerank model lists from the loaded catalog."""
    from src.infrastructure.llm.model_catalog import get_model_catalog_service

    catalog = get_model_catalog_service()
    provider_key = _catalog_provider_key(provider_type)
    models = catalog.list_models(provider=provider_key)
    categorized: dict[str, list[str]] = {"chat": [], "embedding": [], "rerank": []}
    for model in models:
        capabilities = {str(cap).lower() for cap in model.capabilities}
        if "embedding" in capabilities:
            categorized["embedding"].append(model.name)
        elif "rerank" in capabilities or "reranking" in capabilities:
            categorized["rerank"].append(model.name)
        elif "chat" in capabilities or "completion" in capabilities:
            categorized["chat"].append(model.name)

    for names in categorized.values():
        names.sort()
    return categorized


async def require_admin(current_user: User = Depends(get_current_user_with_roles)) -> User:
    """Dependency to require admin role."""
    if not _is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Admin access required"),
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
    except UnsupportedProviderAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("Unsupported provider authentication method"),
        ) from exc
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid provider request"),
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
    if not _is_admin(current_user):
        include_inactive = False

    providers = await service.list_providers(include_inactive=include_inactive)
    return await service.get_provider_responses(providers)


# Static routes must be defined before dynamic /{provider_id} route


@router.get("/types", response_model=list[ProviderTypeDescriptor])
async def list_provider_types(
    current_user: User = Depends(get_current_user),
) -> list[ProviderTypeDescriptor]:
    """
    List all supported provider types.
    """
    no_auth_providers = {ProviderType.OLLAMA, ProviderType.LMSTUDIO}
    descriptors: list[ProviderTypeDescriptor] = []
    for provider_type in ProviderType:
        persistent_auth_available = provider_persistent_auth_supported(provider_type)
        if not persistent_auth_available:
            auth_methods: list[ProviderAuthMethod] = []
            unavailable_auth_methods = ["api_key", "environment", "oauth"]
        else:
            auth_methods = [
                ProviderAuthMethod.NONE
                if provider_type in no_auth_providers
                else ProviderAuthMethod.API_KEY
            ]
            unavailable_auth_methods = (
                ["environment"] if provider_environment_variables(provider_type) else []
            ) + (
                ["oauth"] if provider_type in {ProviderType.OPENAI, ProviderType.ANTHROPIC} else []
            )
        descriptors.append(
            ProviderTypeDescriptor(
                provider_type=provider_type,
                operation_type=infer_operation_type_from_provider_type(provider_type).value,
                probe_supported=provider_probe_supported(provider_type),
                auth_methods=auth_methods,
                unavailable_auth_methods=unavailable_auth_methods,
            )
        )
    return descriptors


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


@router.post("/models/catalog/refresh")
async def refresh_catalog_models(
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """
    Refresh the embedded model catalog snapshot from models.dev.

    Requires admin access because this performs a server-side network fetch
    and rewrites the local model snapshot artifact.
    """
    from src.infrastructure.llm.model_catalog import get_model_catalog_service

    catalog = get_model_catalog_service()
    info = catalog.refresh_from_remote()
    logger.info("Model catalog refreshed from models.dev by user %s", current_user.id)
    return {"status": "refreshed", "snapshot": info}


@router.get("/models/{provider_type}")
async def list_models_for_provider_type(
    provider_type: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    List available models for a given provider type.

    Returns categorized models (chat, embedding, rerank) for the provider.
    """
    catalog_models = _categorize_catalog_models(provider_type)
    if any(catalog_models.values()):
        return {
            "provider_type": provider_type,
            "models": catalog_models,
            "source": "models.dev",
        }

    # Categorized models for each provider type
    models_data = {
        "openai": {
            "chat": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
            "embedding": ["text-embedding-3-small", "text-embedding-3-large"],
            "rerank": [],
        },
        "openrouter": {
            "chat": ["openai/gpt-4o", "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"],
            "embedding": ["openai/text-embedding-3-small"],
            "rerank": [],
        },
        "dashscope": {
            "chat": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
            "embedding": ["text-embedding-v3", "text-embedding-v2"],
            "rerank": ["qwen3-rerank"],
        },
        "zai": {
            "chat": ["glm-4-plus", "glm-4-flash", "glm-4-air"],
            "embedding": ["embedding-3", "embedding-2"],
            "rerank": [],
        },
        "kimi": {
            "chat": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
            "embedding": ["kimi-embedding-1"],
            "rerank": ["kimi-rerank-1"],
        },
        "ollama": {
            "chat": ["llama3.1:8b", "qwen2.5:7b", "mistral-nemo"],
            "embedding": ["nomic-embed-text"],
            "rerank": [],
        },
        "lmstudio": {
            "chat": ["local-model"],
            "embedding": ["text-embedding-nomic-embed-text-v1.5"],
            "rerank": [],
        },
        "gemini": {
            "chat": [
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.5-pro-002",
                "gemini-1.5-flash-002",
            ],
            "embedding": ["text-embedding-004"],
            "rerank": [],
        },
        "anthropic": {
            "chat": [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
            "embedding": [],
            "rerank": [],
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
            "rerank": [],
        },
        "minimax": {
            "chat": ["abab6.5-chat", "abab6.5s-chat", "MiniMax-Text-01"],
            "embedding": ["embo-01"],
            "rerank": [],
        },
        "cohere": {
            "chat": ["command-r-plus", "command-r"],
            "embedding": ["embed-english-v3.0", "embed-multilingual-v3.0"],
            "rerank": ["rerank-english-v3.0", "rerank-multilingual-v3.0"],
        },
        "mistral": {
            "chat": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
            "embedding": ["mistral-embed"],
            "rerank": [],
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
        "volcengine": {
            "chat": [
                "doubao-seed-2.0-pro",
                "doubao-seed-2.0-lite",
                "doubao-seed-2.0-mini",
                "doubao-seed-2.0-code",
                "doubao-1.5-pro-32k",
                "doubao-1.5-pro-128k",
                "doubao-1.5-pro-256k",
                "doubao-1.5-lite-32k",
                "doubao-1.5-lite-128k",
                "doubao-pro-32k",
                "doubao-pro-128k",
                "doubao-pro-256k",
                "doubao-lite-32k",
                "doubao-lite-128k",
            ],
            "vision": [
                "doubao-1.5-vision-pro-32k",
                "doubao-1.5-vision-pro-128k",
                "doubao-vision-pro-32k",
                "doubao-vision-pro-128k",
                "doubao-vision-lite-32k",
            ],
            "embedding": [
                "doubao-embedding",
                "doubao-embedding-large",
                "doubao-embedding-large-text-240915",
                "doubao-embedding-large-text-250515",
                "doubao-embedding-text-240715",
            ],
            "rerank": ["doubao-reranker-large"],
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
        "source": "static-fallback",
    }


@router.get("/env-detection")
async def detect_env_providers(
    current_user: User = Depends(require_admin),
) -> dict[str, Any]:
    """
    Detect LLM providers configured via environment variables.

    Returns non-secret provider configuration metadata found in server env vars.
    Requires admin access because environment-derived infrastructure details are sensitive.
    """
    from src.infrastructure.llm.initializer import detect_env_providers as _detect

    detected = _detect()

    def _safe_base_url(name: str, value: object) -> str | None:
        try:
            provider_type = ProviderType(name)
        except ValueError:
            return None
        try:
            return validate_provider_base_url_transport(
                value if isinstance(value, str) else None,
                provider_type,
            )
        except ValueError:
            return None

    return {
        "detected_providers": {
            name: {
                "provider_type": name,
                "operation_type": config.get("operation_type", "llm"),
                "credential_source": "environment",
                "credential_configured": bool(config.get("api_key")),
                "base_url": _safe_base_url(name, config.get("base_url")),
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
            detail=_("Provider not found"),
        )

    # Check if provider is active (non-admins can't see inactive providers)
    if not _is_admin(current_user) and not provider_response.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Provider not found"),
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
    if config.expected_revision is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("Provider revision is required"),
        )
    try:
        updated = await service.update_provider(provider_id, config)
    except ProviderRevisionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_("Provider configuration changed; reload and try again"),
        ) from exc
    except ProviderCredentialRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("Provider credential must be resubmitted"),
        ) from exc
    except UnsupportedProviderAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_("Unsupported provider authentication method"),
        ) from exc
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Provider not found"),
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
            detail=_("Provider not found"),
        )

    logger.info(f"Provider deleted: {provider_id} by user {current_user.id}")


# Health Check Endpoints


@router.post("/test-connection", response_model=ProviderValidationResponse)
async def test_provider_connection(
    config: ProviderProbeRequest,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderValidationResponse:
    """
    Test an LLM provider configuration without saving it.

    Requires admin access.
    """
    try:
        validation = await service.test_provider_connection(config)
        logger.info(
            "Provider connection test completed for %s by user %s: %s",
            config.provider_type,
            current_user.id,
            validation.status,
        )
        return validation
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Provider connection test failed"),
        ) from e


@router.post("/{provider_id}/health-check", response_model=ProviderValidationResponse)
async def check_provider_health(
    provider_id: UUID,
    current_user: User = Depends(require_admin),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderValidationResponse:
    """
    Trigger a health check for a provider.

    Requires admin access.
    """
    try:
        health = await service.check_provider_health(provider_id)
        logger.info(f"Health check completed for provider {provider_id}: {health.status}")
        probed = health.status != ProviderStatus.CONFIGURATION_VALID
        return ProviderValidationResponse.from_health(
            health,
            probed=probed,
            detail=(
                None if probed else _("Connection probing is not supported for this provider type")
            ),
            catalog=None,
        )
    except UnsupportedProviderAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Provider health check is not supported"),
        ) from exc
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Provider not found"),
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
            detail=_("No health data available for this provider"),
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
    _require_tenant_access(current_user, tenant_id)

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
            detail=_("Provider assignment failed"),
        ) from e


@router.get("/tenants/{tenant_id}/provider", response_model=ProviderConfigResponse)
async def get_tenant_provider(
    tenant_id: str,
    operation_type: OperationType = Query(
        OperationType.LLM,
        description="Operation type to resolve: llm, embedding, rerank",
    ),
    current_user: User = Depends(get_current_user_with_roles),
    service: ProviderService = Depends(get_provider_service_with_session),
) -> ProviderConfigResponse | None:
    """
    Get the provider assigned to a specific tenant.

    Returns the resolved provider based on fallback hierarchy.
    """
    _require_tenant_access(current_user, tenant_id)

    try:
        provider = await service.resolve_provider_for_tenant(tenant_id, operation_type)
        return await service.get_provider_response(provider.id)
    except NoActiveProviderError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("No active provider configured"),
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
            detail=_("Tenant-provider mapping not found"),
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
    tenant_id = None if _is_admin(current_user) else _default_tenant_id_for_user(current_user)

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
        logger.exception("Failed to reset circuit breaker")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Failed to reset circuit breaker"),
        ) from e
