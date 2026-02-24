"""
LLM Provider Configuration Domain Models

This module contains Pydantic models for LLM provider configuration,
following Domain-Driven Design principles.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================================
# Model Metadata Models (for context window management)
# ============================================================================


class ModelCapability(str, Enum):
    """Model capabilities"""

    CHAT = "chat"
    COMPLETION = "completion"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    CODE = "code"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class ModelMetadata(BaseModel):
    """
    Model capability metadata for context window management.

    This defines the capabilities and limits of a specific LLM model,
    enabling dynamic context window sizing and token budget allocation.
    """

    name: str = Field(..., description="Model identifier (e.g., 'gpt-4-turbo')")
    context_length: int = Field(
        default=128000, ge=1024, description="Maximum context window size in tokens"
    )
    max_output_tokens: int = Field(
        default=4096, ge=1, description="Maximum output tokens per request"
    )
    input_cost_per_1m: float | None = Field(
        None, ge=0, description="Cost per 1M input tokens (USD)"
    )
    output_cost_per_1m: float | None = Field(
        None, ge=0, description="Cost per 1M output tokens (USD)"
    )
    capabilities: list[ModelCapability] = Field(
        default_factory=list, description="Model capabilities"
    )
    supports_streaming: bool = Field(default=True, description="Whether model supports streaming")
    supports_json_mode: bool = Field(
        default=False, description="Whether model supports JSON output mode"
    )

    class Config:
        use_enum_values = True


class ProviderModelsConfig(BaseModel):
    """
    Models configuration stored in provider config.models field.

    This structure is stored in the JSONB config column of llm_provider_configs table,
    allowing dynamic retrieval of model-specific context lengths and capabilities.
    """

    llm: ModelMetadata = Field(..., description="Primary LLM model metadata")
    llm_small: ModelMetadata | None = Field(None, description="Smaller/faster LLM metadata")
    embedding: ModelMetadata | None = Field(None, description="Embedding model metadata")
    reranker: ModelMetadata | None = Field(None, description="Reranker model metadata")


# Default model metadata for common providers (used as fallback)
DEFAULT_MODEL_METADATA: dict[str, ModelMetadata] = {
    # OpenAI models
    "gpt-4-turbo": ModelMetadata(
        name="gpt-4-turbo",
        context_length=128000,
        max_output_tokens=4096,
        input_cost_per_1m=10.0,
        output_cost_per_1m=30.0,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
    "gpt-4o": ModelMetadata(
        name="gpt-4o",
        context_length=128000,
        max_output_tokens=16384,
        input_cost_per_1m=2.5,
        output_cost_per_1m=10.0,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
    "gpt-4o-mini": ModelMetadata(
        name="gpt-4o-mini",
        context_length=128000,
        max_output_tokens=16384,
        input_cost_per_1m=0.15,
        output_cost_per_1m=0.6,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
    # Gemini models
    "gemini-2.0-flash": ModelMetadata(
        name="gemini-2.0-flash",
        context_length=1048576,
        max_output_tokens=8192,
        input_cost_per_1m=0.075,
        output_cost_per_1m=0.3,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
    "gemini-1.5-pro": ModelMetadata(
        name="gemini-1.5-pro",
        context_length=2097152,
        max_output_tokens=8192,
        input_cost_per_1m=1.25,
        output_cost_per_1m=5.0,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
    # Dashscope (Qwen) models
    "qwen-max": ModelMetadata(
        name="qwen-max",
        context_length=32000,
        max_output_tokens=8192,
        input_cost_per_1m=2.4,
        output_cost_per_1m=9.6,
        capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING],
        supports_json_mode=True,
    ),
    "qwen-plus": ModelMetadata(
        name="qwen-plus",
        context_length=131072,
        max_output_tokens=8192,
        input_cost_per_1m=0.8,
        output_cost_per_1m=2.0,
        capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING],
        supports_json_mode=True,
    ),
    "qwen-turbo": ModelMetadata(
        name="qwen-turbo",
        context_length=131072,
        max_output_tokens=8192,
        input_cost_per_1m=0.3,
        output_cost_per_1m=0.6,
        capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING],
        supports_json_mode=True,
    ),
    # Deepseek models
    "deepseek-chat": ModelMetadata(
        name="deepseek-chat",
        context_length=64000,
        max_output_tokens=8192,
        input_cost_per_1m=0.14,
        output_cost_per_1m=0.28,
        capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING, ModelCapability.CODE],
        supports_json_mode=True,
    ),
    "deepseek-reasoner": ModelMetadata(
        name="deepseek-reasoner",
        context_length=64000,
        max_output_tokens=8192,
        input_cost_per_1m=0.55,
        output_cost_per_1m=2.19,
        capabilities=[ModelCapability.CHAT, ModelCapability.CODE],
        supports_json_mode=False,
    ),
    # Anthropic models
    "claude-3-5-sonnet-20241022": ModelMetadata(
        name="claude-3-5-sonnet-20241022",
        context_length=200000,
        max_output_tokens=8192,
        input_cost_per_1m=3.0,
        output_cost_per_1m=15.0,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
    "claude-3-5-haiku-20241022": ModelMetadata(
        name="claude-3-5-haiku-20241022",
        context_length=200000,
        max_output_tokens=8192,
        input_cost_per_1m=0.8,
        output_cost_per_1m=4.0,
        capabilities=[
            ModelCapability.CHAT,
            ModelCapability.FUNCTION_CALLING,
            ModelCapability.VISION,
        ],
        supports_json_mode=True,
    ),
}


def get_default_model_metadata(model_name: str) -> ModelMetadata:
    """
    Get default model metadata by model name.

    Args:
        model_name: Model identifier

    Returns:
        ModelMetadata with defaults if not found in registry
    """
    # Try exact match first
    if model_name in DEFAULT_MODEL_METADATA:
        return DEFAULT_MODEL_METADATA[model_name]

    # Try prefix match (e.g., "gpt-4-turbo-2024-01-01" matches "gpt-4-turbo")
    for known_model, metadata in DEFAULT_MODEL_METADATA.items():
        if model_name.startswith(known_model):
            return metadata

    # Return conservative defaults
    return ModelMetadata(
        name=model_name,
        context_length=128000,  # Conservative default
        max_output_tokens=4096,  # Conservative default
        capabilities=[ModelCapability.CHAT],
    )


class ProviderType(str, Enum):
    """Supported LLM provider types"""

    OPENAI = "openai"
    DASHSCOPE = "dashscope"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    AZURE_OPENAI = "azure_openai"
    COHERE = "cohere"
    MISTRAL = "mistral"
    BEDROCK = "bedrock"
    VERTEX = "vertex"
    DEEPSEEK = "deepseek"
    MINIMAX = "minimax"
    ZAI = "zai"  # Z.AI (ZhipuAI)
    KIMI = "kimi"  # Moonshot AI (Kimi)
    OLLAMA = "ollama"  # Local Ollama server
    LMSTUDIO = "lmstudio"  # LM Studio OpenAI-compatible server


class ProviderStatus(str, Enum):
    """Health status of a provider"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class OperationType(str, Enum):
    """Types of LLM operations"""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"


