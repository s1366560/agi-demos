"""
Factory functions for creating LLM clients and NativeGraphAdapter.

This module provides factory functions that create LLM clients using native SDKs
for each provider, and the NativeGraphAdapter for knowledge graph operations.
"""

import logging
from typing import Optional

from src.configuration.config import get_settings
from src.domain.llm_providers.llm_types import LLMClient

logger = logging.getLogger(__name__)

# Default embedding dimensions by provider
EMBEDDING_DIMS = {
    "openai": 1536,
    "gemini": 768,
    "qwen": 1024,
    "deepseek": 1024,  # Uses fallback
    "zai": 1024,
}


async def create_native_graph_adapter(
    tenant_id: Optional[str] = None,
):
    """
    Create NativeGraphAdapter for knowledge graph operations.

    Args:
        tenant_id: Optional tenant ID for multi-tenant provider resolution

    Returns:
        Configured NativeGraphAdapter instance
    """
    from src.infrastructure.graph import NativeGraphAdapter
    from src.infrastructure.graph.neo4j_client import Neo4jClient

    settings = get_settings()

    # Create Neo4j client
    neo4j_client = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    # Initialize Neo4j indices
    await neo4j_client.build_indices()

    # Get LLM client for entity extraction
    llm_client = create_llm_client(tenant_id)

    # Create embedding service
    embedding_service = await _create_embedding_service(settings, tenant_id)

    # Create NativeGraphAdapter
    adapter = NativeGraphAdapter(
        neo4j_client=neo4j_client,
        llm_client=llm_client,
        embedding_service=embedding_service,
        enable_reflexion=False,  # Temporarily disabled for testing
        reflexion_max_iterations=2,
        auto_clear_embeddings=settings.auto_clear_mismatched_embeddings,
    )

    logger.info("NativeGraphAdapter created successfully")
    return adapter


async def _create_embedding_service(settings, tenant_id: Optional[str] = None):
    """Create embedding service, preferring DB-resolved provider config.

    Falls back to ``.env``-based ``LiteLLMEmbedderConfig`` when the database
    has no active provider (e.g. first-run before ``make db-init``).
    """
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService

    # --- Try DB resolution first ----------------------------------------
    if settings.use_db_provider_resolution:
        try:
            from src.infrastructure.llm.provider_factory import get_ai_service_factory

            factory = get_ai_service_factory()
            provider_config = await factory.resolve_provider(tenant_id)
            embedding_service = factory.create_embedding_service(provider_config)
            logger.info(
                f"EmbeddingService created from DB provider: "
                f"{provider_config.provider_type}, "
                f"model={provider_config.embedding_model}"
            )
            return embedding_service
        except Exception as e:
            logger.warning(f"DB provider resolution failed, falling back to .env: {e}")

    # --- Fallback: build from .env settings -----------------------------
    from src.infrastructure.llm.litellm.litellm_embedder import (
        LiteLLMEmbedder,
        LiteLLMEmbedderConfig,
    )

    provider = settings.llm_provider.strip().lower()
    embedding_dim = EMBEDDING_DIMS.get(provider, 1024)

    if provider == "qwen":
        embedding_model = settings.qwen_embedding_model or "text-embedding-v3"
        api_key = settings.qwen_api_key
        base_url = settings.qwen_base_url
    elif provider == "openai":
        embedding_model = (
            getattr(settings, "openai_embedding_model", None) or "text-embedding-3-small"
        )
        api_key = settings.openai_api_key
        base_url = settings.openai_base_url
    elif provider == "gemini":
        embedding_model = getattr(settings, "gemini_embedding_model", None) or "text-embedding-004"
        api_key = settings.gemini_api_key
        base_url = None
    elif provider in ("zai", "zhipu"):
        embedding_model = (
            settings.zai_embedding_model or settings.zhipu_embedding_model or "embedding-3"
        )
        api_key = settings.zai_api_key or settings.zhipu_api_key
        base_url = settings.zai_base_url or settings.zhipu_base_url
    elif provider == "deepseek":
        embedding_model = settings.qwen_embedding_model or "text-embedding-v3"
        api_key = settings.qwen_api_key
        base_url = settings.qwen_base_url
        embedding_dim = EMBEDDING_DIMS.get("qwen", 1024)
    elif provider == "cohere":
        embedding_model = getattr(settings, "cohere_embedding_model", None) or "embed-english-v3.0"
        api_key = getattr(settings, "cohere_api_key", None)
        base_url = None
    else:
        embedding_model = settings.qwen_embedding_model or "text-embedding-v3"
        api_key = settings.qwen_api_key
        base_url = settings.qwen_base_url

    from src.domain.llm_providers.models import ProviderType

    provider_type_map = {
        "qwen": ProviderType.QWEN,
        "openai": ProviderType.OPENAI,
        "gemini": ProviderType.GEMINI,
        "zai": ProviderType.ZAI,
        "zhipu": ProviderType.ZAI,
        "deepseek": ProviderType.QWEN,
        "cohere": ProviderType.COHERE,
        "anthropic": ProviderType.QWEN,
    }

    config = LiteLLMEmbedderConfig(
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        api_key=api_key,
        base_url=base_url,
        provider_type=provider_type_map.get(provider, ProviderType.QWEN),
    )
    embedder = LiteLLMEmbedder(config=config)
    embedding_service = EmbeddingService(embedder=embedder)

    logger.info(
        f"EmbeddingService created from .env: provider={provider}, "
        f"model={embedding_model}, dim={embedding_dim}"
    )
    return embedding_service


