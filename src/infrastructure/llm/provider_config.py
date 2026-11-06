"""
LLM Provider Constants and Unified Configuration.

Provides:
- Provider prefix enumeration for LiteLLM model names
- Unified configuration objects
- Model registry constants

Usage:
    from src.infrastructure.llm.provider_config import ProviderPrefix, UnifiedLLMConfig

    config = UnifiedLLMConfig(
        provider_type=ProviderType.DASHSCOPE,
        model="qwen-max",
        temperature=0.7,
    )
    litellm_model = config.get_litellm_model_name()
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.domain.llm_providers.models import ProviderType
from src.domain.llm_providers.provider_catalog import (
    MODEL_PREFIXES,
    TRANSPORT_PREFIX,
    runtime_model_table,
    transport_prefix,
)


class ProviderPrefix(StrEnum):
    """
    Provider prefixes for LiteLLM model names.

    LiteLLM requires provider prefixes for some models to disambiguate
    between providers with similar model names.

    Example:
        "dashscope/qwen-max"  # Qwen via Dashscope
        "openai/gpt-4"        # GPT-4 via OpenAI
        "gemini/gemini-pro"   # Gemini via Google
    """

    # Major providers
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    DASHSCOPE = "dashscope"
    DEEPSEEK = "deepseek"
    MINIMAX = "minimax"
    ZAI = "zai"  # Zhipu AI
    KIMI = "openai"  # Kimi uses OpenAI-compatible API
    MISTRAL = "mistral"
    GROQ = "groq"
    XAI = "xai"
    COHERE = "cohere"

    # Cloud providers
    BEDROCK = "bedrock"
    VERTEX_AI = "vertex_ai"
    AZURE = "azure"

    # Local providers
    OLLAMA = "ollama"
    LMSTUDIO = "openai"  # LM Studio uses OpenAI-compatible API
    VOLCENGINE = "volcengine"

    # Default (no prefix needed)
    DEFAULT = ""


MODEL_PREFIX_TO_PROVIDER: dict[str, ProviderType] = {
    prefix: ProviderType(provider_type) for prefix, provider_type in MODEL_PREFIXES
}

DEFAULT_MODELS: dict[ProviderType, dict[str, str]] = {
    ProviderType(provider_type): models for provider_type, models in runtime_model_table().items()
}

_PREFIXED_PROVIDER_TYPES = {
    ProviderType(provider_type)
    for provider_type, spec in TRANSPORT_PREFIX.items()
    if spec.prefix_model_names
}


def get_provider_prefix(provider_type: ProviderType) -> ProviderPrefix:
    """
    Get LiteLLM provider prefix for provider type.

    Args:
        provider_type: Provider type enum

    Returns:
        ProviderPrefix enum value
    """
    spec = transport_prefix(provider_type)
    if spec is None:
        return ProviderPrefix.DEFAULT
    return ProviderPrefix[spec.member]


def infer_provider_from_model(model_name: str) -> ProviderType:
    """
    Infer provider type from model name.

    Args:
        model_name: Model name string

    Returns:
        Inferred ProviderType (defaults to OPENAI)
    """
    model_lower = model_name.lower()

    for prefix, provider in MODEL_PREFIX_TO_PROVIDER.items():
        if model_lower.startswith(prefix):
            return provider

    return ProviderType.OPENAI


@dataclass
class UnifiedLLMConfig:
    """
    Unified configuration for LLM operations.

    Replaces separate LLMConfig, EmbedderConfig, StreamConfig with
    a single comprehensive configuration object.

    Example:
        config = UnifiedLLMConfig(
            provider_type=ProviderType.DASHSCOPE,
            model="qwen-max",
            temperature=0.7,
            max_tokens=4096,
            api_key="sk-...",
        )

        # Get LiteLLM model name with prefix
        litellm_model = config.get_litellm_model_name()

        # Get default model for provider
        default_model = config.get_default_model("completion")
    """

    # Provider configuration
    provider_type: ProviderType
    api_key: str | None = None
    base_url: str | None = None

    # Model configuration
    model: str = ""  # Primary model (medium/large)
    small_model: str | None = None  # Small/fast model
    embedding_model: str | None = None
    reranker_model: str | None = None

    # Generation parameters
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: int = 600  # seconds

    # Provider-specific options
    provider_options: dict[str, Any] = field(default_factory=dict)

    # Caching
    cache_enabled: bool = True

    def __post_init__(self) -> None:
        """Validate and normalize configuration."""
        # Use default model if not specified
        if not self.model:
            self.model = self.get_default_model("completion")

        # Use default small model if not specified
        if not self.small_model:
            self.small_model = self.get_default_model("completion", use_small=True)

    def get_default_model(
        self,
        operation: str = "completion",
        use_small: bool = False,
    ) -> str:
        """
        Get default model for provider and operation.

        Args:
            operation: Operation type (completion, embedding, rerank)
            use_small: Use small/fast model variant

        Returns:
            Default model name
        """
        provider_defaults = DEFAULT_MODELS.get(self.provider_type, {})

        if operation == "completion":
            if use_small:
                # For some providers, small = flash/haiku/luna variants
                return provider_defaults.get("completion", "gpt-6-luna")
            return provider_defaults.get("completion_medium", "gpt-6-astra")

        return provider_defaults.get(operation, "gpt-6-luna")

    def get_litellm_model_name(self, model: str | None = None) -> str:
        """
        Get model name in LiteLLM format with provider prefix.

        Args:
            model: Model name (uses config.model if None)

        Returns:
            LiteLLM-formatted model name
        """
        model_name = model or self.model

        # Skip if already prefixed
        if "/" in model_name:
            return model_name

        # Get provider prefix
        prefix = get_provider_prefix(self.provider_type)

        if self.provider_type in _PREFIXED_PROVIDER_TYPES and prefix.value:
            return f"{prefix.value}/{model_name}"

        return model_name

    def get_model_for_size(self, size: str) -> str:
        """
        Get model name for requested size.

        Args:
            size: Model size (small, medium, large)

        Returns:
            Model name
        """
        if size == "small" and self.small_model:
            return self.small_model
        elif size == "large":
            # For large, use medium model (may be same)
            return self.get_default_model("completion", use_small=False)
        return self.model

    def to_kwargs(self) -> dict[str, Any]:
        """
        Convert to kwargs for LiteLLM calls.

        Returns:
            Dictionary of kwargs
        """
        return {
            "model": self.get_litellm_model_name(),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            **self.provider_options,
        }


@dataclass
class ProviderHealthConfig:
    """
    Health check configuration for providers.

    Example:
        health_config = ProviderHealthConfig(
            provider_type=ProviderType.DASHSCOPE,
            health_check_model="qwen-turbo",
            failure_threshold=5,
            recovery_timeout=60,
        )
    """

    provider_type: ProviderType
    health_check_model: str | None = None
    health_check_endpoint: str | None = None

    # Circuit breaker settings
    failure_threshold: int = 5
    success_threshold: int = 2
    recovery_timeout: float = 60.0  # seconds
    half_open_max_calls: int = 3

    # Rate limiter settings
    max_concurrent_requests: int = 10
    rate_limit_window: float = 1.0  # seconds

    def __post_init__(self) -> None:
        """Set default health check model if not specified."""
        if not self.health_check_model:
            defaults = DEFAULT_MODELS.get(self.provider_type, {})
            self.health_check_model = defaults.get("completion", "gpt-4o-mini")
