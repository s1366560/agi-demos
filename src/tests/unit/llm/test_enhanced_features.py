"""
Unit tests for LLM cache, validation, and metrics components.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from src.domain.llm_providers.models import ProviderType
from src.infrastructure.llm.cache import (
    CacheConfig,
    ResponseCache,
    get_response_cache,
)
from src.infrastructure.llm.metrics import (
    MetricsCollector,
    estimate_cost,
    get_metrics_collector,
)
from src.infrastructure.llm.validation import (
    StructuredOutputValidator,
    ValidationConfig,
    get_structured_validator,
)


class TestResponseCache:
    """Tests for ResponseCache."""

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        """Cache miss returns None."""
        cache = ResponseCache(CacheConfig(enabled=True))
        result = await cache.get(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_returns_response(self):
        """Cache hit returns stored response."""
        cache = ResponseCache(CacheConfig(enabled=True))
        messages = [{"role": "user", "content": "hello"}]
        response = {"content": "Hello! How can I help?"}

        await cache.set(messages, response, model="gpt-4")
        result = await cache.get(messages, model="gpt-4")

        assert result == response

    @pytest.mark.asyncio
    async def test_disabled_cache_returns_none(self):
        """Disabled cache always returns None."""
        cache = ResponseCache(CacheConfig(enabled=False))
        messages = [{"role": "user", "content": "hello"}]
        response = {"content": "Hello!"}

        await cache.set(messages, response, model="gpt-4")
        result = await cache.get(messages, model="gpt-4")

        assert result is None

    @pytest.mark.asyncio
    async def test_temperature_gt_0_not_cached(self):
        """Non-deterministic responses (temperature > 0) are not cached."""
        cache = ResponseCache(CacheConfig(enabled=True))
        messages = [{"role": "user", "content": "hello"}]
        response = {"content": "Hello!"}

        await cache.set(messages, response, model="gpt-4", temperature=0.7)
        result = await cache.get(messages, model="gpt-4", temperature=0.7)

        assert result is None

    @pytest.mark.asyncio
    async def test_different_models_different_keys(self):
        """Different models produce different cache keys."""
        cache = ResponseCache(CacheConfig(enabled=True))
        messages = [{"role": "user", "content": "hello"}]

        await cache.set(messages, {"content": "gpt4 response"}, model="gpt-4")
        await cache.set(messages, {"content": "gpt3 response"}, model="gpt-3.5-turbo")

        result_gpt4 = await cache.get(messages, model="gpt-4")
        result_gpt3 = await cache.get(messages, model="gpt-3.5-turbo")

        assert result_gpt4["content"] == "gpt4 response"
        assert result_gpt3["content"] == "gpt3 response"

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """LRU eviction works when cache is full."""
        # Set min_response_length to 1 so short test responses are cached
        cache = ResponseCache(CacheConfig(enabled=True, max_size=2, min_response_length=1))

        # Add two entries - cache is now full
        await cache.set([{"role": "user", "content": "first"}], {"content": "r1"}, model="m")
        await cache.set([{"role": "user", "content": "second"}], {"content": "r2"}, model="m")

        # Both should be present
        assert await cache.get([{"role": "user", "content": "first"}], model="m") is not None
        assert await cache.get([{"role": "user", "content": "second"}], model="m") is not None

        # Add third entry - should evict the oldest (first was accessed more recently via get)
        # After the gets above, "second" was accessed last, so "first" is oldest
        await cache.set([{"role": "user", "content": "third"}], {"content": "r3"}, model="m")

        # Third should exist
        result3 = await cache.get([{"role": "user", "content": "third"}], model="m")
        assert result3 is not None

        # One of the first two should be evicted
        result1 = await cache.get([{"role": "user", "content": "first"}], model="m")
        result2 = await cache.get([{"role": "user", "content": "second"}], model="m")

        # At least one should be evicted
        assert result1 is None or result2 is None
        # Cache size should be 2
        assert cache._stats.size == 2

    def test_get_stats(self):
        """Stats are correctly tracked."""
        cache = ResponseCache()
        stats = cache.get_stats()

        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats
        assert "size" in stats

    def test_clear(self):
        """Clear removes all entries."""
        cache = ResponseCache()
        cache._cache["test"] = MagicMock()
        cache.clear()
        assert len(cache._cache) == 0


class TestStructuredOutputValidator:
    """Tests for StructuredOutputValidator."""

    class SampleModel(BaseModel):
        name: str
        age: int

    def test_validate_valid_json(self):
        """Valid JSON is correctly validated."""
        validator = StructuredOutputValidator()
        content = '{"name": "Alice", "age": 30}'

        result = validator.validate(content, self.SampleModel)

        assert result.success
        assert result.data == {"name": "Alice", "age": 30}
        assert result.model_instance is not None

    def test_validate_json_in_code_block(self):
        """JSON in code blocks is extracted."""
        validator = StructuredOutputValidator()
        content = '```json\n{"name": "Bob", "age": 25}\n```'

        result = validator.validate(content, self.SampleModel)

        assert result.success
        assert result.data["name"] == "Bob"

    def test_validate_invalid_json(self):
        """Invalid JSON returns error."""
        validator = StructuredOutputValidator()
        content = "not valid json"

        result = validator.validate(content, self.SampleModel)

        assert not result.success
        assert "JSON parsing error" in result.error

    def test_validate_missing_field(self):
        """Missing required field returns validation error."""
        validator = StructuredOutputValidator()
        content = '{"name": "Alice"}'  # Missing 'age'

        result = validator.validate(content, self.SampleModel)

        assert not result.success
        assert "Validation errors" in result.error

    def test_validate_wrong_type(self):
        """Wrong field type returns validation error."""
        validator = StructuredOutputValidator()
        content = '{"name": "Alice", "age": "thirty"}'  # age should be int

        result = validator.validate(content, self.SampleModel)

        assert not result.success
        assert "Validation errors" in result.error

    def test_extract_json_with_surrounding_text(self):
        """JSON is extracted from surrounding text."""
        validator = StructuredOutputValidator()
        content = 'Here is the result: {"name": "Test", "age": 20} Hope this helps!'

        result = validator.validate(content, self.SampleModel)

        assert result.success

    @pytest.mark.asyncio
    async def test_generate_validated_success(self):
        """generate_validated returns validated result."""
        validator = StructuredOutputValidator(ValidationConfig(max_retries=1))

        mock_client = AsyncMock()
        mock_client.generate_response = AsyncMock(
            return_value={"content": '{"name": "Test", "age": 25}'}
        )

        result = await validator.generate_validated(
            llm_client=mock_client,
            messages=[{"role": "user", "content": "Generate a person"}],
            response_model=self.SampleModel,
        )

        assert result.success
        assert result.data["name"] == "Test"
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_generate_validated_retry_on_failure(self):
        """generate_validated retries on validation failure."""
        validator = StructuredOutputValidator(
            ValidationConfig(max_retries=2, include_error_feedback=True)
        )

        mock_client = AsyncMock()
        mock_client.generate_response = AsyncMock(
            side_effect=[
                {"content": '{"name": "Test"}'},  # Missing age
                {"content": '{"name": "Test", "age": 25}'},  # Valid
            ]
        )

        result = await validator.generate_validated(
            llm_client=mock_client,
            messages=[{"role": "user", "content": "Generate a person"}],
            response_model=self.SampleModel,
        )

        assert result.success
        assert result.attempts == 2


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_record_request(self):
        """Requests are correctly recorded."""
        collector = MetricsCollector()

        collector.record_request(
            provider=ProviderType.OPENAI,
            model="gpt-4",
            success=True,
            latency_ms=100,
            prompt_tokens=50,
            completion_tokens=100,
        )

        metrics = collector.get_metrics()
        assert metrics["overall"]["request_count"] == 1
        assert metrics["overall"]["success_count"] == 1
        assert metrics["overall"]["prompt_tokens"] == 50
        assert metrics["overall"]["completion_tokens"] == 100

    def test_track_request_context_manager(self):
        """Context manager tracks requests correctly."""
        collector = MetricsCollector()

        with collector.track_request(ProviderType.OPENAI, "gpt-4") as tracker:
            tracker.set_tokens(prompt_tokens=100, completion_tokens=50)

        metrics = collector.get_metrics()
        assert metrics["overall"]["request_count"] == 1
        assert metrics["overall"]["success_count"] == 1

    def test_track_request_records_error(self):
        """Context manager records errors correctly."""
        collector = MetricsCollector()

        try:
            with collector.track_request(ProviderType.OPENAI, "gpt-4"):
                raise ValueError("Test error")
        except ValueError:
            pass

        metrics = collector.get_metrics()
        assert metrics["overall"]["error_count"] == 1
        assert "ValueError" in metrics["overall"]["error_types"]

    def test_metrics_by_provider(self):
        """Metrics are tracked per provider."""
        collector = MetricsCollector()

        collector.record_request(ProviderType.OPENAI, "gpt-4", True, 100)
        collector.record_request(ProviderType.GEMINI, "gemini-pro", True, 150)
        collector.record_request(ProviderType.OPENAI, "gpt-4", True, 120)

        openai_metrics = collector.get_provider_metrics(ProviderType.OPENAI)
        gemini_metrics = collector.get_provider_metrics(ProviderType.GEMINI)

        assert openai_metrics["request_count"] == 2
        assert gemini_metrics["request_count"] == 1

    def test_metrics_by_model(self):
        """Metrics are tracked per model."""
        collector = MetricsCollector()

        collector.record_request(ProviderType.OPENAI, "gpt-4", True, 100)
        collector.record_request(ProviderType.OPENAI, "gpt-3.5-turbo", True, 50)
        collector.record_request(ProviderType.OPENAI, "gpt-4", True, 120)

        gpt4_metrics = collector.get_model_metrics("gpt-4")
        gpt35_metrics = collector.get_model_metrics("gpt-3.5-turbo")

        assert gpt4_metrics["request_count"] == 2
        assert gpt35_metrics["request_count"] == 1

    def test_get_recent_errors(self):
        """Recent errors are retrievable."""
        collector = MetricsCollector()

        collector.record_request(
            ProviderType.OPENAI, "gpt-4", False, 100, error_type="RateLimitError"
        )
        collector.record_request(
            ProviderType.GEMINI, "gemini-pro", False, 50, error_type="TimeoutError"
        )

        errors = collector.get_recent_errors(limit=10)

        assert len(errors) == 2
        assert errors[0]["error_type"] == "TimeoutError"  # Most recent first

    def test_reset(self):
        """Reset clears all metrics."""
        collector = MetricsCollector()
        collector.record_request(ProviderType.OPENAI, "gpt-4", True, 100)

        collector.reset()

        metrics = collector.get_metrics()
        assert metrics["overall"]["request_count"] == 0


class TestCostEstimation:
    """Tests for cost estimation."""

    def test_gpt4_cost(self):
        """GPT-4 cost is correctly estimated."""
        cost = estimate_cost("gpt-4", prompt_tokens=1000, completion_tokens=500)
        # Input: 1000/1000 * 0.03 = 0.03
        # Output: 500/1000 * 0.06 = 0.03
        # Total: 0.06
        assert abs(cost - 0.06) < 0.001

    def test_gpt35_cost(self):
        """GPT-3.5-turbo cost is correctly estimated."""
        cost = estimate_cost("gpt-3.5-turbo", prompt_tokens=1000, completion_tokens=1000)
        # Input: 1000/1000 * 0.0005 = 0.0005
        # Output: 1000/1000 * 0.0015 = 0.0015
        # Total: 0.002
        assert abs(cost - 0.002) < 0.0001

    def test_unknown_model_uses_default(self):
        """Unknown models use default cost."""
        cost = estimate_cost("unknown-model", prompt_tokens=1000, completion_tokens=1000)
        assert cost > 0


class TestGlobalInstances:
    """Tests for global singleton instances."""

    def test_cache_singleton(self):
        """Global cache is singleton."""
        cache1 = get_response_cache()
        cache2 = get_response_cache()
        assert cache1 is cache2

    def test_validator_singleton(self):
        """Global validator is singleton."""
        v1 = get_structured_validator()
        v2 = get_structured_validator()
        assert v1 is v2

    def test_metrics_singleton(self):
        """Global metrics collector is singleton."""
        m1 = get_metrics_collector()
        m2 = get_metrics_collector()
        assert m1 is m2
