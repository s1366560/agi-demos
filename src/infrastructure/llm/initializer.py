"""
Default LLM Provider Initialization

This module handles automatic creation of default LLM provider configurations
from environment variables when no providers are configured in the database.
"""

import logging
import os

from sqlalchemy.exc import IntegrityError

from src.application.services.provider_service import ProviderService
from src.domain.llm_providers.models import ProviderConfigCreate, ProviderType
from src.infrastructure.llm.provider_credentials import should_require_api_key

logger = logging.getLogger(__name__)

# Provider type mapping from config name to ProviderType enum
PROVIDER_TYPE_MAP: dict[str, ProviderType] = {
    "gemini": ProviderType.GEMINI,
    "dashscope": ProviderType.DASHSCOPE,
    "openai": ProviderType.OPENAI,
    "deepseek": ProviderType.DEEPSEEK,
    "zai": ProviderType.ZAI,
    "zhipu": ProviderType.ZAI,  # Alias for zai
    "kimi": ProviderType.KIMI,  # Moonshot AI (Kimi)
    "moonshot": ProviderType.KIMI,  # Alias for kimi
    "anthropic": ProviderType.ANTHROPIC,  # Anthropic (Claude)
    "claude": ProviderType.ANTHROPIC,  # Alias for anthropic
    "ollama": ProviderType.OLLAMA,  # Local Ollama
    "lmstudio": ProviderType.LMSTUDIO,  # LM Studio
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
    # Fallback to 'gemini' if not set, but try to detect based on API keys first
    provider_name = os.getenv("LLM_PROVIDER", "").lower()
    
    # Auto-detect if not set
    if not provider_name:
        if os.getenv("GEMINI_API_KEY"):
            provider_name = "gemini"
        elif os.getenv("DASHSCOPE_API_KEY"):
            provider_name = "dashscope"
        elif os.getenv("OPENAI_API_KEY"):
            provider_name = "openai"
        elif os.getenv("DEEPSEEK_API_KEY"):
            provider_name = "deepseek"
        elif os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY"):
            provider_name = "zai"
        elif os.getenv("KIMI_API_KEY"):
            provider_name = "kimi"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider_name = "anthropic"
        elif os.getenv("OLLAMA_BASE_URL"):
            provider_name = "ollama"
        elif os.getenv("LMSTUDIO_BASE_URL"):
            provider_name = "lmstudio"
        else:
            provider_name = "gemini"  # Default fallback

    provider_type = PROVIDER_TYPE_MAP.get(provider_name)

    if provider_type is None:
        logger.warning(
            f"Unknown provider type '{provider_name}'. "
            f"Supported types: {list(PROVIDER_TYPE_MAP.keys())}"
        )
        return False

    # Build provider config from environment variables
    provider_config = _build_provider_config(provider_name)

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
    provider_name: str,
) -> ProviderConfigCreate | None:
    """
    Build a ProviderConfigCreate from environment variables.

    Args:
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

    if provider_name == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        llm_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")
        reranker_model = os.getenv("GEMINI_RERANK_MODEL", "gemini-2.0-flash")
        
    elif provider_name in ("zhipu", "zai"):
        api_key = os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY")
        llm_model = os.getenv("ZAI_MODEL") or os.getenv("ZHIPU_MODEL", "glm-4-plus")
        llm_small_model = os.getenv("ZAI_SMALL_MODEL") or os.getenv("ZHIPU_SMALL_MODEL", "glm-4-flash")
        embedding_model = os.getenv("ZAI_EMBEDDING_MODEL") or os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-3")
        reranker_model = os.getenv("ZAI_RERANK_MODEL") or os.getenv("ZHIPU_RERANK_MODEL", "glm-4-flash")
        base_url = os.getenv("ZAI_BASE_URL") or os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

    elif provider_name == "dashscope":
        api_key = os.getenv("DASHSCOPE_API_KEY")
        llm_model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")
        llm_small_model = os.getenv("DASHSCOPE_SMALL_MODEL", "qwen-turbo")
        embedding_model = os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3")
        reranker_model = os.getenv("DASHSCOPE_RERANK_MODEL", "qwen-turbo")
        base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    elif provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        llm_model = os.getenv("OPENAI_MODEL", "gpt-4o")
        llm_small_model = os.getenv("OPENAI_SMALL_MODEL", "gpt-4o-mini")
        embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        reranker_model = os.getenv("OPENAI_RERANK_MODEL", "gpt-4o-mini")
        base_url = os.getenv("OPENAI_BASE_URL")

    elif provider_name == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        llm_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        llm_small_model = os.getenv("DEEPSEEK_SMALL_MODEL", "deepseek-coder")
        reranker_model = os.getenv("DEEPSEEK_RERANK_MODEL", "deepseek-chat")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

    elif provider_name in ("kimi", "moonshot"):
        api_key = os.getenv("KIMI_API_KEY")
        llm_model = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
        llm_small_model = os.getenv("KIMI_SMALL_MODEL", "moonshot-v1-8k")
        embedding_model = os.getenv("KIMI_EMBEDDING_MODEL", "kimi-embedding-1")
        reranker_model = os.getenv("KIMI_RERANK_MODEL", "kimi-rerank-1")
        base_url = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")

    elif provider_name in ("anthropic", "claude"):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        llm_model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620")
        llm_small_model = os.getenv("ANTHROPIC_SMALL_MODEL", "claude-3-haiku-20240307")
        embedding_model = os.getenv("ANTHROPIC_EMBEDDING_MODEL", "")
        reranker_model = os.getenv("ANTHROPIC_RERANK_MODEL", "claude-3-haiku-20240307")
        base_url = os.getenv("ANTHROPIC_BASE_URL")

    elif provider_name == "ollama":
        api_key = os.getenv("OLLAMA_API_KEY")
        llm_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        llm_small_model = os.getenv("OLLAMA_SMALL_MODEL", "llama3.1:8b")
        embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
        reranker_model = os.getenv("OLLAMA_RERANK_MODEL", "llama3.1:8b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    elif provider_name == "lmstudio":
        api_key = os.getenv("LMSTUDIO_API_KEY")
        llm_model = os.getenv("LMSTUDIO_MODEL", "local-model")
        llm_small_model = os.getenv("LMSTUDIO_SMALL_MODEL", "local-model")
        embedding_model = os.getenv(
            "LMSTUDIO_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5"
        )
        reranker_model = os.getenv("LMSTUDIO_RERANK_MODEL", "local-model")
        base_url = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")

    # Check if API key is available (except local providers with optional key)
    if should_require_api_key(provider_type) and not api_key:
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