def create_llm_client(tenant_id: Optional[str] = None) -> LLMClient:
    """Create a unified LLM client, preferring DB-resolved provider config.

    Falls back to ``.env``-based config when DB has no active provider.
    """
    from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
    from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient

    settings = get_settings()

    # --- Try DB resolution first ----------------------------------------
    if settings.use_db_provider_resolution:
        try:
            from src.infrastructure.llm.provider_factory import get_ai_service_factory

            factory = get_ai_service_factory()
            # resolve_provider is async; use sync wrapper for backward compat
            import asyncio

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already in an async context -- caller should use async path
                pass
            else:
                provider_config = asyncio.run(factory.resolve_provider(tenant_id))
                client = factory.create_unified_llm_client(provider_config)
                logger.info(
                    f"LLM client created from DB: {provider_config.provider_type}, "
                    f"model={provider_config.llm_model}"
                )
                return client
        except Exception as e:
            logger.warning(f"DB provider resolution failed for LLM, falling back to .env: {e}")

    # --- Fallback: build from .env settings -----------------------------
    provider = settings.llm_provider.strip().lower()
    provider_config = _build_provider_config_from_settings(settings, provider)
    litellm_client = create_litellm_client(provider_config)

    logger.info(f"LLM client created from .env (provider: {provider})")
    return UnifiedLLMClient(litellm_client=litellm_client, temperature=0.7)


