"""
LLM Provider Exceptions.

Unified exception hierarchy for LLM provider operations.
Provides clear categorization of errors for better error handling and observability.

Example:
    try:
        response = await llm_client.generate(messages)
    except RateLimitError:
        logger.warning("Rate limit exceeded")
    except ModelError as e:
        logger.error(f"Model error: {e}")
    except ProviderError as e:
        logger.error(f"Provider error: {e}")
"""

from typing import Any


class LLMError(Exception):
    """
    Base exception for all LLM-related errors.

    All LLM exceptions inherit from this base class.
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        model: str | None = None,
        request_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.model = model
        self.request_id = request_id
        self.extra = kwargs

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging."""
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            **self.extra,
        }


class ProviderError(LLMError):
    """
    Exception for provider-level errors.

    Used for errors related to specific LLM providers:
    - Authentication failures
    - Configuration errors
    - Provider unavailable
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message=message, provider=provider, **kwargs)


class AuthenticationError(ProviderError):
    """
    Exception for authentication failures.

    Raised when:
    - Invalid API key
    - Expired credentials
    - Missing authentication
    """



class RateLimitError(ProviderError):
    """
    Exception for rate limit exceeded errors.

    Raised when:
    - Provider rate limit hit (429)
    - Quota exceeded
    - Throttling in effect
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        retry_after: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message=message, provider=provider, **kwargs)
        self.retry_after = retry_after  # Seconds to wait before retry


class CircuitBreakerOpenError(ProviderError):
    """
    Exception when circuit breaker is open.

    Raised when:
    - Provider has too many recent failures
    - Circuit breaker is in open state
    - Provider is temporarily unavailable
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        reopen_after: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message=message, provider=provider, **kwargs)
        self.reopen_after = reopen_after  # Seconds until circuit breaker half-opens


class ProviderUnavailableError(ProviderError):
    """
    Exception when provider is unavailable.

    Raised when:
    - Provider service is down
    - Network connectivity issues
    - Timeout exceeded
    """



class ModelError(LLMError):
    """
    Exception for model-related errors.

    Used for errors related to model behavior:
    - Invalid response format
    - JSON parsing failures
    - Content policy violations
    - Context length exceeded
    """

    def __init__(
        self,
        message: str,
        model: str | None = None,
        response: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message=message, model=model, **kwargs)
        self.response = response


class InvalidResponseError(ModelError):
    """
    Exception for invalid model responses.

    Raised when:
    - Response is empty or malformed
    - Required fields missing
    - Unexpected response structure
    """



class JSONParseError(ModelError):
    """
    Exception for JSON parsing failures.

    Raised when:
    - Model returns invalid JSON for structured output
    - Response cannot be parsed
    - Schema validation fails
    """

    def __init__(
        self,
        message: str,
        raw_response: str | None = None,
        expected_schema: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message=message, **kwargs)
        self.raw_response = raw_response
        self.expected_schema = expected_schema


class ContentPolicyViolationError(ModelError):
    """
    Exception for content policy violations.

    Raised when:
    - Content filtered by provider
    - Safety guidelines violation
    - Blocked content detected
    """



class ContextLengthExceededError(ModelError):
    """
    Exception when context length exceeds model limits.

    Raised when:
    - Input tokens exceed model maximum
    - Context window overflow
    """

    def __init__(
        self,
        message: str,
        model: str | None = None,
        input_tokens: int | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message=message, model=model, **kwargs)
        self.input_tokens = input_tokens
        self.max_tokens = max_tokens


class ConfigurationError(LLMError):
    """
    Exception for configuration errors.

    Raised when:
    - Invalid configuration
    - Missing required settings
    - Incompatible options
    """



class EmbeddingError(LLMError):
    """
    Exception for embedding-related errors.

    Used for errors in embedding generation:
    - Embedding dimension mismatch
    - Failed embedding generation
    - Invalid input for embedding
    """



class RerankError(LLMError):
    """
    Exception for reranking-related errors.

    Used for errors in reranking operations:
    - Failed reranking
    - Invalid rerank response
    - Score computation errors
    """



class StreamError(LLMError):
    """
    Exception for streaming-related errors.

    Used for errors during streaming:
    - Stream interrupted
    - Incomplete response
    - Stream parsing errors
    """

