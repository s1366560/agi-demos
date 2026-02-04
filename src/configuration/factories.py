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
    """
    Create embedding service based on provider configuration.

    Uses LiteLLM for all embedding operations.

    Args:
        settings: Application settings
        tenant_id: Optional tenant ID for provider resolution

    Returns:
        Configured EmbeddingService instance
    """
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    from src.infrastructure.llm.litellm.litellm_embedder import (
        LiteLLMEmbedder,
        LiteLLMEmbedderConfig,
    )

    provider = settings.llm_provider.strip().lower()

    # Determine embedding dimension and model based on provider
    embedding_dim = EMBEDDING_DIMS.get(provider, 1024)

    # Get embedding model and API key for provider
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
        # Deepseek doesn't have embedding API, use Qwen as fallback
        embedding_model = settings.qwen_embedding_model or "text-embedding-v3"
        api_key = settings.qwen_api_key
        base_url = settings.qwen_base_url
        embedding_dim = EMBEDDING_DIMS.get("qwen", 1024)
    elif provider == "cohere":
        embedding_model = getattr(settings, "cohere_embedding_model", None) or "embed-english-v3.0"
        api_key = getattr(settings, "cohere_api_key", None)
        base_url = None
    else:
        # Default to Qwen for unknown providers
        embedding_model = settings.qwen_embedding_model or "text-embedding-v3"
        api_key = settings.qwen_api_key
        base_url = settings.qwen_base_url

    # Create LiteLLM embedder config
    from src.domain.llm_providers.models import ProviderType

    # Map provider string to ProviderType
    provider_type_map = {
        "qwen": ProviderType.QWEN,
        "openai": ProviderType.OPENAI,
        "gemini": ProviderType.GEMINI,
        "zai": ProviderType.ZAI,
        "zhipu": ProviderType.ZAI,
        "deepseek": ProviderType.QWEN,  # Uses Qwen for embedding
        "cohere": ProviderType.COHERE,
        "anthropic": ProviderType.QWEN,  # Uses Qwen for embedding
    }

    config = LiteLLMEmbedderConfig(
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        api_key=api_key,
        base_url=base_url,
        provider_type=provider_type_map.get(provider, ProviderType.QWEN),
    )
    embedder = LiteLLMEmbedder(config=config)

    # Create EmbeddingService wrapper
    embedding_service = EmbeddingService(embedder=embedder)

    logger.info(
        f"EmbeddingService created with LiteLLM: provider={provider}, model={embedding_model}, dim={embedding_dim}"
    )
    return embedding_service


def create_llm_client(tenant_id: Optional[str] = None) -> LLMClient:
    """
    Create a unified LLM client backed by LiteLLM.

    This function returns a UnifiedLLMClient adapter that wraps
    LiteLLMClient, providing unified multi-provider support through
    the domain's standard LLMClient interface.

    Args:
        tenant_id: Optional tenant ID for multi-tenant provider resolution

    Returns:
        Unified LLM client backed by LiteLLM
    """
    from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
    from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient

    settings = get_settings()
    provider = settings.llm_provider.strip().lower()

    # Build ProviderConfig from settings
    provider_config = _build_provider_config_from_settings(settings, provider)

    # Create LiteLLM client
    litellm_client = create_litellm_client(provider_config)

    logger.info(f"Creating unified LLM client via LiteLLM adapter (provider: {provider})")

    # Return wrapped adapter
    return UnifiedLLMClient(
        litellm_client=litellm_client,
        temperature=0.7,
    )


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
    from datetime import datetime
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
        },
        "openai": {
            "provider_type": ProviderType.OPENAI,
            "api_key": settings.openai_api_key,
            "model": settings.openai_model,
            "small_model": getattr(settings, "openai_small_model", None),
            "base_url": settings.openai_base_url,
        },
        "gemini": {
            "provider_type": ProviderType.GEMINI,
            "api_key": settings.gemini_api_key,
            "model": settings.gemini_model,
            "small_model": getattr(settings, "gemini_small_model", None),
            "base_url": None,
        },
        "zai": {
            "provider_type": ProviderType.ZAI,
            "api_key": settings.zai_api_key or settings.zhipu_api_key,
            "model": settings.zai_model or settings.zhipu_model,
            "small_model": getattr(settings, "zai_small_model", None),
            "base_url": settings.zai_base_url or settings.zhipu_base_url,
        },
        "zhipu": {
            "provider_type": ProviderType.ZAI,
            "api_key": settings.zai_api_key or settings.zhipu_api_key,
            "model": settings.zai_model or settings.zhipu_model,
            "small_model": getattr(settings, "zai_small_model", None),
            "base_url": settings.zai_base_url or settings.zhipu_base_url,
        },
        "deepseek": {
            "provider_type": ProviderType.DEEPSEEK,
            "api_key": settings.deepseek_api_key,
            "model": settings.deepseek_model,
            "small_model": getattr(settings, "deepseek_small_model", None),
            "base_url": settings.deepseek_base_url,
        },
        "anthropic": {
            "provider_type": ProviderType.ANTHROPIC,
            "api_key": getattr(settings, "anthropic_api_key", None),
            "model": getattr(settings, "anthropic_model", "claude-3-sonnet-20240229"),
            "small_model": getattr(settings, "anthropic_small_model", None),
            "base_url": getattr(settings, "anthropic_base_url", None),
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

    now = datetime.utcnow()

    return ProviderConfig(
        id=uuid4(),
        name=f"settings-{provider}",
        tenant_id="default",
        provider_type=config["provider_type"],
        api_key_encrypted=api_key_encrypted,
        llm_model=config["model"] or "gpt-4",
        llm_small_model=config["small_model"],
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
