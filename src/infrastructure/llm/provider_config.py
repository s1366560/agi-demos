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
from enum import Enum
from typing import Any

from src.domain.llm_providers.models import ProviderType


class ProviderPrefix(str, Enum):
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
    COHERE = "cohere"

    # Cloud providers
    BEDROCK = "bedrock"
    VERTEX_AI = "vertex_ai"
    AZURE = "azure"

    # Local providers
    OLLAMA = "ollama"
    LMSTUDIO = "openai"  # LM Studio uses OpenAI-compatible API

    # Default (no prefix needed)
    DEFAULT = ""


# Model name prefixes for provider inference
MODEL_PREFIX_TO_PROVIDER: dict[str, ProviderType] = {
    "qwen-": ProviderType.DASHSCOPE,
    "qwq-": ProviderType.DASHSCOPE,
    "gpt-": ProviderType.OPENAI,
    "o1-": ProviderType.OPENAI,
    "gemini-": ProviderType.GEMINI,
    "deepseek-": ProviderType.DEEPSEEK,
    "minimax-": ProviderType.MINIMAX,
    "abab": ProviderType.MINIMAX,
    "glm-": ProviderType.ZAI,
    "claude-": ProviderType.ANTHROPIC,
    "mistral-": ProviderType.MISTRAL,
    "codestral-": ProviderType.MISTRAL,
    "rerank-": ProviderType.COHERE,
    "embed-": ProviderType.OPENAI,
    "text-embedding-": ProviderType.OPENAI,
}


# Default models by provider and operation type
DEFAULT_MODELS: dict[ProviderType, dict[str, str]] = {
    ProviderType.OPENAI: {
        "completion": "gpt-4o-mini",
        "completion_medium": "gpt-4o",
        "embedding": "text-embedding-3-small",
        "rerank": "gpt-4o-mini",  # LLM-based rerank
    },
    ProviderType.ANTHROPIC: {
        "completion": "claude-3-5-haiku-20241022",
        "completion_medium": "claude-3-5-sonnet-20241022",
        "embedding": "text-embedding-3-small",  # Uses OpenAI
        "rerank": "claude-3-5-haiku-20241022",
    },
    ProviderType.GEMINI: {
        "completion": "gemini-1.5-flash",
        "completion_medium": "gemini-1.5-pro",
        "embedding": "text-embedding-004",
        "rerank": "gemini-1.5-flash",
    },
    ProviderType.DASHSCOPE: {
        "completion": "qwen-turbo",
        "completion_medium": "qwen-max",
        "embedding": "text-embedding-v3",
        "rerank": "qwen-turbo",
    },
    ProviderType.KIMI: {
        "completion": "kimi-latest",
        "completion_medium": "kimi-latest",
        "embedding": "kimi-embedding-1",
        "rerank": "kimi-rerank-1",
    },
    ProviderType.DEEPSEEK: {
        "completion": "deepseek-chat",
        "completion_medium": "deepseek-chat",
        "embedding": "text-embedding-v3",  # Uses Dashscope
        "rerank": "deepseek-chat",
    },
    ProviderType.MINIMAX: {
        "completion": "abab6.5-chat",
        "completion_medium": "abab6.5-chat",
        "embedding": "embo-01",
        "rerank": "abab6.5-chat",
    },
    ProviderType.ZAI: {
        "completion": "glm-4-flash",
        "completion_medium": "glm-4",
        "embedding": "embedding-3",
        "rerank": "glm-4-flash",
    },
    ProviderType.MISTRAL: {
        "completion": "mistral-small-latest",
        "completion_medium": "mistral-medium-latest",
        "embedding": "mistral-embed",
        "rerank": "mistral-small-latest",
    },
    ProviderType.GROQ: {
        "completion": "llama-3.1-8b-instant",
        "completion_medium": "llama-3.1-70b-versatile",
        "embedding": "text-embedding-3-small",  # Uses OpenAI
        "rerank": "llama-3.1-8b-instant",
    },
    ProviderType.COHERE: {
        "completion": "command-r-plus",
        "completion_medium": "command-r-plus",
        "embedding": "embed-english-v3.0",
        "rerank": "rerank-english-v3.0",
    },
    ProviderType.OLLAMA: {
        "completion": "llama3.1:8b",
        "completion_medium": "llama3.1:70b",
        "embedding": "nomic-embed-text",
        "rerank": "llama3.1:8b",
    },
    ProviderType.LMSTUDIO: {
        "completion": "local-model",
        "completion_medium": "local-model",
        "embedding": "text-embedding-nomic-embed-text-v1.5",
        "rerank": "local-model",
    },
    ProviderType.BEDROCK: {
        "completion": "anthropic.claude-3-haiku-20240307-v1:0",
        "completion_medium": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "embedding": "amazon.titan-embed-text-v1",
        "rerank": "anthropic.claude-3-haiku-20240307-v1:0",
    },
    ProviderType.VERTEX: {
        "completion": "gemini-1.5-flash-001",
        "completion_medium": "gemini-1.5-pro-001",
        "embedding": "textembedding-gecko",
        "rerank": "gemini-1.5-flash-001",
    },
    ProviderType.AZURE_OPENAI: {
        "completion": "gpt-4o-mini",
        "completion_medium": "gpt-4o",
        "embedding": "text-embedding-3-small",
        "rerank": "gpt-4o-mini",
    },
}


