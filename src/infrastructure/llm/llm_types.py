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

from typing import Any, Literal, Optional, TypedDict, Union


class MessageDict(TypedDict, total=False):
    """
    Dictionary representation of a chat message.
    
    Compatible with OpenAI/LiteLLM message format.
    """
    
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, list[dict[str, Any]], None]
    name: Optional[str]
    tool_calls: Optional[list["ToolCallDict"]]
    tool_call_id: Optional[str]


class ToolCallDict(TypedDict, total=False):
    """
    Dictionary representation of a tool call.
    """
    
    id: str
    type: Literal["function"]
    index: Optional[int]
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
    description: Optional[str]
    parameters: dict[str, Any]
    strict: Optional[bool]


class UsageData(TypedDict, total=False):
    """
    Token usage data from LLM response.
    """
    
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: Optional[int]
    cache_read_tokens: Optional[int]
    cache_write_tokens: Optional[int]
    prompt_tokens: Optional[int]  # Alternative name for input_tokens
    completion_tokens: Optional[int]  # Alternative name for output_tokens


class CompletionKwargs(TypedDict, total=False):
    """
    Kwargs for LiteLLM completion calls.
    
    Provides type safety for completion parameters.
    """
    
    # Required
    model: str
    messages: list[MessageDict]
    
    # Optional generation parameters
    temperature: Optional[float]
    max_tokens: Optional[int]
    top_p: Optional[float]
    frequency_penalty: Optional[float]
    presence_penalty: Optional[float]
    stop: Optional[Union[str, list[str]]]
    
    # Streaming
    stream: Optional[bool]
    stream_options: Optional[dict[str, Any]]
    
    # Tool calling
    tools: Optional[list[ToolDefinition]]
    tool_choice: Optional[Union[str, dict[str, Any]]]
    
    # Response format
    response_format: Optional[dict[str, Any]]
    
    # Authentication
    api_key: Optional[str]
    api_base: Optional[str]
    api_version: Optional[str]
    
    # Request configuration
    timeout: Optional[int]
    num_retries: Optional[int]
    metadata: Optional[dict[str, Any]]
    
    # Provider-specific
    extra_headers: Optional[dict[str, Any]]
    extra_query: Optional[dict[str, Any]]
    extra_body: Optional[dict[str, Any]]
    
    # Caching
    cache: Optional[bool]


class EmbeddingKwargs(TypedDict, total=False):
    """
    Kwargs for LiteLLM embedding calls.
    """
    
    # Required
    model: str
    input: Union[str, list[str]]
    
    # Optional parameters
    dimensions: Optional[int]
    encoding_format: Optional[Literal["float", "base64"]]
    user: Optional[str]
    
    # Authentication
    api_key: Optional[str]
    api_base: Optional[str]
    
    # Request configuration
    timeout: Optional[int]


class RerankKwargs(TypedDict, total=False):
    """
    Kwargs for LiteLLM rerank calls.
    """
    
    # Required
    model: str
    query: str
    documents: list[str]
    
    # Optional parameters
    top_n: Optional[int]
    return_documents: Optional[bool]
    max_chunks_per_doc: Optional[int]
    
    # Authentication
    api_key: Optional[str]
    api_base: Optional[str]
    
    # Request configuration
    timeout: Optional[int]


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
    finish_reason: Optional[str]
    delta: Optional[MessageDict]


class CompletionResponseDict(TypedDict, total=False):
    """
    Dictionary representation of a completion response.
    """
    
    id: str
    model: str
    created: int
    object: Literal["chat.completion", "chat.completion.chunk"]
    choices: list[ChoiceDict]
    usage: Optional[UsageData]
    system_fingerprint: Optional[str]


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
    
    id: Optional[str]
    model: str
    object: Literal["list"]
    data: list[EmbeddingResponseDataDict]
    usage: Optional[UsageData]


class RerankResultDict(TypedDict, total=False):
    """
    Dictionary representation of rerank result.
    """
    
    index: int
    relevance_score: float
    document: Optional[dict[str, Any]]


class RerankResponseDict(TypedDict, total=False):
    """
    Dictionary representation of rerank response.
    """
    
    id: Optional[str]
    model: str
    results: list[RerankResultDict]
    usage: Optional[UsageData]


# Langfuse context types


class LangfuseContextDict(TypedDict, total=False):
    """
    Context dictionary for Langfuse tracing.
    """
    
    trace_name: str
    trace_id: str
    session_id: Optional[str]
    user_id: Optional[str]
    tags: Optional[list[str]]
    metadata: Optional[dict[str, Any]]
    extra: Optional[dict[str, Any]]
    
    # Multi-tenant context
    tenant_id: Optional[str]
    project_id: Optional[str]
    conversation_id: Optional[str]


# Provider configuration types


class ProviderConfigDict(TypedDict, total=False):
    """
    Dictionary representation of provider configuration.
    """
    
    id: Optional[str]
    provider_type: str
    api_key_encrypted: str
    base_url: Optional[str]
    
    # Model configuration
    llm_model: str
    llm_small_model: Optional[str]
    embedding_model: Optional[str]
    reranker_model: Optional[str]
    
    # Health check configuration
    health_check_enabled: bool
    health_check_model: Optional[str]
    
    # Rate limiting
    max_concurrent_requests: int
    
    # Metadata
    created_at: Optional[str]
    updated_at: Optional[str]
    is_active: bool


# Cache types


class CacheKeyDict(TypedDict, total=False):
    """
    Dictionary representation of cache key components.
    """
    
    messages_hash: str
    model: str
    temperature: float
    tools_hash: Optional[str]
    response_format_hash: Optional[str]


class CachedResponseDict(TypedDict, total=False):
    """
    Dictionary representation of cached response.
    """
    
    content: str
    tool_calls: Optional[list[ToolCallDict]]
    finish_reason: Optional[str]
    usage: Optional[UsageData]
    created_at: float
    expires_at: Optional[float]
