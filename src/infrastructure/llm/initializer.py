"""
Default LLM Provider Initialization

This module handles automatic creation of default LLM provider configurations
from environment variables when no providers are configured in the database.
"""

import logging
from typing import Dict, Optional

from sqlalchemy.exc import IntegrityError

from src.application.services.provider_service import ProviderService
from src.configuration.config import get_settings
from src.domain.llm_providers.models import ProviderConfigCreate, ProviderType

logger = logging.getLogger(__name__)

# Provider type mapping from config name to ProviderType enum
PROVIDER_TYPE_MAP: Dict[str, ProviderType] = {
    "gemini": ProviderType.GEMINI,
    "qwen": ProviderType.QWEN,
    "openai": ProviderType.OPENAI,
    "deepseek": ProviderType.DEEPSEEK,
    "zai": ProviderType.ZAI,
    "zhipu": ProviderType.ZAI,  # Alias for zai
    "kimi": ProviderType.KIMI,  # Moonshot AI (Kimi)
    "moonshot": ProviderType.KIMI,  # Alias for kimi
    "anthropic": ProviderType.ANTHROPIC,  # Anthropic (Claude)
    "claude": ProviderType.ANTHROPIC,  # Alias for anthropic
}


async def initialize_default_llm_providers(force_recreate: bool = False) -> bool:
    """
    Initialize default LLM provider from environment configuration.

    This function checks if any LLM providers exist in the database.
    If none exist, or if force_recreate is True, it creates a default provider
    using the configured LLM_PROVIDER environment variable and its associated API keys.

    The created provider will include:
    - LLM model configuration
    - Small LLM model (if available)
    - Embedding model
    - Rerank model (may use LLM model as fallback)

    This function is idempotent and safe for concurrent initialization across
    multiple processes. If another process creates the provider first, this
    function will silently use the existing provider.

    Args:
        force_recreate: If True, clear all existing providers and recreate.

    Returns:
        True if a default provider was created, False otherwise
    """
    settings = get_settings()
    provider_service = ProviderService()

    # If force recreate, clear all existing providers first
    if force_recreate:
        logger.info("Force recreate requested, clearing existing providers...")
        cleared_count = await provider_service.clear_all_providers()
        logger.info(f"Cleared {cleared_count} existing providers")
    else:
        # Check if any providers already exist and verify accessibility
        existing_providers = await provider_service.list_providers(include_inactive=False)
        if existing_providers:
            # Verify that existing providers are accessible (API key can be decrypted)
            try:
                from src.infrastructure.security.encryption_service import get_encryption_service

                test_provider = existing_providers[0]
                # Try to decrypt the API key to verify accessibility
                encryption_service = get_encryption_service()
                _ = encryption_service.decrypt(test_provider.api_key_encrypted)
                logger.info(
                    f"Existing provider {test_provider.name} is accessible, skipping initialization"
                )
                return False
            except Exception as e:
                logger.warning(
                    f"Existing provider {existing_providers[0].name} is not accessible: {e}. "
                    f"This usually means the encryption key has changed. Will recreate providers..."
                )
                # Recreate with force flag
                return await initialize_default_llm_providers(force_recreate=True)

    logger.info("Creating default LLM provider from environment...")

    # Get the configured provider
    provider_name = settings.llm_provider.lower()
    provider_type = PROVIDER_TYPE_MAP.get(provider_name)

    if provider_type is None:
        logger.warning(
            f"Unknown provider type '{provider_name}'. "
            f"Supported types: {list(PROVIDER_TYPE_MAP.keys())}"
        )
        return False

    # Build provider config from settings
    provider_config = _build_provider_config(settings, provider_name)

    if provider_config is None:
        logger.warning(f"Could not build provider config for '{provider_name}': API key not found")
        return False

    try:
        # Create the provider (idempotent - returns existing if another process created it)
        created_provider = await provider_service.create_provider(provider_config)

        # Verify the created provider is accessible by decrypting API key
        from src.infrastructure.security.encryption_service import get_encryption_service

        encryption_service = get_encryption_service()
        _ = encryption_service.decrypt(created_provider.api_key_encrypted)

        logger.info(
            f"Created and verified default LLM provider: {created_provider.name} "
            f"({created_provider.provider_type}) with models: "
            f"LLM={created_provider.llm_model}, "
            f"Embedding={created_provider.embedding_model}, "
            f"Rerank={created_provider.reranker_model or 'using LLM model'}"
        )
        return True

    except IntegrityError as e:
        # Handle concurrent initialization - another process may have created the provider
        if "llm_providers_name_key" in str(e) or "UniqueViolationError" in str(e):
            logger.info(
                "Default LLM provider already created by another process. Skipping. "
                "This is normal during concurrent initialization."
            )
            return True
        logger.error(f"Database integrity error during provider initialization: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Failed to create default LLM provider: {e}", exc_info=True)
        return False


