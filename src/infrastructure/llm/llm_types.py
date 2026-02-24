"""
Type Definitions for LLM Operations.

Provides TypedDict definitions for consistent type annotations across
LLM client implementations. Replaces dict[str, Any] with strongly-typed
dictionary types.

Usage:
    from src.infrastructure.llm.llm_types import (
        CompletionKwargs,
        MessageDict,
        ToolDefinition,
        UsageData,
    )

    def generate(self, messages: list[MessageDict], **kwargs: CompletionKwargs) -> ...
"""

from typing import Any, Literal, TypedDict


class MessageDict(TypedDict, total=False):
    """
    Dictionary representation of a chat message.

    Compatible with OpenAI/LiteLLM message format.
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None
    name: str | None
    tool_calls: list["ToolCallDict"] | None
    tool_call_id: str | None


class ToolCallDict(TypedDict, total=False):
    """
    Dictionary representation of a tool call.
    """

    id: str
    type: Literal["function"]
    index: int | None
    function: "FunctionCallDict"


class FunctionCallDict(TypedDict, total=False):
    """
    Dictionary representation of a function call.
    """

    name: str
    arguments: str


class ToolDefinition(TypedDict, total=False):
    """
    Dictionary representation of a tool definition.
    """

    type: Literal["function"]
    function: "FunctionDefinitionDict"


class FunctionDefinitionDict(TypedDict, total=False):
    """
    Dictionary representation of a function definition.
    """

    name: str
    description: str | None
    parameters: dict[str, Any]
    strict: bool | None


class UsageData(TypedDict, total=False):
    """
    Token usage data from LLM response.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    prompt_tokens: int | None  # Alternative name for input_tokens
    completion_tokens: int | None  # Alternative name for output_tokens


class CompletionKwargs(TypedDict, total=False):
    """
    Kwargs for LiteLLM completion calls.

    Provides type safety for completion parameters.
    """

    # Required
    model: str
    messages: list[MessageDict]

    # Optional generation parameters
    temperature: float | None
    max_tokens: int | None
    top_p: float | None
    frequency_penalty: float | None
    presence_penalty: float | None
    stop: str | list[str] | None

    # Streaming
    stream: bool | None
    stream_options: dict[str, Any] | None

    # Tool calling
    tools: list[ToolDefinition] | None
    tool_choice: str | dict[str, Any] | None

    # Response format
    response_format: dict[str, Any] | None

    # Authentication
    api_key: str | None
    api_base: str | None
    api_version: str | None

    # Request configuration
    timeout: int | None
    num_retries: int | None
    metadata: dict[str, Any] | None

    # Provider-specific
    extra_headers: dict[str, Any] | None
    extra_query: dict[str, Any] | None
    extra_body: dict[str, Any] | None

    # Caching
    cache: bool | None


class EmbeddingKwargs(TypedDict, total=False):
    """
    Kwargs for LiteLLM embedding calls.
    """

    # Required
    model: str
    input: str | list[str]

    # Optional parameters
    dimensions: int | None
    encoding_format: Literal["float", "base64"] | None
    user: str | None

    # Authentication
    api_key: str | None
    api_base: str | None

    # Request configuration
    timeout: int | None


class RerankKwargs(TypedDict, total=False):
    """
    Kwargs for LiteLLM rerank calls.
    """

    # Required
    model: str
    query: str
    documents: list[str]

    # Optional parameters
    top_n: int | None
    return_documents: bool | None
    max_chunks_per_doc: int | None

    # Authentication
    api_key: str | None
    api_base: str | None

    # Request configuration
    timeout: int | None


class StreamEventDict(TypedDict, total=False):
    """
    Dictionary representation of a streaming event.
    """

    type: Literal[
        "content",
        "tool_calls",
        "reasoning",
        "usage",
        "finish",
        "error",
    ]
    data: dict[str, Any]
    timestamp: float


class ChoiceDict(TypedDict, total=False):
    """
    Dictionary representation of a completion choice.
    """

    index: int
    message: MessageDict
    finish_reason: str | None
    delta: MessageDict | None


class CompletionResponseDict(TypedDict, total=False):
    """
    Dictionary representation of a completion response.
    """

    id: str
    model: str
    created: int
    object: Literal["chat.completion", "chat.completion.chunk"]
    choices: list[ChoiceDict]
    usage: UsageData | None
    system_fingerprint: str | None


class EmbeddingResponseDataDict(TypedDict, total=False):
    """
    Dictionary representation of embedding response data.
    """

    index: int
    embedding: list[float]
    object: Literal["embedding"]


class EmbeddingResponseDict(TypedDict, total=False):
    """
    Dictionary representation of embedding response.
    """

    id: str | None
    model: str
    object: Literal["list"]
    data: list[EmbeddingResponseDataDict]
    usage: UsageData | None


class RerankResultDict(TypedDict, total=False):
    """
    Dictionary representation of rerank result.
    """

    index: int
    relevance_score: float
    document: dict[str, Any] | None


class RerankResponseDict(TypedDict, total=False):
    """
    Dictionary representation of rerank response.
    """

    id: str | None
    model: str
    results: list[RerankResultDict]
    usage: UsageData | None


# Langfuse context types


class LangfuseContextDict(TypedDict, total=False):
    """
    Context dictionary for Langfuse tracing.
    """

    trace_name: str
    trace_id: str
    session_id: str | None
    user_id: str | None
    tags: list[str] | None
    metadata: dict[str, Any] | None
    extra: dict[str, Any] | None

    # Multi-tenant context
    tenant_id: str | None
    project_id: str | None
    conversation_id: str | None


# Provider configuration types


class ProviderConfigDict(TypedDict, total=False):
    """
    Dictionary representation of provider configuration.
    """

    id: str | None
    provider_type: str
    api_key_encrypted: str
    base_url: str | None

    # Model configuration
    llm_model: str
    llm_small_model: str | None
    embedding_model: str | None
    reranker_model: str | None

    # Health check configuration
    health_check_enabled: bool
    health_check_model: str | None

    # Rate limiting
    max_concurrent_requests: int

    # Metadata
    created_at: str | None
    updated_at: str | None
    is_active: bool


# Cache types


class CacheKeyDict(TypedDict, total=False):
    """
    Dictionary representation of cache key components.
    """

    messages_hash: str
    model: str
    temperature: float
    tools_hash: str | None
    response_format_hash: str | None


class CachedResponseDict(TypedDict, total=False):
    """
    Dictionary representation of cached response.
    """

    content: str
    tool_calls: list[ToolCallDict] | None
    finish_reason: str | None
    usage: UsageData | None
    created_at: float
    expires_at: float | None