# Deprecated: Use create_llm_client instead
def create_langchain_llm(tenant_id: Optional[str] = None) -> LLMClient:
    """
    DEPRECATED: Use create_llm_client() instead.

    This function is kept for backward compatibility and will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "create_langchain_llm is deprecated. Use create_llm_client instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_llm_client(tenant_id)


def _build_provider_config_from_settings(settings, provider: str):
    """
    Build ProviderConfig from application settings.

    Args:
        settings: Application settings
        provider: Provider name string (e.g., "qwen", "openai", "gemini")

    Returns:
        ProviderConfig instance configured from settings
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from src.domain.llm_providers.models import ProviderConfig, ProviderType
    from src.infrastructure.security.encryption_service import get_encryption_service

    encryption_service = get_encryption_service()

    # Map provider string to configuration
    provider_configs = {
        "qwen": {
            "provider_type": ProviderType.QWEN,
            "api_key": settings.qwen_api_key,
            "model": settings.qwen_model,
            "small_model": getattr(settings, "qwen_small_model", None),
            "base_url": settings.qwen_base_url,
            "embedding_model": getattr(settings, "qwen_embedding_model", None),
        },
        "openai": {
            "provider_type": ProviderType.OPENAI,
            "api_key": settings.openai_api_key,
            "model": settings.openai_model,
            "small_model": getattr(settings, "openai_small_model", None),
            "base_url": settings.openai_base_url,
            "embedding_model": getattr(settings, "openai_embedding_model", None),
        },
        "gemini": {
            "provider_type": ProviderType.GEMINI,
            "api_key": settings.gemini_api_key,
            "model": settings.gemini_model,
            "small_model": getattr(settings, "gemini_small_model", None),
            "base_url": None,
            "embedding_model": getattr(settings, "gemini_embedding_model", None),
        },
        "zai": {
            "provider_type": ProviderType.ZAI,
            "api_key": settings.zai_api_key or settings.zhipu_api_key,
            "model": settings.zai_model or settings.zhipu_model,
            "small_model": getattr(settings, "zai_small_model", None),
            "base_url": settings.zai_base_url or settings.zhipu_base_url,
            "embedding_model": getattr(
                settings,
                "zai_embedding_model",
                getattr(settings, "zhipu_embedding_model", None),
            ),
        },
        "zhipu": {
            "provider_type": ProviderType.ZAI,
            "api_key": settings.zai_api_key or settings.zhipu_api_key,
            "model": settings.zai_model or settings.zhipu_model,
            "small_model": getattr(settings, "zai_small_model", None),
            "base_url": settings.zai_base_url or settings.zhipu_base_url,
            "embedding_model": getattr(
                settings,
                "zai_embedding_model",
                getattr(settings, "zhipu_embedding_model", None),
            ),
        },
        "deepseek": {
            "provider_type": ProviderType.DEEPSEEK,
            "api_key": settings.deepseek_api_key,
            "model": settings.deepseek_model,
            "small_model": getattr(settings, "deepseek_small_model", None),
            "base_url": settings.deepseek_base_url,
            "embedding_model": getattr(settings, "qwen_embedding_model", None),
        },
        "anthropic": {
            "provider_type": ProviderType.ANTHROPIC,
            "api_key": getattr(settings, "anthropic_api_key", None),
            "model": getattr(settings, "anthropic_model", "claude-3-sonnet-20240229"),
            "small_model": getattr(settings, "anthropic_small_model", None),
            "base_url": getattr(settings, "anthropic_base_url", None),
            "embedding_model": getattr(settings, "qwen_embedding_model", None),
        },
    }

    # Get config for provider, default to Gemini
    config = provider_configs.get(
        provider,
        provider_configs["gemini"],
    )

    # Encrypt API key
    api_key = config["api_key"] or ""
    api_key_encrypted = encryption_service.encrypt(api_key) if api_key else ""

    now = datetime.now(timezone.utc)

    return ProviderConfig(
        id=uuid4(),
        name=f"settings-{provider}",
        tenant_id="default",
        provider_type=config["provider_type"],
        api_key_encrypted=api_key_encrypted,
        llm_model=config["model"] or "gpt-4",
        llm_small_model=config["small_model"],
        embedding_model=config.get("embedding_model"),
        base_url=config["base_url"],
        is_active=True,
        is_default=True,
        created_at=now,
        updated_at=now,
    )


async def create_managed_llm_client(
    tenant_id: Optional[str] = None,
    preferred_provider: Optional[str] = None,
) -> LLMClient:
    """
    Create an LLM client using the LLMProviderManager.

    This function provides automatic health checking, circuit breaking,
    and fallback to alternative providers.

    Args:
        tenant_id: Optional tenant ID for multi-tenant provider resolution
        preferred_provider: Preferred provider name (e.g., "openai", "gemini")

    Returns:
        LLM client with resilience patterns applied
    """
    from src.application.services.llm_provider_manager import (
        OperationType,
        get_llm_provider_manager,
    )
    from src.domain.llm_providers.models import ProviderType

    settings = get_settings()
    manager = get_llm_provider_manager()

    # Register provider from settings if not already registered
    provider = preferred_provider or settings.llm_provider.strip().lower()
    provider_config = _build_provider_config_from_settings(settings, provider)

    # Map string to ProviderType
    provider_type_map = {
        "openai": ProviderType.OPENAI,
        "gemini": ProviderType.GEMINI,
        "qwen": ProviderType.QWEN,
        "deepseek": ProviderType.DEEPSEEK,
        "zai": ProviderType.ZAI,
        "zhipu": ProviderType.ZAI,
        "anthropic": ProviderType.ANTHROPIC,
        "kimi": ProviderType.KIMI,
    }
    provider_type = provider_type_map.get(provider, ProviderType.GEMINI)

    # Register if not already registered
    if manager.get_provider_config(provider_type) is None:
        manager.register_provider(provider_config)

    # Get client with automatic fallback
    return await manager.get_llm_client(
        tenant_id=tenant_id,
        operation=OperationType.LLM,
        preferred_provider=provider_type,
    )