def _build_provider_config(
    settings,  # type: ignore
    provider_name: str,
) -> Optional[ProviderConfigCreate]:
    """
    Build a ProviderConfigCreate from environment settings.

    Args:
        settings: Application settings
        provider_name: Name of the provider (lowercase)

    Returns:
        ProviderConfigCreate if API key is available, None otherwise
    """
    provider_type = PROVIDER_TYPE_MAP[provider_name]

    # Extract provider-specific settings
    api_key = None
    llm_model = None
    llm_small_model = None
    embedding_model = None
    reranker_model = None
    base_url = None

    if provider_name == "gemini" or provider_name == "zhipu" or provider_name == "zai":
        if provider_name == "gemini":
            api_key = settings.gemini_api_key
            llm_model = settings.gemini_model
            embedding_model = settings.gemini_embedding_model
            reranker_model = settings.gemini_rerank_model
        elif provider_name in ("zhipu", "zai"):
            api_key = settings.zai_api_key or settings.zhipu_api_key
            llm_model = settings.zai_model or settings.zhipu_model
            llm_small_model = settings.zai_small_model or settings.zhipu_small_model
            embedding_model = settings.zai_embedding_model or settings.zhipu_embedding_model
            reranker_model = settings.zai_rerank_model or settings.zhipu_rerank_model
            base_url = settings.zai_base_url or settings.zhipu_base_url

    elif provider_name == "qwen":
        api_key = settings.qwen_api_key
        llm_model = settings.qwen_model
        llm_small_model = settings.qwen_small_model
        embedding_model = settings.qwen_embedding_model
        reranker_model = settings.qwen_rerank_model
        base_url = settings.qwen_base_url

    elif provider_name == "openai":
        api_key = settings.openai_api_key
        llm_model = settings.openai_model
        llm_small_model = settings.openai_small_model
        embedding_model = settings.openai_embedding_model
        reranker_model = settings.openai_rerank_model
        base_url = settings.openai_base_url

    elif provider_name == "deepseek":
        api_key = settings.deepseek_api_key
        llm_model = settings.deepseek_model
        llm_small_model = settings.deepseek_small_model
        # Deepseek uses Qwen embeddings by default
        reranker_model = settings.deepseek_rerank_model
        base_url = settings.deepseek_base_url

    elif provider_name in ("kimi", "moonshot"):
        api_key = settings.kimi_api_key
        llm_model = settings.kimi_model
        llm_small_model = settings.kimi_small_model
        embedding_model = settings.kimi_embedding_model
        reranker_model = settings.kimi_rerank_model
        base_url = settings.kimi_base_url

    elif provider_name in ("anthropic", "claude"):
        api_key = settings.anthropic_api_key
        llm_model = settings.anthropic_model
        llm_small_model = settings.anthropic_small_model
        embedding_model = settings.anthropic_embedding_model
        reranker_model = settings.anthropic_rerank_model
        base_url = settings.anthropic_base_url

    # Check if API key is available
    if not api_key:
        return None

    # Create provider config
    return ProviderConfigCreate(
        name=f"Default {provider_name.title()}",
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        llm_model=llm_model or f"{provider_name}-default",
        llm_small_model=llm_small_model,
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        is_active=True,
        is_default=True,
        config={},  # Additional provider-specific config can be added here
    )