def get_provider_prefix(provider_type: ProviderType) -> ProviderPrefix:
    """
    Get LiteLLM provider prefix for provider type.

    Args:
        provider_type: Provider type enum

    Returns:
        ProviderPrefix enum value
    """
    prefix_map: dict[ProviderType, ProviderPrefix] = {
        ProviderType.OPENAI: ProviderPrefix.OPENAI,
        ProviderType.ANTHROPIC: ProviderPrefix.ANTHROPIC,
        ProviderType.GEMINI: ProviderPrefix.GEMINI,
        ProviderType.DASHSCOPE: ProviderPrefix.DASHSCOPE,
        ProviderType.DEEPSEEK: ProviderPrefix.DEEPSEEK,
        ProviderType.MINIMAX: ProviderPrefix.MINIMAX,
        ProviderType.ZAI: ProviderPrefix.ZAI,
        ProviderType.KIMI: ProviderPrefix.KIMI,
        ProviderType.MISTRAL: ProviderPrefix.MISTRAL,
        ProviderType.GROQ: ProviderPrefix.GROQ,
        ProviderType.COHERE: ProviderPrefix.COHERE,
        ProviderType.BEDROCK: ProviderPrefix.BEDROCK,
        ProviderType.VERTEX: ProviderPrefix.VERTEX_AI,
        ProviderType.AZURE_OPENAI: ProviderPrefix.AZURE,
        ProviderType.OLLAMA: ProviderPrefix.OLLAMA,
        ProviderType.LMSTUDIO: ProviderPrefix.LMSTUDIO,
    }
    return prefix_map.get(provider_type, ProviderPrefix.DEFAULT)


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
                # For some providers, small = flash/haiku/turbo variants
                return provider_defaults.get("completion", "gpt-4o-mini")
            return provider_defaults.get("completion_medium", "gpt-4o")

        return provider_defaults.get(operation, "gpt-4o-mini")

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

        # Special handling for providers that need explicit prefix
        needs_prefix = {
            ProviderType.ANTHROPIC,
            ProviderType.GEMINI,
            ProviderType.DASHSCOPE,
            ProviderType.MISTRAL,
            ProviderType.GROQ,
            ProviderType.DEEPSEEK,
            ProviderType.MINIMAX,
            ProviderType.ZAI,
            ProviderType.COHERE,
            ProviderType.BEDROCK,
            ProviderType.VERTEX,
            ProviderType.OLLAMA,
        }

        if self.provider_type in needs_prefix and prefix.value:
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
