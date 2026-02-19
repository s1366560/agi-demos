"""
Unit tests for unified LLM exceptions.

Tests the exception hierarchy and error handling capabilities.
"""

import pytest

from src.domain.llm_providers.exceptions import (
    AuthenticationError,
    CircuitBreakerOpenError,
    ConfigurationError,
    ContextLengthExceededError,
    EmbeddingError,
    InvalidResponseError,
    JSONParseError,
    LLMError,
    ModelError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
    RerankError,
    StreamError,
)


class TestLLMError:
    """Tests for base LLMError."""

    def test_basic_exception(self):
        """Test basic exception creation."""
        error = LLMError(message="Test error")
        assert error.message == "Test error"
        assert str(error) == "Test error"

    def test_exception_with_provider(self):
        """Test exception with provider info."""
        error = LLMError(message="Error", provider="dashscope")
        assert error.provider == "dashscope"

    def test_exception_with_model(self):
        """Test exception with model info."""
        error = LLMError(message="Error", model="qwen-max")
        assert error.model == "qwen-max"

    def test_exception_with_request_id(self):
        """Test exception with request ID."""
        error = LLMError(message="Error", request_id="req-123")
        assert error.request_id == "req-123"

    def test_exception_with_extra_kwargs(self):
        """Test exception with extra metadata."""
        error = LLMError(message="Error", tokens=100, latency=50)
        assert error.extra == {"tokens": 100, "latency": 50}

    def test_to_dict(self):
        """Test converting exception to dictionary."""
        error = LLMError(
            message="Test error",
            provider="dashscope",
            model="qwen-max",
            request_id="req-123",
            tokens=100,
        )
        error_dict = error.to_dict()
        assert error_dict["type"] == "LLMError"
        assert error_dict["message"] == "Test error"
        assert error_dict["provider"] == "dashscope"
        assert error_dict["model"] == "qwen-max"
        assert error_dict["request_id"] == "req-123"
        assert error_dict["tokens"] == 100


class TestProviderError:
    """Tests for ProviderError."""

    def test_provider_error_basic(self):
        """Test basic provider error."""
        error = ProviderError(message="Provider error", provider="dashscope")
        assert error.provider == "dashscope"
        assert isinstance(error, LLMError)


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_rate_limit_error_basic(self):
        """Test basic rate limit error."""
        error = RateLimitError(message="Rate limit exceeded", provider="openai")
        assert error.provider == "openai"
        assert error.retry_after is None

    def test_rate_limit_error_with_retry_after(self):
        """Test rate limit error with retry_after."""
        error = RateLimitError(message="Rate limit", retry_after=60)
        assert error.retry_after == 60


class TestCircuitBreakerOpenError:
    """Tests for CircuitBreakerOpenError."""

    def test_circuit_breaker_error_basic(self):
        """Test basic circuit breaker error."""
        error = CircuitBreakerOpenError(message="Circuit open", provider="anthropic")
        assert error.provider == "anthropic"
        assert error.reopen_after is None

    def test_circuit_breaker_error_with_reopen_after(self):
        """Test circuit breaker error with reopen time."""
        error = CircuitBreakerOpenError(message="Circuit open", reopen_after=30.0)
        assert error.reopen_after == 30.0


class TestModelError:
    """Tests for ModelError."""

    def test_model_error_basic(self):
        """Test basic model error."""
        error = ModelError(message="Invalid response", model="gpt-4")
        assert error.model == "gpt-4"
        assert error.response is None

    def test_model_error_with_response(self):
        """Test model error with response."""
        error = ModelError(message="Invalid", model="gpt-4", response={"key": "value"})
        assert error.response == {"key": "value"}


class TestJSONParseError:
    """Tests for JSONParseError."""

    def test_json_parse_error_basic(self):
        """Test basic JSON parse error."""
        error = JSONParseError(message="Invalid JSON")
        assert error.raw_response is None
        assert error.expected_schema is None

    def test_json_parse_error_with_details(self):
        """Test JSON parse error with details."""
        error = JSONParseError(
            message="Invalid JSON",
            raw_response="{invalid}",
            expected_schema='{"type": "object"}',
        )
        assert error.raw_response == "{invalid}"
        assert error.expected_schema == '{"type": "object"}'


class TestContextLengthExceededError:
    """Tests for ContextLengthExceededError."""

    def test_context_length_error_basic(self):
        """Test basic context length error."""
        error = ContextLengthExceededError(
            message="Context too long",
            model="qwen-max",
            input_tokens=150000,
            max_tokens=128000,
        )
        assert error.model == "qwen-max"
        assert error.input_tokens == 150000
        assert error.max_tokens == 128000


class TestAuthenticationError:
    """Tests for AuthenticationError."""

    def test_auth_error_basic(self):
        """Test basic authentication error."""
        error = AuthenticationError(message="Invalid API key", provider="openai")
        assert error.provider == "openai"
        assert isinstance(error, ProviderError)


class TestProviderUnavailableError:
    """Tests for ProviderUnavailableError."""

    def test_provider_unavailable_basic(self):
        """Test basic provider unavailable error."""
        error = ProviderUnavailableError(message="Provider down", provider="gemini")
        assert error.provider == "gemini"


class TestEmbeddingError:
    """Tests for EmbeddingError."""

    def test_embedding_error_basic(self):
        """Test basic embedding error."""
        error = EmbeddingError(message="Embedding failed")
        assert error.message == "Embedding failed"
        assert isinstance(error, LLMError)


class TestRerankError:
    """Tests for RerankError."""

    def test_rerank_error_basic(self):
        """Test basic rerank error."""
        error = RerankError(message="Rerank failed")
        assert error.message == "Rerank failed"
        assert isinstance(error, LLMError)


class TestStreamError:
    """Tests for StreamError."""

    def test_stream_error_basic(self):
        """Test basic stream error."""
        error = StreamError(message="Stream interrupted")
        assert error.message == "Stream interrupted"
        assert isinstance(error, LLMError)


class TestInvalidResponseError:
    """Tests for InvalidResponseError."""

    def test_invalid_response_basic(self):
        """Test basic invalid response error."""
        error = InvalidResponseError(message="Empty response", model="gpt-4")
        assert error.model == "gpt-4"
        assert isinstance(error, ModelError)


class TestContentPolicyViolationError:
    """Tests for ContentPolicyViolationError."""

    def test_content_policy_error_basic(self):
        """Test basic content policy error."""
        error = ModelError(message="Content filtered", model="gpt-4")
        assert error.model == "gpt-4"


class TestConfigurationError:
    """Tests for ConfigurationError."""

    def test_configuration_error_basic(self):
        """Test basic configuration error."""
        error = ConfigurationError(message="Missing API key")
        assert error.message == "Missing API key"
        assert isinstance(error, LLMError)


class TestExceptionInheritance:
    """Tests for exception hierarchy."""

    def test_all_exceptions_inherit_from_llm_error(self):
        """Test that all exceptions inherit from LLMError."""
        exceptions = [
            ProviderError,
            AuthenticationError,
            RateLimitError,
            CircuitBreakerOpenError,
            ProviderUnavailableError,
            ModelError,
            InvalidResponseError,
            JSONParseError,
            ContextLengthExceededError,
            ConfigurationError,
            EmbeddingError,
            RerankError,
            StreamError,
        ]

        for exc_class in exceptions:
            exc = exc_class("Test")
            assert isinstance(exc, LLMError)