# ============================================================================
# Provider Configuration Models
# ============================================================================


class EmbeddingConfig(BaseModel):
    """Structured embedding configuration for provider runtime calls."""

    model: str | None = Field(None, min_length=1, description="Embedding model name")
    dimensions: int | None = Field(None, ge=1, description="Requested embedding dimensions")
    encoding_format: Literal["float", "base64"] | None = Field(
        None,
        description="Embedding encoding format",
    )
    user: str | None = Field(None, min_length=1, description="Provider user identifier")
    timeout: float | None = Field(None, gt=0, description="Embedding request timeout in seconds")
    provider_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional provider-specific embedding parameters",
    )


class ProviderConfigBase(BaseModel):
    """Base fields for provider configuration"""

    name: str = Field(..., min_length=1, description="Human-readable provider name")
    provider_type: ProviderType = Field(..., description="Provider type (openai, dashscope, etc.)")
    tenant_id: str | None = Field("default", description="Tenant/group ID")
    base_url: str | None = Field(None, description="Custom base URL for API calls")
    llm_model: str = Field(..., min_length=1, description="Primary LLM model")
    llm_small_model: str | None = Field(None, description="Smaller/faster LLM model")
    embedding_model: str | None = Field(None, description="Embedding model")
    embedding_config: EmbeddingConfig | None = Field(
        None,
        description="Structured embedding model configuration",
    )
    reranker_model: str | None = Field(None, description="Reranker model")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Additional provider-specific config"
    )
    is_active: bool = Field(True, description="Whether provider is enabled")
    is_default: bool = Field(False, description="Whether this is the default provider")

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        """Validate name is not just whitespace"""
        if not v or not v.strip():
            raise ValueError("Provider name cannot be empty")
        return v.strip()


class ProviderConfigCreate(ProviderConfigBase):
    """Model for creating a new provider (includes API key)"""

    api_key: str | None = Field(None, description="API key for the provider")

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, v: str | None) -> str | None:
        """Normalize API key by trimming whitespace."""
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def validate_api_key_requirement(self) -> "ProviderConfigCreate":
        """Require API key for remote providers while allowing local providers."""
        if self.provider_type in {ProviderType.OLLAMA, ProviderType.LMSTUDIO}:
            return self

        if not self.api_key:
            raise ValueError("API key cannot be empty")

        return self


