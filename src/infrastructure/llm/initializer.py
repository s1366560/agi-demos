"""
Default LLM Provider Initialization

This module handles automatic creation of default LLM provider configurations
from environment variables when no providers are configured in the database.
"""

import logging
import os
from typing import Any

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
    "minimax": ProviderType.MINIMAX,
    "zai": ProviderType.ZAI,
    "zhipu": ProviderType.ZAI,  # Alias for zai
    "kimi": ProviderType.KIMI,  # Moonshot AI (Kimi)
    "moonshot": ProviderType.KIMI,  # Alias for kimi
    "anthropic": ProviderType.ANTHROPIC,  # Anthropic (Claude)
    "claude": ProviderType.ANTHROPIC,  # Alias for anthropic
    "ollama": ProviderType.OLLAMA,  # Local Ollama
    "lmstudio": ProviderType.LMSTUDIO,  # LM Studio
}

# Auto-detection order: env var -> provider name
_PROVIDER_AUTO_DETECT: list[tuple[str, str]] = [
    ("GEMINI_API_KEY", "gemini"),
    ("DASHSCOPE_API_KEY", "dashscope"),
    ("OPENAI_API_KEY", "openai"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("MINIMAX_API_KEY", "minimax"),
    ("ZAI_API_KEY", "zai"),
    ("ZHIPU_API_KEY", "zai"),
    ("KIMI_API_KEY", "kimi"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OLLAMA_BASE_URL", "ollama"),
    ("LMSTUDIO_BASE_URL", "lmstudio"),
]


def _auto_detect_provider() -> str:
    """Auto-detect provider name from available environment API keys."""
    for env_var, provider_name in _PROVIDER_AUTO_DETECT:
        if os.getenv(env_var):
            return provider_name
    return "gemini"  # Default fallback


async def _verify_existing_providers(
    provider_service: ProviderService,
) -> bool | None:
    """Check existing providers and verify accessibility.

    Returns:
        True if existing providers are accessible (skip initialization).
        None if providers need recreation (encryption key changed).
    """
    existing_providers = await provider_service.list_providers(include_inactive=False)
    if not existing_providers:
        return None

    try:
        from src.infrastructure.security.encryption_service import get_encryption_service

        test_provider = existing_providers[0]
        encryption_service = get_encryption_service()
        _ = encryption_service.decrypt(test_provider.api_key_encrypted)
        logger.info(
            f"Existing provider {test_provider.name} is accessible, skipping initialization"
        )
        return True
    except Exception as e:
        logger.warning(
            f"Existing provider {existing_providers[0].name} is not accessible: {e}. "
            f"This usually means the encryption key has changed. Will recreate providers..."
        )
        return None


async def _create_and_verify_provider(
    provider_service: ProviderService,
    provider_config: ProviderConfigCreate,
) -> bool:
    """Create a provider and verify it is accessible.

    Returns:
        True if provider was created (or already existed), False on error.
    """
    try:
        created_provider = await provider_service.create_provider(provider_config)

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


async def initialize_default_llm_providers(force_recreate: bool = False) -> bool:
    """
    Initialize default LLM provider from environment configuration.

    This function checks if any LLM providers exist in the database.
    If none exist, or if force_recreate is True, it creates a default provider
    using the configured LLM_PROVIDER environment variable and its associated API keys.

    Args:
        force_recreate: If True, clear all existing providers and recreate.

    Returns:
        True if a default provider was created, False otherwise
    """
    provider_service = ProviderService()

    if force_recreate:
        logger.info("Force recreate requested, clearing existing providers...")
        cleared_count = await provider_service.clear_all_providers()
        logger.info(f"Cleared {cleared_count} existing providers")
    else:
        verify_result = await _verify_existing_providers(provider_service)
        if verify_result is True:
            return False
        if verify_result is None and await provider_service.list_providers(include_inactive=False):
            return await initialize_default_llm_providers(force_recreate=True)

    logger.info("Creating default LLM provider from environment...")

    provider_name = os.getenv("LLM_PROVIDER", "").lower()
    if not provider_name:
        provider_name = _auto_detect_provider()

    provider_type = PROVIDER_TYPE_MAP.get(provider_name)
    if provider_type is None:
        logger.warning(
            f"Unknown provider type '{provider_name}'. "
            f"Supported types: {list(PROVIDER_TYPE_MAP.keys())}"
        )
        return False

    provider_config = _build_provider_config(provider_name)
    if provider_config is None:
        logger.warning(f"Could not build provider config for '{provider_name}': API key not found")
        return False

    return await _create_and_verify_provider(provider_service, provider_config)


# ---------------------------------------------------------------------------
# Provider environment configuration registry
# ---------------------------------------------------------------------------
# Each entry maps a canonical provider name (or alias set) to a callable that
# reads the relevant env vars and returns a dict with the provider settings.
# This replaces the long if/elif chain in _build_provider_config.


def _env_gemini() -> dict[str, Any]:
    return {
        "api_key": os.getenv("GEMINI_API_KEY"),
        "llm_model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "embedding_model": os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004"),
        "reranker_model": os.getenv("GEMINI_RERANK_MODEL", "gemini-2.0-flash"),
    }


def _env_zai() -> dict[str, Any]:
    return {
        "api_key": os.getenv("ZAI_API_KEY") or os.getenv("ZHIPU_API_KEY"),
        "llm_model": os.getenv("ZAI_MODEL") or os.getenv("ZHIPU_MODEL", "glm-4-plus"),
        "llm_small_model": os.getenv("ZAI_SMALL_MODEL")
        or os.getenv("ZHIPU_SMALL_MODEL", "glm-4-flash"),
        "embedding_model": os.getenv("ZAI_EMBEDDING_MODEL")
        or os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-3"),
        "reranker_model": os.getenv("ZAI_RERANK_MODEL")
        or os.getenv("ZHIPU_RERANK_MODEL", "glm-4-flash"),
        "base_url": os.getenv("ZAI_BASE_URL")
        or os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
    }


def _env_dashscope() -> dict[str, Any]:
    return {
        "api_key": os.getenv("DASHSCOPE_API_KEY"),
        "llm_model": os.getenv("DASHSCOPE_MODEL", "qwen-plus"),
        "llm_small_model": os.getenv("DASHSCOPE_SMALL_MODEL", "qwen-turbo"),
        "embedding_model": os.getenv("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v3"),
        "reranker_model": os.getenv("DASHSCOPE_RERANK_MODEL", "qwen-turbo"),
        "base_url": os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    }


def _env_openai() -> dict[str, Any]:
    return {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "llm_model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "llm_small_model": os.getenv("OPENAI_SMALL_MODEL", "gpt-4o-mini"),
        "embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        "reranker_model": os.getenv("OPENAI_RERANK_MODEL", "gpt-4o-mini"),
        "base_url": os.getenv("OPENAI_BASE_URL"),
    }


def _env_deepseek() -> dict[str, Any]:
    return {
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "llm_model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "llm_small_model": os.getenv("DEEPSEEK_SMALL_MODEL", "deepseek-coder"),
        "reranker_model": os.getenv("DEEPSEEK_RERANK_MODEL", "deepseek-chat"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    }


def _env_minimax() -> dict[str, Any]:
    return {
        "api_key": os.getenv("MINIMAX_API_KEY"),
        "llm_model": os.getenv("MINIMAX_MODEL", "abab6.5-chat"),
        "llm_small_model": os.getenv("MINIMAX_SMALL_MODEL", "abab6.5s-chat"),
        "embedding_model": os.getenv("MINIMAX_EMBEDDING_MODEL", "embo-01"),
        "reranker_model": os.getenv("MINIMAX_RERANK_MODEL", "abab6.5-chat"),
        "base_url": os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
    }


def _env_kimi() -> dict[str, Any]:
    return {
        "api_key": os.getenv("KIMI_API_KEY"),
        "llm_model": os.getenv("KIMI_MODEL", "moonshot-v1-8k"),
        "llm_small_model": os.getenv("KIMI_SMALL_MODEL", "moonshot-v1-8k"),
        "embedding_model": os.getenv("KIMI_EMBEDDING_MODEL", "kimi-embedding-1"),
        "reranker_model": os.getenv("KIMI_RERANK_MODEL", "kimi-rerank-1"),
        "base_url": os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
    }


def _env_anthropic() -> dict[str, Any]:
    return {
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "llm_model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20240620"),
        "llm_small_model": os.getenv("ANTHROPIC_SMALL_MODEL", "claude-3-haiku-20240307"),
        "embedding_model": os.getenv("ANTHROPIC_EMBEDDING_MODEL", ""),
        "reranker_model": os.getenv("ANTHROPIC_RERANK_MODEL", "claude-3-haiku-20240307"),
        "base_url": os.getenv("ANTHROPIC_BASE_URL"),
    }


def _env_ollama() -> dict[str, Any]:
    return {
        "api_key": os.getenv("OLLAMA_API_KEY"),
        "llm_model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        "llm_small_model": os.getenv("OLLAMA_SMALL_MODEL", "llama3.1:8b"),
        "embedding_model": os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
        "reranker_model": os.getenv("OLLAMA_RERANK_MODEL", "llama3.1:8b"),
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    }


def _env_lmstudio() -> dict[str, Any]:
    return {
        "api_key": os.getenv("LMSTUDIO_API_KEY"),
        "llm_model": os.getenv("LMSTUDIO_MODEL", "local-model"),
        "llm_small_model": os.getenv("LMSTUDIO_SMALL_MODEL", "local-model"),
        "embedding_model": os.getenv(
            "LMSTUDIO_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5"
        ),
        "reranker_model": os.getenv("LMSTUDIO_RERANK_MODEL", "local-model"),
        "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
    }


_PROVIDER_ENV_REGISTRY: dict[str, Any] = {
    "gemini": _env_gemini,
    "zhipu": _env_zai,
    "zai": _env_zai,
    "dashscope": _env_dashscope,
    "openai": _env_openai,
    "deepseek": _env_deepseek,
    "minimax": _env_minimax,
    "kimi": _env_kimi,
    "moonshot": _env_kimi,
    "anthropic": _env_anthropic,
    "claude": _env_anthropic,
    "ollama": _env_ollama,
    "lmstudio": _env_lmstudio,
}


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

    env_fn = _PROVIDER_ENV_REGISTRY.get(provider_name)
    if env_fn is None:
        return None

    env = env_fn()
    api_key = env.get("api_key")

    # Check if API key is available (except local providers with optional key)
    if should_require_api_key(provider_type) and not api_key:
        return None

    # Create provider config
    return ProviderConfigCreate(
        name=f"Default {provider_name.title()}",
        provider_type=provider_type,
        api_key=api_key,
        base_url=env.get("base_url"),
        llm_model=env.get("llm_model") or f"{provider_name}-default",
        llm_small_model=env.get("llm_small_model"),
        embedding_model=env.get("embedding_model"),
        reranker_model=env.get("reranker_model"),
        is_active=True,
        is_default=True,
        config={},  # Additional provider-specific config can be added here
    )
