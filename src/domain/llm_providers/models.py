"""
LLM Provider Configuration Domain Models

This module contains Pydantic models for LLM provider configuration,
following Domain-Driven Design principles.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.llm_providers.security_policy import (
    provider_persistent_auth_supported,
    validate_provider_base_url,
)

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


class ProviderAuthMethod(StrEnum):
    """Authentication methods supported by an LLM provider type."""

    API_KEY = "api_key"
    ENVIRONMENT = "environment"
    OAUTH = "oauth"
    NONE = "none"


class UnsupportedProviderAuthError(ValueError):
    """Persistent or probe authentication cannot be executed by this backend."""


class ProviderCredentialRequiredError(ValueError):
    """A credential must be resubmitted because its provider binding changed."""


class ProviderRevisionConflictError(ValueError):
    """The submitted provider snapshot is no longer authoritative."""


def provider_revision(updated_at: datetime) -> int:
    """Convert a provider timestamp to the cross-runtime microsecond revision contract."""
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    delta = updated_at.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


_PROVIDER_ENVIRONMENT_VARIABLES: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "dashscope": ("DASHSCOPE_API_KEY",),
    "gemini": ("GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "zai": ("ZAI_API_KEY", "ZHIPU_API_KEY"),
    "kimi": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "volcengine": ("VOLCENGINE_API_KEY", "ARK_API_KEY"),
}
_PROVIDER_VARIANT_SUFFIXES: tuple[str, ...] = ("_coding", "_embedding", "_reranker")


def provider_environment_variables(provider_type: ProviderType) -> tuple[str, ...]:
    """Return the server-side credential variable names allowed for a provider type."""
    provider_family = provider_type.value
    for suffix in _PROVIDER_VARIANT_SUFFIXES:
        if provider_family.endswith(suffix):
            provider_family = provider_family[: -len(suffix)]
            break
    return _PROVIDER_ENVIRONMENT_VARIABLES.get(provider_family, ())


class ProviderTypeDescriptor(BaseModel):
    """Public capabilities for configuring an LLM provider type."""

    provider_type: ProviderType
    operation_type: Literal["llm", "embedding", "rerank"] = "llm"
    probe_supported: bool = True
    auth_methods: list[ProviderAuthMethod]
    unavailable_auth_methods: list[str] = Field(default_factory=list)


class ProviderStatus(StrEnum):
    """Health status of a provider"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CONFIGURATION_VALID = "configuration_valid"


class OperationType(StrEnum):
    """Types of LLM operations"""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANK = "rerank"


def infer_operation_type_from_provider_type(provider_type: ProviderType) -> OperationType:
    """Infer operation role from provider type variants."""
    value = provider_type.value
    if value.endswith("_embedding"):
        return OperationType.EMBEDDING
    if value.endswith("_reranker"):
        return OperationType.RERANK
    return OperationType.LLM


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


class _SafeEmbeddingProviderOptions(BaseModel):
    """Explicit non-credential embedding options accepted from public requests."""

    model_config = ConfigDict(extra="forbid")

    batch_size: int | None = Field(default=None, ge=1, le=2048)
    input_type: (
        Literal[
            "search_document",
            "search_query",
            "classification",
            "clustering",
        ]
        | None
    ) = None
    truncate: Literal["NONE", "START", "END"] | None = None


class _SafeRetryConfig(BaseModel):
    """Public retry tuning without executable or credential-bearing fields."""

    model_config = ConfigDict(extra="forbid")

    max_attempts: int | None = Field(default=None, ge=0, le=20)
    base_delay: float | None = Field(default=None, ge=0, le=300)
    max_delay: float | None = Field(default=None, ge=0, le=3600)
    backoff_factor: float | None = Field(default=None, ge=0, le=100)


class _SafeTransportConfig(BaseModel):
    """Public transport timeouts without headers, URLs, or authentication state."""

    model_config = ConfigDict(extra="forbid")

    connect_timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    request_timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    idle_timeout_seconds: float | None = Field(default=None, gt=0, le=86_400)


def _validate_request_embedding_config(value: EmbeddingConfig | None) -> EmbeddingConfig | None:
    """Validate and normalize the public subset of structured embedding options."""
    if value is None:
        return None
    safe_options = _SafeEmbeddingProviderOptions.model_validate(value.provider_options)
    value.provider_options = safe_options.model_dump(exclude_none=True)
    return value


