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
from src.domain.llm_providers.models import OperationType, ProviderConfigCreate, ProviderType
from src.domain.llm_providers.provider_catalog import (
    AUTO_DETECT_ENV,
    STARTUP_ALIASES,
    detection_defaults,
)
from src.infrastructure.llm.provider_credentials import should_require_api_key

logger = logging.getLogger(__name__)

# Provider type mapping from config name to ProviderType enum.
PROVIDER_TYPE_MAP: dict[str, ProviderType] = {
    alias: ProviderType(provider_type) for alias, provider_type in STARTUP_ALIASES.items()
}

# Auto-detection order: env var -> provider name
_PROVIDER_AUTO_DETECT: list[tuple[str, str]] = list(AUTO_DETECT_ENV)

_LOCAL_FALLBACK_PROVIDER = "ollama"


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
        False if existing providers cannot be verified (preserve their records).
        None only when no providers are stored.
    """
    existing_providers = await provider_service.list_providers(include_inactive=True)
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
    except Exception:
        logger.warning(
            "Existing LLM providers could not be verified; preserving stored configurations."
        )
        return False


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
            f"Created and verified default provider: {created_provider.name} "
            f"({created_provider.provider_type}, operation={created_provider.operation_type})"
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
        if verify_result is not None:
            # Verification failure is not authorization to destroy persisted configuration.
            return False

    logger.info("Creating default LLM provider from environment...")

    provider_name = os.getenv("LLM_PROVIDER", "").lower()
    if not provider_name:
        provider_name = _auto_detect_provider()

    resolved_provider_name = provider_name
    provider_type = PROVIDER_TYPE_MAP.get(resolved_provider_name)
    if provider_type is None:
        logger.warning(
            f"Unknown provider type '{provider_name}'. "
            f"Supported types: {list(PROVIDER_TYPE_MAP.keys())}. "
            f"Falling back to local provider '{_LOCAL_FALLBACK_PROVIDER}'."
        )
        resolved_provider_name = _LOCAL_FALLBACK_PROVIDER

    provider_configs = _build_provider_configs(resolved_provider_name)
    if not provider_configs and resolved_provider_name != _LOCAL_FALLBACK_PROVIDER:
        logger.warning(
            f"Could not build provider config for '{resolved_provider_name}': API key not found. "
            f"Falling back to local provider '{_LOCAL_FALLBACK_PROVIDER}'."
        )
        provider_configs = _build_provider_configs(_LOCAL_FALLBACK_PROVIDER)

    if not provider_configs:
        logger.warning(
            f"Could not build provider config for '{resolved_provider_name}' "
            f"or fallback '{_LOCAL_FALLBACK_PROVIDER}'."
        )
        return False

    created_any = False
    for provider_config in provider_configs:
        created_any = (
            await _create_and_verify_provider(provider_service, provider_config)
        ) or created_any
    return created_any


# ---------------------------------------------------------------------------
# Provider environment configuration registry
# ---------------------------------------------------------------------------
# Each entry maps a canonical provider name (or alias set) to a callable that
# reads the relevant env vars and returns a dict with the provider settings.
# This replaces the long if/elif chain in provider env config building.


_DETECTION_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "openai": {
        "api_key": ("OPENAI_API_KEY",),
        "llm_model": ("OPENAI_MODEL",),
        "llm_small_model": ("OPENAI_SMALL_MODEL",),
        "embedding_model": ("OPENAI_EMBEDDING_MODEL",),
        "reranker_model": ("OPENAI_RERANK_MODEL",),
        "base_url": ("OPENAI_BASE_URL",),
    },
    "openrouter": {
        "api_key": ("OPENROUTER_API_KEY",),
        "llm_model": ("OPENROUTER_MODEL",),
        "llm_small_model": ("OPENROUTER_SMALL_MODEL",),
        "embedding_model": ("OPENROUTER_EMBEDDING_MODEL",),
        "reranker_model": ("OPENROUTER_RERANK_MODEL",),
        "base_url": ("OPENROUTER_BASE_URL",),
    },
    "gemini": {
        "api_key": ("GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"),
        "llm_model": ("GEMINI_MODEL",),
        "llm_small_model": ("GEMINI_SMALL_MODEL",),
        "embedding_model": ("GEMINI_EMBEDDING_MODEL",),
        "reranker_model": ("GEMINI_RERANK_MODEL",),
    },
    "dashscope": {
        "api_key": ("DASHSCOPE_API_KEY",),
        "llm_model": ("DASHSCOPE_MODEL",),
        "llm_small_model": ("DASHSCOPE_SMALL_MODEL",),
        "embedding_model": ("DASHSCOPE_EMBEDDING_MODEL",),
        "reranker_model": ("DASHSCOPE_RERANK_MODEL",),
        "base_url": ("DASHSCOPE_BASE_URL",),
    },
    "deepseek": {
        "api_key": ("DEEPSEEK_API_KEY",),
        "llm_model": ("DEEPSEEK_MODEL",),
        "llm_small_model": ("DEEPSEEK_SMALL_MODEL",),
        "reranker_model": ("DEEPSEEK_RERANK_MODEL",),
        "base_url": ("DEEPSEEK_BASE_URL",),
    },
    "minimax": {
        "api_key": ("MINIMAX_API_KEY",),
        "llm_model": ("MINIMAX_MODEL",),
        "llm_small_model": ("MINIMAX_SMALL_MODEL",),
        "embedding_model": ("MINIMAX_EMBEDDING_MODEL",),
        "reranker_model": ("MINIMAX_RERANK_MODEL",),
        "base_url": ("MINIMAX_BASE_URL",),
    },
    "zai": {
        "api_key": ("ZAI_API_KEY", "ZHIPU_API_KEY"),
        "llm_model": ("ZAI_MODEL", "ZHIPU_MODEL"),
        "llm_small_model": ("ZAI_SMALL_MODEL", "ZHIPU_SMALL_MODEL"),
        "embedding_model": ("ZAI_EMBEDDING_MODEL", "ZHIPU_EMBEDDING_MODEL"),
        "reranker_model": ("ZAI_RERANK_MODEL", "ZHIPU_RERANK_MODEL"),
        "base_url": ("ZAI_BASE_URL", "ZHIPU_BASE_URL"),
    },
    "kimi": {
        "api_key": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
        "llm_model": ("KIMI_MODEL", "MOONSHOT_MODEL"),
        "llm_small_model": ("KIMI_SMALL_MODEL", "MOONSHOT_SMALL_MODEL"),
        "embedding_model": ("KIMI_EMBEDDING_MODEL",),
        "reranker_model": ("KIMI_RERANK_MODEL",),
        "base_url": ("KIMI_BASE_URL",),
    },
    "xai": {
        "api_key": ("XAI_API_KEY",),
        "llm_model": ("XAI_MODEL",),
        "llm_small_model": ("XAI_SMALL_MODEL",),
        "reranker_model": ("XAI_RERANK_MODEL",),
        "base_url": ("XAI_BASE_URL",),
    },
    "anthropic": {
        "api_key": ("ANTHROPIC_API_KEY",),
        "llm_model": ("ANTHROPIC_MODEL",),
        "llm_small_model": ("ANTHROPIC_SMALL_MODEL",),
        "embedding_model": ("ANTHROPIC_EMBEDDING_MODEL",),
        "reranker_model": ("ANTHROPIC_RERANK_MODEL",),
        "base_url": ("ANTHROPIC_BASE_URL",),
    },
    "ollama": {
        "api_key": ("OLLAMA_API_KEY",),
        "llm_model": ("OLLAMA_MODEL",),
        "llm_small_model": ("OLLAMA_SMALL_MODEL",),
        "embedding_model": ("OLLAMA_EMBEDDING_MODEL",),
        "reranker_model": ("OLLAMA_RERANK_MODEL",),
        "base_url": ("OLLAMA_BASE_URL",),
    },
    "lmstudio": {
        "api_key": ("LMSTUDIO_API_KEY",),
        "llm_model": ("LMSTUDIO_MODEL",),
        "llm_small_model": ("LMSTUDIO_SMALL_MODEL",),
        "embedding_model": ("LMSTUDIO_EMBEDDING_MODEL",),
        "reranker_model": ("LMSTUDIO_RERANK_MODEL",),
        "base_url": ("LMSTUDIO_BASE_URL",),
    },
    "volcengine": {
        "api_key": ("VOLCENGINE_API_KEY", "ARK_API_KEY"),
        "llm_model": ("VOLCENGINE_MODEL",),
        "llm_small_model": ("VOLCENGINE_SMALL_MODEL",),
        "embedding_model": ("VOLCENGINE_EMBEDDING_MODEL",),
        "reranker_model": ("VOLCENGINE_RERANK_MODEL",),
        "base_url": ("VOLCENGINE_BASE_URL",),
    },
}


def _chain_env(names: tuple[str, ...], default: str | None = None) -> str | None:
    """Read the first non-empty env var, applying a fallback only on the last name."""
    if not names:
        return default
    for name in names[:-1]:
        value = os.getenv(name)
        if value:
            return value
    last = names[-1]
    if default is None:
        return os.getenv(last)
    return os.getenv(last, default)


def _detected_provider_config(provider_name: str) -> dict[str, Any]:
    """Build the historical startup env view for one canonical provider."""
    defaults = detection_defaults(provider_name)
    fields = _DETECTION_FIELDS[provider_name]
    if defaults is None:
        return {}
    fallbacks = {
        "llm_model": defaults.llm_model,
        "llm_small_model": defaults.llm_small_model,
        "embedding_model": defaults.embedding_model,
        "base_url": defaults.base_url,
    }
    return {key: _chain_env(names, fallbacks.get(key)) for key, names in fields.items()}


def _detected_from_alias(alias: str) -> dict[str, Any]:
    return _detected_provider_config(STARTUP_ALIASES[alias])


_PROVIDER_ENV_REGISTRY: dict[str, Any] = {
    alias: (lambda alias=alias: _detected_from_alias(alias)) for alias in STARTUP_ALIASES
}


def detect_env_providers() -> dict[str, dict[str, Any]]:
    """
    Detect LLM providers configured via environment variables.

    Scans all known provider env vars and returns their configurations.
    Used by the env-detection API endpoint for frontend auto-fill.

    Returns:
        Dict mapping provider name to env config dict with keys:
        api_key, base_url, llm_model, llm_small_model, embedding_model, reranker_model
    """
    detected: dict[str, dict[str, Any]] = {}
    seen_providers: set[str] = set()

    for env_var, provider_name in _PROVIDER_AUTO_DETECT:
        # Skip duplicates (e.g. ZAI_API_KEY and ZHIPU_API_KEY both map to "zai")
        if provider_name in seen_providers:
            continue

        if not os.getenv(env_var):
            continue

        env_fn = _PROVIDER_ENV_REGISTRY.get(provider_name)
        if env_fn is None:
            continue

        env_config = env_fn()
        # Only include providers with a valid key (or local providers)
        provider_type = PROVIDER_TYPE_MAP.get(provider_name)
        if (
            provider_type
            and should_require_api_key(provider_type)
            and not env_config.get("api_key")
        ):
            continue

        detected[provider_name] = env_config
        seen_providers.add(provider_name)

    return detected


def _build_provider_configs(provider_name: str) -> list[ProviderConfigCreate]:
    """
    Build operation-specific provider configs from environment variables.

    Each returned row owns exactly one operation role. LLM, embedding, and
    rerank models are no longer stored together in one provider config.
    """
    provider_type = PROVIDER_TYPE_MAP[provider_name]

    env_fn = _PROVIDER_ENV_REGISTRY.get(provider_name)
    if env_fn is None:
        return []

    env = env_fn()
    api_key = env.get("api_key")

    # Check if API key is available (except local providers with optional key)
    if should_require_api_key(provider_type) and not api_key:
        return []

    common: dict[str, Any] = {
        "provider_type": provider_type,
        "api_key": api_key,
        "base_url": env.get("base_url"),
        "is_active": True,
        "is_default": True,
        "tenant_id": "default",
        "is_enabled": True,
        "config": {},  # Additional provider-specific config can be added here
    }

    configs: list[ProviderConfigCreate] = [
        ProviderConfigCreate(
            name=f"Default {provider_name.title()} LLM",
            operation_type=OperationType.LLM,
            llm_model=env.get("llm_model") or f"{provider_name}-default",
            llm_small_model=env.get("llm_small_model"),
            pool_enabled=True,
            **common,
        )
    ]

    embedding_model = env.get("embedding_model")
    if embedding_model:
        configs.append(
            ProviderConfigCreate(
                name=f"Default {provider_name.title()} Embedding",
                operation_type=OperationType.EMBEDDING,
                embedding_model=embedding_model,
                pool_enabled=False,
                **common,
            )
        )

    reranker_model = env.get("reranker_model")
    if reranker_model:
        configs.append(
            ProviderConfigCreate(
                name=f"Default {provider_name.title()} Rerank",
                operation_type=OperationType.RERANK,
                reranker_model=reranker_model,
                pool_enabled=False,
                **common,
            )
        )

    return configs
