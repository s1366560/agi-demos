"""
LLM Provider Configuration Domain Models

This module contains Pydantic models for LLM provider configuration,
following Domain-Driven Design principles.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================================
# Model Metadata Models (for context window management)
# ============================================================================


class ModelCapability(StrEnum):
    """Model capabilities"""

    CHAT = "chat"
    COMPLETION = "completion"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    CODE = "code"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDITING = "image_editing"
    VIDEO_GENERATION = "video_generation"
    # Volcengine Ark platform capabilities
    TTS = "tts"
    ASR = "asr"
    THREE_D_GENERATION = "3d_generation"
    DOCUMENT_UNDERSTANDING = "document_understanding"
    VIDEO_UNDERSTANDING = "video_understanding"
    MULTIMODAL_EMBEDDING = "multimodal_embedding"
    AUDIO_GENERATION = "audio_generation"
    VOICE_CLONING = "voice_cloning"
    REALTIME_VOICE = "realtime_voice"


class ModelMetadata(BaseModel):
    """
    Model capability metadata for context window management.

    This defines the capabilities and limits of a specific LLM model,
    enabling dynamic context window sizing and token budget allocation.
    """

    name: str = Field(..., description="Model identifier (e.g., 'gpt-4-turbo')")
    context_length: int = Field(
        default=128000,
        ge=1024,
        description="Maximum context window size in tokens",
    )
    max_output_tokens: int = Field(
        default=4096,
        ge=1,
        description="Maximum output tokens per request",
    )
    input_cost_per_1m: float | None = Field(
        default=None, ge=0, description="Cost per 1M input tokens (USD)"
    )
    output_cost_per_1m: float | None = Field(
        default=None, ge=0, description="Cost per 1M output tokens (USD)"
    )
    capabilities: list[ModelCapability] = Field(
        default_factory=list, description="Model capabilities"
    )
    supports_streaming: bool = Field(default=True, description="Whether model supports streaming")
    supports_json_mode: bool = Field(
        default=False,
        description="Whether model supports JSON output mode",
    )

    # --- New catalog fields (P1-T1) ---
    provider: str | None = Field(
        default=None,
        description="Provider name (e.g., 'openai', 'dashscope')",
    )
    modalities: list[str] = Field(
        default_factory=list,
        description="Supported modalities (e.g., ['text', 'image'])",
    )
    variants: list[str] = Field(
        default_factory=list,
        description="Available variant names (e.g., ['latest', '0125'])",
    )
    default_variant: str | None = Field(
        default=None,
        description="Default variant identifier",
    )
    family: str | None = Field(
        default=None,
        description="Model family (e.g., 'gpt-4', 'qwen')",
    )
    release_date: date | None = Field(default=None, description="Model release date")
    is_deprecated: bool = Field(default=False, description="Whether model is deprecated")
    description: str | None = Field(default=None, description="Human-readable model description")

    # --- Registry-compat fields (P1-T4) ---
    max_input_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Provider-enforced max input token cap",
    )
    input_budget_ratio: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Safety ratio for practical input budgeting",
    )
    chars_per_token: float = Field(
        default=3.0,
        gt=0.0,
        description="Fallback chars/token estimate",
    )

    # --- models.dev catalog fields (P1-T4 extended) ---
    reasoning: bool = Field(
        default=False,
        description="Whether model supports reasoning/thinking natively",
    )
    supports_temperature: bool = Field(
        default=True,
        description="Whether model accepts temperature parameter",
    )
    supports_tool_call: bool = Field(
        default=False,
        description="Whether model supports tool/function calling",
    )
    supports_structured_output: bool = Field(
        default=False,
        description="Whether model supports structured output mode",
    )
    supports_attachment: bool = Field(
        default=False,
        description="Whether model supports file/image attachments",
    )
    interleaved: dict[str, str] | None = Field(
        default=None,
        description="Reasoning interleaved content config (e.g. {'field': 'reasoning_content'})",
    )
    cache_read_cost_per_1m: float | None = Field(
        default=None, ge=0, description="Cost per 1M cache read tokens (USD)"
    )
    cache_write_cost_per_1m: float | None = Field(
        default=None, ge=0, description="Cost per 1M cache write tokens (USD)"
    )
    reasoning_cost_per_1m: float | None = Field(
        default=None, ge=0, description="Cost per 1M reasoning/thinking tokens (USD)"
    )
    knowledge_cutoff: str | None = Field(
        default=None, description="Knowledge cutoff date (e.g. '2024-06')"
    )
    open_weights: bool = Field(
        default=False,
        description="Whether model weights are publicly available",
    )

    # --- Extended parameter support fields (B1.1) ---
    default_temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Provider-recommended default temperature for this model",
    )
    default_top_p: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Provider-recommended default top_p for this model",
    )
    default_frequency_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description="Provider-recommended default frequency_penalty",
    )
    default_presence_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description="Provider-recommended default presence_penalty",
    )
    default_seed: int | None = Field(
        default=None,
        description="Provider-recommended default seed value",
    )
    default_stop: list[str] | None = Field(
        default=None,
        description="Provider-recommended default stop sequences",
    )
    supports_response_format: bool = Field(
        default=False,
        description="Whether model supports response_format parameter",
    )
    supports_seed: bool = Field(
        default=False,
        description="Whether model supports deterministic seed parameter",
    )
    supports_stop: bool = Field(
        default=True,
        description="Whether model supports custom stop sequences",
    )
    supports_frequency_penalty: bool = Field(
        default=True,
        description="Whether model supports frequency_penalty parameter",
    )
    supports_presence_penalty: bool = Field(
        default=True,
        description="Whether model supports presence_penalty parameter",
    )
    supports_top_p: bool = Field(
        default=True,
        description="Whether model supports top_p parameter",
    )
    temperature_range: list[float] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Allowed [min, max] temperature range for this model",
    )
    top_p_range: list[float] | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Allowed [min, max] top_p range for this model",
    )
    supported_params: list[str] | None = Field(
        default=None,
        description="Exhaustive list of supported OpenAI params for this model",
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


# Conservative fallback metadata for unknown models.
# The authoritative model catalog is loaded from models_snapshot.json
# (generated via models_dev_fetcher.py).  This fallback is used ONLY
# when a model is not found in the snapshot.
FALLBACK_MODEL_METADATA = ModelMetadata(
    name="unknown",
    context_length=128000,
    max_output_tokens=4096,
    input_cost_per_1m=None,
    output_cost_per_1m=None,
    capabilities=[ModelCapability.CHAT],
    supports_streaming=True,
    supports_json_mode=False,
    provider=None,
    modalities=["text"],
    description="Unknown model with conservative defaults",
)

# Backward-compatible alias.  Callers that previously iterated over
# DEFAULT_MODEL_METADATA will now get an empty dict.  They should migrate
# to ModelCatalogService for full model lookups.
DEFAULT_MODEL_METADATA: dict[str, ModelMetadata] = {}


def get_default_model_metadata(model_name: str) -> ModelMetadata:
    """Return conservative fallback metadata for *model_name*.

    .. deprecated::
        Callers should migrate to ``ModelCatalogService.get_model()``
        which uses the full models.dev snapshot.  This function now
        simply returns a copy of ``FALLBACK_MODEL_METADATA`` with the
        ``name`` field set to *model_name*.
    """
    return ModelMetadata(
        name=model_name,
        context_length=FALLBACK_MODEL_METADATA.context_length,
        max_output_tokens=FALLBACK_MODEL_METADATA.max_output_tokens,
        input_cost_per_1m=FALLBACK_MODEL_METADATA.input_cost_per_1m,
        output_cost_per_1m=FALLBACK_MODEL_METADATA.output_cost_per_1m,
        capabilities=list(FALLBACK_MODEL_METADATA.capabilities),
        supports_streaming=FALLBACK_MODEL_METADATA.supports_streaming,
        supports_json_mode=FALLBACK_MODEL_METADATA.supports_json_mode,
        provider=FALLBACK_MODEL_METADATA.provider,
        modalities=list(FALLBACK_MODEL_METADATA.modalities),
        description=f"Unknown model '{model_name}' with conservative defaults",
    )


class ProviderType(StrEnum):
    """Supported LLM provider types"""

    OPENAI = "openai"
    OPENROUTER = "openrouter"
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
    VOLCENGINE = "volcengine"  # Volcengine (Doubao/豆包)
    VOLCENGINE_CODING = "volcengine_coding"
    VOLCENGINE_EMBEDDING = "volcengine_embedding"
    VOLCENGINE_RERANKER = "volcengine_reranker"
    # Specialized sub-providers (coding, embedding, reranker variants)
    MINIMAX_CODING = "minimax_coding"
    MINIMAX_EMBEDDING = "minimax_embedding"
    MINIMAX_RERANKER = "minimax_reranker"
    ZAI_CODING = "zai_coding"
    ZAI_EMBEDDING = "zai_embedding"
    ZAI_RERANKER = "zai_reranker"
    KIMI_CODING = "kimi_coding"
    KIMI_EMBEDDING = "kimi_embedding"
    KIMI_RERANKER = "kimi_reranker"
    DASHSCOPE_CODING = "dashscope_coding"
    DASHSCOPE_EMBEDDING = "dashscope_embedding"
    DASHSCOPE_RERANKER = "dashscope_reranker"


class ProviderStatus(StrEnum):
    """Health status of a provider"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class OperationType(StrEnum):
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
    llm_model: str | None = Field(
        None, description="Primary LLM model (required for chat/coding providers)"
    )
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
    is_enabled: bool = Field(
        True,
        description="Whether this provider config is enabled for model routing",
    )
    allowed_models: list[str] = Field(
        default_factory=list,
        description="Whitelist of allowed model prefixes (empty = all allowed)",
    )
    blocked_models: list[str] = Field(
        default_factory=list,
        description="Blacklist of blocked model prefixes (takes precedence)",
    )

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

        # Require llm_model for chat/coding providers, not for embedding/reranker
        pt = self.provider_type.value if self.provider_type else ""
        is_embedding = pt.endswith("_embedding")
        is_reranker = pt.endswith("_reranker")
        if not is_embedding and not is_reranker and not self.llm_model:
            raise ValueError("llm_model is required for chat and coding providers")

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
    is_enabled: bool | None = None
    allowed_models: list[str] | None = None
    blocked_models: list[str] | None = None

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

    def is_model_allowed(self, model_id: str) -> bool:
        """Check if a model is allowed by whitelist/blacklist rules.

        Rules:
        - If blocked_models is non-empty and model_id matches any prefix
          (case-insensitive), the model is blocked.
        - Blacklist takes precedence over whitelist.
        - If allowed_models is non-empty, model_id must match at least
          one prefix (case-insensitive) to be allowed.
        - If both lists are empty, all models are allowed.

        Args:
            model_id: The model identifier to check.

        Returns:
            True if the model is allowed, False otherwise.
        """
        model_lower = model_id.lower()

        # Blacklist takes precedence
        if self.blocked_models:
            for pattern in self.blocked_models:
                if model_lower.startswith(pattern.lower()):
                    return False

        # Whitelist check (empty = all allowed)
        if self.allowed_models:
            return any(model_lower.startswith(p.lower()) for p in self.allowed_models)

        return True

    class Config:
        from_attributes = True


class CircuitBreakerState(StrEnum):
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
        default_factory=lambda: RateLimitStats(
            current_concurrent=0,
            max_concurrent=50,
            total_requests=0,
            requests_per_minute=0,
            max_rpm=None,
        ),
        description="Rate limit statistics",
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