class _SafeProviderRequestConfig(BaseModel):
    """Positive schema for JSON config accepted from create/update/probe requests."""

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = Field(default=None, ge=0, le=1)
    timeout: float | None = Field(default=None, gt=0, le=3600)
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    request_timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    connect_timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    seed: int | None = None
    max_retries: int | None = Field(default=None, ge=0, le=20)
    region: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,64}$")
    retries: _SafeRetryConfig | None = None
    transport: _SafeTransportConfig | None = None
    embedding: EmbeddingConfig | None = None

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: EmbeddingConfig | None) -> EmbeddingConfig | None:
        """Reject arbitrary embedding provider options in nested config."""
        return _validate_request_embedding_config(value)


_SAFE_PROVIDER_CONFIG_FIELDS = frozenset(_SafeProviderRequestConfig.model_fields)
_SAFE_RETRY_CONFIG_FIELDS = frozenset(_SafeRetryConfig.model_fields)
_SAFE_TRANSPORT_CONFIG_FIELDS = frozenset(_SafeTransportConfig.model_fields)
_SAFE_EMBEDDING_CONFIG_FIELDS = frozenset(EmbeddingConfig.model_fields)
_SAFE_EMBEDDING_PROVIDER_OPTION_FIELDS = frozenset(_SafeEmbeddingProviderOptions.model_fields)


def validate_provider_request_config(value: object) -> dict[str, Any]:
    """Validate public JSON config and return a JSON-compatible safe projection."""
    parsed = _SafeProviderRequestConfig.model_validate({} if value is None else value)
    return parsed.model_dump(mode="json", exclude_none=True, exclude_unset=True)


def merge_provider_request_config(
    existing: object,
    submitted: dict[str, Any],
) -> dict[str, Any]:
    """Replace public fields while preserving historical hidden/private fields."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    nested_fields = {"embedding", "retries", "transport"}
    for key in _SAFE_PROVIDER_CONFIG_FIELDS - nested_fields:
        merged.pop(key, None)
    merged.update({key: value for key, value in submitted.items() if key not in nested_fields})

    nested_schemas = {
        "retries": _SAFE_RETRY_CONFIG_FIELDS,
        "transport": _SAFE_TRANSPORT_CONFIG_FIELDS,
    }
    for key, safe_fields in nested_schemas.items():
        nested = _merge_safe_config_object(
            merged.get(key),
            submitted.get(key),
            safe_fields,
        )
        if nested:
            merged[key] = nested
        else:
            merged.pop(key, None)

    embedding = merge_provider_embedding_config(merged.get("embedding"), submitted.get("embedding"))
    if embedding:
        merged["embedding"] = embedding
    else:
        merged.pop("embedding", None)
    return merged


def _merge_safe_config_object(
    existing: object,
    submitted: object,
    safe_fields: frozenset[str],
) -> dict[str, Any]:
    """Replace safe keys in one object while retaining unknown historical keys."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    for key in safe_fields:
        merged.pop(key, None)
    if isinstance(submitted, dict):
        merged.update({key: value for key, value in submitted.items() if key in safe_fields})
    return merged


def merge_provider_embedding_config(existing: object, submitted: object) -> dict[str, Any]:
    """Merge embedding fields and provider options at their respective safe-key levels."""
    existing_config = dict(existing) if isinstance(existing, dict) else {}
    submitted_config = dict(submitted) if isinstance(submitted, dict) else {}
    merged = _merge_safe_config_object(
        existing_config,
        submitted_config,
        _SAFE_EMBEDDING_CONFIG_FIELDS - {"provider_options"},
    )

    existing_options = existing_config.get("provider_options")
    submitted_options = submitted_config.get("provider_options")
    if not isinstance(existing_options, dict) and "provider_options" not in submitted_config:
        if existing_options is not None:
            merged["provider_options"] = existing_options
        return merged

    provider_options = _merge_safe_config_object(
        existing_options,
        submitted_options,
        _SAFE_EMBEDDING_PROVIDER_OPTION_FIELDS,
    )
    if provider_options:
        merged["provider_options"] = provider_options
    else:
        merged.pop("provider_options", None)
    return merged