class ProviderConfigUpdate(BaseModel):
    """Model for updating an existing provider"""

    name: str | None = Field(None, min_length=1)
    provider_type: ProviderType | None = None
    api_key: str | None = Field(None, min_length=1)
    base_url: str | None = None
    llm_model: str | None = None
    llm_small_model: str | None = None
    embedding_model: str | None = None
    embedding_config: EmbeddingConfig | None = None
    reranker_model: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, v: str | None) -> str | None:
        """Normalize API key by trimming whitespace."""
        return v.strip() if isinstance(v, str) else v


class ProviderConfig(ProviderConfigBase):
    """Complete provider configuration (as stored in database)"""

    id: UUID = Field(..., description="Provider unique identifier")
    api_key_encrypted: str = Field(..., description="Encrypted API key")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    class Config:
        from_attributes = True


class CircuitBreakerState(str, Enum):
    """Circuit breaker state."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RateLimitStats(BaseModel):
    """Rate limiter statistics."""

    current_concurrent: int = Field(0, description="Current concurrent requests")
    max_concurrent: int = Field(50, description="Maximum concurrent requests")
    total_requests: int = Field(0, description="Total requests made")
    requests_per_minute: int = Field(0, description="Requests in current minute window")
    max_rpm: int | None = Field(None, description="Maximum requests per minute")


class ResilienceStatus(BaseModel):
    """Provider resilience status combining circuit breaker and rate limiter."""

    circuit_breaker_state: CircuitBreakerState = Field(
        CircuitBreakerState.CLOSED, description="Circuit breaker state"
    )
    failure_count: int = Field(0, description="Current failure count")
    success_count: int = Field(0, description="Success count in half-open state")
    rate_limit: RateLimitStats = Field(
        default_factory=RateLimitStats, description="Rate limit statistics"
    )
    can_execute: bool = Field(True, description="Whether requests can be executed")


class ProviderConfigResponse(ProviderConfigBase):
    """Provider configuration for API responses (API key masked)"""

    id: UUID
    api_key_masked: str = Field(..., description="Masked API key (e.g., 'sk-...xyz')")
    created_at: datetime
    updated_at: datetime
    health_status: ProviderStatus | None = None
    health_last_check: datetime | None = None
    response_time_ms: int | None = None
    error_message: str | None = None
    # New resilience fields
    resilience: ResilienceStatus | None = Field(
        None, description="Provider resilience status (circuit breaker + rate limiter)"
    )


# ============================================================================
# Tenant Mapping Models
# ============================================================================


class TenantProviderMappingCreate(BaseModel):
    """Model for creating tenant-provider mapping"""

    tenant_id: str = Field(..., min_length=1, description="Tenant/group ID")
    provider_id: UUID = Field(..., description="Provider to assign")
    operation_type: OperationType = Field(
        default=OperationType.LLM,
        description="Operation type (llm, embedding, rerank)",
    )
    priority: int = Field(0, ge=0, description="Priority (lower = higher priority)")


class TenantProviderMapping(BaseModel):
    """Tenant to provider mapping"""

    id: UUID
    tenant_id: str
    provider_id: UUID
    operation_type: OperationType
    priority: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Health Status Models
# ============================================================================


class ProviderHealthCreate(BaseModel):
    """Model for creating health check entry"""

    provider_id: UUID
    status: ProviderStatus
    error_message: str | None = None
    response_time_ms: int | None = Field(None, ge=0)


class ProviderHealth(BaseModel):
    """Provider health status"""

    provider_id: UUID
    status: ProviderStatus
    last_check: datetime
    error_message: str | None = None
    response_time_ms: int | None = None

    class Config:
        from_attributes = True


# ============================================================================
# Usage Tracking Models
# ============================================================================


class LLMUsageLogCreate(BaseModel):
    """Model for creating usage log entry"""

    provider_id: UUID
    tenant_id: str | None = None
    operation_type: OperationType
    model_name: str
    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    cost_usd: float | None = Field(None, ge=0)


class LLMUsageLog(BaseModel):
    """LLM usage log entry"""

    id: UUID
    provider_id: UUID
    tenant_id: str | None
    operation_type: OperationType
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None
    created_at: datetime

    class Config:
        from_attributes = True


class UsageStatistics(BaseModel):
    """Aggregated usage statistics"""

    provider_id: UUID
    tenant_id: str | None
    operation_type: OperationType | None
    total_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float | None
    avg_response_time_ms: float | None
    first_request_at: datetime | None
    last_request_at: datetime | None


# ============================================================================
# Provider Resolution Models
# ============================================================================


class ResolvedProvider(BaseModel):
    """Result of provider resolution for a tenant"""

    provider: ProviderConfig
    resolution_source: str = Field(
        ..., description="How provider was resolved: 'tenant', 'default', or 'fallback'"
    )


class NoActiveProviderError(Exception):
    """Raised when no active provider can be found"""

    def __init__(self, message: str = "No active LLM provider configured") -> None:
        self.message = message
        super().__init__(self.message)