class ProviderConfigBase(BaseModel):
    """Base fields for provider configuration"""

    name: str = Field(..., min_length=1, description="Human-readable provider name")
    provider_type: ProviderType = Field(..., description="Provider type (openai, dashscope, etc.)")
    operation_type: OperationType = Field(
        OperationType.LLM,
        description="Provider operation role: llm, embedding, or rerank",
    )
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

    # Pool / load-balancer routing -----------------------------------------
    pool_weight: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Relative weight in the tenant model pool. Higher = more traffic "
            "when the load balancer ties on inflight/latency."
        ),
    )
    pool_enabled: bool = Field(
        default=True,
        description=(
            "Whether this provider participates in the tenant LLM pool used "
            "by load-balancing / auto-routing. is_active stays the master "
            "on/off switch."
        ),
    )
    model_tier: Literal["small", "medium", "large"] | None = Field(
        default=None,
        description=(
            "Optional capability tier hint. The auto-broker uses it to map a "
            "task verdict (complexity=small|medium|large) onto candidates."
        ),
    )
    secondary_models: list[str] = Field(
        default_factory=list,
        description=(
            "Optional extra model names that share this provider's API key "
            "and base_url, exposed to the pool alongside llm_model / "
            "llm_small_model."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        """Validate name is not just whitespace"""
        if not v or not v.strip():
            raise ValueError("Provider name cannot be empty")
        return v.strip()

    @model_validator(mode="after")
    def normalize_operation_type(self) -> "ProviderConfigBase":
        """Keep legacy provider variants aligned with explicit operation roles."""
        inferred = infer_operation_type_from_provider_type(self.provider_type)
        if inferred != OperationType.LLM:
            self.operation_type = inferred
        return self


def _normalize_persistent_provider_base_url(value: str | None) -> str | None:
    """Validate the structural parts shared by persisted and probe endpoints."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid provider base URL") from exc
    if parsed.scheme not in {"http", "https"} or hostname is None:
        raise ValueError("Invalid provider base URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid provider base URL")
    if parsed.query or "?" in normalized:
        raise ValueError("Invalid provider base URL")
    if parsed.fragment or "#" in normalized:
        raise ValueError("Invalid provider base URL")
    return normalized


def validate_provider_base_url_transport(
    value: str | None,
    provider_type: ProviderType,
) -> str | None:
    """Validate transport plus the explicit non-secret API base-path policy."""
    return validate_provider_base_url(value, provider_type)


class ProviderConfigCreate(ProviderConfigBase):
    """Model for creating a new provider (includes API key)"""

    model_config = ConfigDict(extra="forbid")

    auth_method: ProviderAuthMethod | None = Field(
        None,
        description="Persistent credential method",
    )
    environment_variable: str | None = Field(
        None,
        description="Reserved credential reference; unsupported for persistent providers",
    )
    api_key: str | None = Field(None, description="API key for the provider")

    @field_validator("api_key", "environment_variable")
    @classmethod
    def normalize_credential_field(cls, v: str | None) -> str | None:
        """Normalize credential input by trimming whitespace."""
        return v.strip() if isinstance(v, str) else v

    @field_validator("base_url")
    @classmethod
    def validate_persistent_base_url(cls, value: str | None) -> str | None:
        """Keep credentials and query tokens out of persistent provider endpoints."""
        return _normalize_persistent_provider_base_url(value)

    @field_validator("config")
    @classmethod
    def validate_public_config(cls, value: object) -> dict[str, Any]:
        """Allow only explicitly safe, non-credential JSON configuration."""
        return validate_provider_request_config(value)

    @field_validator("embedding_config")
    @classmethod
    def validate_structured_embedding(
        cls,
        value: EmbeddingConfig | None,
    ) -> EmbeddingConfig | None:
        """Reject unstructured embedding provider options before persistence."""
        return _validate_request_embedding_config(value)

    @model_validator(mode="after")
    def validate_api_key_requirement(self) -> "ProviderConfigCreate":
        """Accept only executable persistent authentication configurations."""
        self.base_url = validate_provider_base_url_transport(self.base_url, self.provider_type)
        if not provider_persistent_auth_supported(self.provider_type):
            raise UnsupportedProviderAuthError(
                "Persistent authentication is not available for this provider type"
            )
        is_local = self.provider_type in {ProviderType.OLLAMA, ProviderType.LMSTUDIO}
        auth_method = self.auth_method or (
            ProviderAuthMethod.NONE if is_local else ProviderAuthMethod.API_KEY
        )
        self.auth_method = auth_method

        if auth_method in {ProviderAuthMethod.ENVIRONMENT, ProviderAuthMethod.OAUTH}:
            raise UnsupportedProviderAuthError(
                "Authentication method is not supported for persistent providers"
            )
        if self.environment_variable:
            raise UnsupportedProviderAuthError(
                "Authentication method is not supported for persistent providers"
            )

        if is_local:
            if auth_method != ProviderAuthMethod.NONE or self.api_key:
                raise UnsupportedProviderAuthError(
                    "API-key authentication is not supported for local providers"
                )
            return self._validate_required_model()

        if auth_method != ProviderAuthMethod.API_KEY:
            raise UnsupportedProviderAuthError(
                "No-auth authentication is not supported for remote providers"
            )
        if not self.api_key:
            raise ValueError("API key cannot be empty")

        return self._validate_required_model()

    def _validate_required_model(self) -> "ProviderConfigCreate":
        """Require the model field that matches this provider's operation role."""
        if self.operation_type == OperationType.LLM and not self.llm_model:
            raise ValueError("llm_model is required for chat and coding providers")
        if self.operation_type == OperationType.EMBEDDING:
            embedding_model = self.embedding_model or (
                self.embedding_config.model if self.embedding_config else None
            )
            if not embedding_model:
                raise ValueError("embedding_model is required for embedding providers")
        if self.operation_type == OperationType.RERANK and not self.reranker_model:
            raise ValueError("reranker_model is required for rerank providers")

        return self


class ProviderProbeRequest(ProviderConfigBase):
    """Connection fields accepted when probing a provider without persisting it."""

    model_config = ConfigDict(extra="forbid")

    auth_method: ProviderAuthMethod | None = Field(
        None,
        description="Credential source used only for this probe",
    )
    environment_variable: str | None = Field(
        None,
        description="Allow-listed server environment variable name; never its value",
    )
    api_key: str | None = Field(None, description="Ephemeral API key used only for this probe")

    @field_validator("api_key", "environment_variable")
    @classmethod
    def normalize_credential_reference(cls, value: str | None) -> str | None:
        """Normalize an ephemeral API key or environment-variable reference."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("base_url")
    @classmethod
    def validate_probe_base_url(cls, value: str | None) -> str | None:
        """Reject unsafe endpoint structures before an ephemeral credential is resolved."""
        return _normalize_persistent_provider_base_url(value)

    @field_validator("config")
    @classmethod
    def validate_public_config(cls, value: object) -> dict[str, Any]:
        """Reject arbitrary executable or credential-bearing probe config."""
        return validate_provider_request_config(value)

    @field_validator("embedding_config")
    @classmethod
    def validate_structured_embedding(
        cls,
        value: EmbeddingConfig | None,
    ) -> EmbeddingConfig | None:
        """Reject unstructured embedding provider options in draft probes."""
        return _validate_request_embedding_config(value)

    @model_validator(mode="after")
    def validate_api_key_requirement(self) -> "ProviderProbeRequest":
        """Validate the mutually exclusive credential source without requiring a model."""
        self.base_url = validate_provider_base_url_transport(self.base_url, self.provider_type)
        is_local = self.provider_type in {ProviderType.OLLAMA, ProviderType.LMSTUDIO}
        auth_method = self.auth_method or (
            ProviderAuthMethod.NONE if is_local else ProviderAuthMethod.API_KEY
        )
        self.auth_method = auth_method

        if auth_method == ProviderAuthMethod.OAUTH:
            raise UnsupportedProviderAuthError("OAuth authentication is not supported")

        if auth_method == ProviderAuthMethod.NONE:
            if not is_local or self.api_key or self.environment_variable:
                raise ValueError("No-auth providers cannot accept credential fields")
            return self

        if is_local:
            raise ValueError("Authentication method is not supported for this provider type")

        if auth_method == ProviderAuthMethod.API_KEY:
            if self.environment_variable:
                raise ValueError("Environment variable requires environment authentication")
            if not self.api_key:
                raise ValueError("API key cannot be empty")
            return self

        if self.api_key:
            raise ValueError("API key cannot be combined with environment authentication")
        if not self.environment_variable:
            raise ValueError("Environment variable is required for environment authentication")
        if self.environment_variable not in provider_environment_variables(self.provider_type):
            raise ValueError("Environment variable is not supported for this provider type")
        return self


class ProviderConfigUpdate(BaseModel):
    """Model for updating an existing provider"""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1)
    provider_type: ProviderType | None = None
    operation_type: OperationType | None = None
    auth_method: ProviderAuthMethod | None = None
    environment_variable: str | None = None
    expected_revision: int | None = Field(default=None, ge=0)
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
    pool_weight: float | None = Field(default=None, ge=0.0)
    pool_enabled: bool | None = None
    model_tier: Literal["small", "medium", "large"] | None = None
    secondary_models: list[str] | None = None

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str | None) -> str | None:
        """Normalize a supplied replacement key and reject whitespace-only values."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("API key cannot be empty")
        return normalized

    @field_validator("environment_variable")
    @classmethod
    def normalize_environment_variable(cls, value: str | None) -> str | None:
        """Normalize the unsupported reference before model-level validation."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("base_url")
    @classmethod
    def validate_persistent_base_url(cls, value: str | None) -> str | None:
        """Keep credentials and query tokens out of persistent provider endpoints."""
        return _normalize_persistent_provider_base_url(value)

    @field_validator("config")
    @classmethod
    def validate_public_config(cls, value: object) -> dict[str, Any] | None:
        """Allow only explicitly safe JSON fields in persistent updates."""
        if value is None:
            return None
        return validate_provider_request_config(value)

    @field_validator("embedding_config")
    @classmethod
    def validate_structured_embedding(
        cls,
        value: EmbeddingConfig | None,
    ) -> EmbeddingConfig | None:
        """Reject unstructured embedding provider options before persistence."""
        return _validate_request_embedding_config(value)

    @model_validator(mode="after")
    def validate_persistent_auth_method(self) -> "ProviderConfigUpdate":
        """Reject credential sources the persistent repository cannot execute."""
        if self.provider_type is not None:
            self.base_url = validate_provider_base_url_transport(
                self.base_url,
                self.provider_type,
            )
            if not provider_persistent_auth_supported(self.provider_type):
                raise UnsupportedProviderAuthError(
                    "Persistent authentication is not available for this provider type"
                )
        if self.auth_method in {ProviderAuthMethod.ENVIRONMENT, ProviderAuthMethod.OAUTH}:
            raise UnsupportedProviderAuthError(
                "Authentication method is not supported for persistent providers"
            )
        if self.environment_variable:
            raise UnsupportedProviderAuthError(
                "Authentication method is not supported for persistent providers"
            )
        if self.auth_method == ProviderAuthMethod.NONE and self.api_key:
            raise UnsupportedProviderAuthError("No-auth provider updates cannot include an API key")
        return self


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


_PUBLIC_PROVIDER_NUMBER_FIELDS = (
    "temperature",
    "max_tokens",
    "top_p",
    "timeout",
    "timeout_seconds",
    "request_timeout_seconds",
    "connect_timeout_seconds",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "max_retries",
)
_PUBLIC_RETRY_NUMBER_FIELDS = ("max_attempts", "base_delay", "max_delay", "backoff_factor")
_PUBLIC_TRANSPORT_NUMBER_FIELDS = (
    "connect_timeout_seconds",
    "request_timeout_seconds",
    "idle_timeout_seconds",
)


def _public_number_fields(value: object, keys: tuple[str, ...]) -> dict[str, int | float]:
    """Project explicitly public numeric tuning fields from an arbitrary JSON object."""
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key in keys
        if isinstance((item := value.get(key)), (int, float)) and not isinstance(item, bool)
    }


def _public_embedding_response_config(value: object) -> dict[str, Any]:
    """Project the non-secret, schema-bound subset of an embedding configuration."""
    if isinstance(value, EmbeddingConfig):
        value = value.model_dump()
    if not isinstance(value, dict):
        return {}
    public: dict[str, Any] = _public_number_fields(value, ("dimensions", "timeout"))
    for key in ("model", "user"):
        item = value.get(key)
        if isinstance(item, str) and 0 < len(item) <= 512 and item.isprintable():
            public[key] = item
    encoding_format = value.get("encoding_format")
    if encoding_format in {"float", "base64"}:
        public["encoding_format"] = encoding_format
    raw_provider_options = value.get("provider_options", {})
    safe_provider_options = (
        {
            key: item
            for key, item in raw_provider_options.items()
            if key in _SAFE_EMBEDDING_PROVIDER_OPTION_FIELDS
        }
        if isinstance(raw_provider_options, dict)
        else {}
    )
    try:
        provider_options = _SafeEmbeddingProviderOptions.model_validate(
            safe_provider_options
        ).model_dump(exclude_none=True)
    except ValueError:
        provider_options = {}
    if provider_options:
        public["provider_options"] = provider_options
    return public


def _public_provider_response_config(value: object) -> dict[str, Any]:
    """Project only schema-bound fields that are safe for ordinary Provider responses."""
    if not isinstance(value, dict):
        return {}
    public: dict[str, Any] = _public_number_fields(value, _PUBLIC_PROVIDER_NUMBER_FIELDS)
    region = value.get("region")
    if (
        isinstance(region, str)
        and 0 < len(region) <= 64
        and region.isascii()
        and all(char.isalnum() or char == "-" for char in region)
    ):
        public["region"] = region
    retries = _public_number_fields(value.get("retries"), _PUBLIC_RETRY_NUMBER_FIELDS)
    if retries:
        public["retries"] = retries
    transport = _public_number_fields(value.get("transport"), _PUBLIC_TRANSPORT_NUMBER_FIELDS)
    if transport:
        public["transport"] = transport
    embedding = _public_embedding_response_config(value.get("embedding"))
    if embedding:
        public["embedding"] = embedding
    return public


class ProviderConfigResponse(ProviderConfigBase):
    """Provider configuration for API responses (API key masked)"""

    id: UUID
    auth_method: ProviderAuthMethod = ProviderAuthMethod.API_KEY
    environment_variable: str | None = None
    credential_source: Literal["service_encrypted", "environment", "none"] = "service_encrypted"
    credential_configured: bool = False
    api_key_masked: str = Field(..., description="Masked API key (e.g., 'sk-...xyz')")
    revision: int = Field(..., ge=0, description="Optimistic concurrency revision in microseconds")
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

    @field_validator("config", mode="before")
    @classmethod
    def redact_config_credentials(cls, value: object) -> object:
        """Keep arbitrary or sensitive provider config out of public response serialization."""
        return _public_provider_response_config(value)

    @field_validator("embedding_config", mode="before")
    @classmethod
    def redact_embedding_config_credentials(cls, value: object) -> object:
        """Expose only the schema-bound public subset of structured embedding config."""
        return _public_embedding_response_config(value)


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


class ProviderValidationResponse(BaseModel):
    """Result of an explicit provider connection probe."""

    provider: ProviderConfigResponse | None
    provider_id: UUID
    status: ProviderStatus
    probed: bool
    environment_variable: str | None = None
    detail: str | None
    last_check: datetime
    response_time_ms: int | None = Field(..., ge=0)
    error_message: str | None
    catalog: dict[str, Any] | None

    @classmethod
    def from_health(
        cls,
        health: ProviderHealth,
        *,
        probed: bool,
        detail: str | None,
        catalog: dict[str, Any] | None,
        environment_variable: str | None = None,
    ) -> "ProviderValidationResponse":
        """Adapt an internal health result to the explicit validation contract."""
        return cls(
            provider=None,
            provider_id=health.provider_id,
            status=health.status,
            probed=probed,
            environment_variable=environment_variable,
            detail=detail,
            last_check=health.last_check,
            response_time_ms=health.response_time_ms,
            error_message=health.error_message,
            catalog=catalog,
        )

    @classmethod
    def from_configuration_validation(
        cls,
        *,
        provider_id: UUID,
        detail: str,
        environment_variable: str | None = None,
    ) -> "ProviderValidationResponse":
        """Return a valid configuration result when no safe network probe exists."""
        return cls(
            provider=None,
            provider_id=provider_id,
            status=ProviderStatus.CONFIGURATION_VALID,
            probed=False,
            environment_variable=environment_variable,
            detail=detail,
            last_check=datetime.now(UTC),
            response_time_ms=None,
            error_message=None,
            catalog=None,
        )


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
