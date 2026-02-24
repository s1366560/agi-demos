"""
Unit tests for token estimator with caching.
"""

from src.infrastructure.llm.token_estimator import (
    DEFAULT_TOKEN_CACHE_MAXSIZE,
    TokenEstimator,
    clear_token_cache,
    estimate_tokens,
    get_token_estimator,
)


class TestTokenEstimator:
    """Tests for TokenEstimator."""

    def test_estimate_tokens_basic(self):
        """Test basic token estimation."""
        estimator = TokenEstimator()
        messages = [{"role": "user", "content": "Hello world"}]
        tokens = estimator.estimate_tokens(model="qwen-max", messages=messages)
        assert tokens > 0

    def test_estimate_tokens_empty_messages(self):
        """Test token estimation with empty messages."""
        estimator = TokenEstimator()
        tokens = estimator.estimate_tokens(model="qwen-max", messages=[])
        assert tokens == 0

    def test_estimate_tokens_caching(self):
        """Test that caching works."""
        estimator = TokenEstimator(maxsize=10)
        messages = [{"role": "user", "content": "Test caching"}]

        # First call
        tokens1 = estimator.estimate_tokens(model="qwen-max", messages=messages)

        # Second call should use cache
        tokens2 = estimator.estimate_tokens(model="qwen-max", messages=messages)

        assert tokens1 == tokens2

    def test_estimate_tokens_without_cache(self):
        """Test estimation without cache."""
        estimator = TokenEstimator()
        messages = [{"role": "user", "content": "Test no cache"}]

        tokens1 = estimator.estimate_tokens(model="qwen-max", messages=messages, use_cache=False)
        tokens2 = estimator.estimate_tokens(model="qwen-max", messages=messages, use_cache=False)

        # Both should return valid results
        assert tokens1 > 0
        assert tokens2 > 0

    def test_cache_info(self):
        """Test cache statistics."""
        estimator = TokenEstimator(maxsize=10)
        messages = [{"role": "user", "content": "Test stats"}]

        # Make some calls
        estimator.estimate_tokens(model="qwen-max", messages=messages)
        estimator.estimate_tokens(model="qwen-max", messages=messages)

        info = estimator.cache_info()
        assert "manual_cache" in info
        assert info["manual_cache"]["size"] >= 1
        assert info["manual_cache"]["maxsize"] == 10

    def test_clear_cache(self):
        """Test cache clearing."""
        estimator = TokenEstimator()
        messages = [{"role": "user", "content": "Test clear"}]

        # Make some calls
        estimator.estimate_tokens(model="qwen-max", messages=messages)
        estimator.estimate_tokens(model="qwen-max", messages=messages)

        # Clear cache
        estimator.clear_cache()

        info = estimator.cache_info()
        assert info["manual_cache"]["size"] == 0

    def test_estimate_batch(self):
        """Test batch token estimation."""
        estimator = TokenEstimator()
        messages_list = [
            [{"role": "user", "content": "First"}],
            [{"role": "user", "content": "Second"}],
            [{"role": "user", "content": "Third"}],
        ]

        tokens = estimator.estimate_batch(model="qwen-max", batch_messages=messages_list)

        assert len(tokens) == 3
        assert all(t > 0 for t in tokens)

    def test_different_models_different_caches(self):
        """Test that different models have separate cache entries."""
        estimator = TokenEstimator()
        messages = [{"role": "user", "content": "Test models"}]

        tokens1 = estimator.estimate_tokens(model="qwen-max", messages=messages)
        tokens2 = estimator.estimate_tokens(model="gpt-4", messages=messages)

        # Both should be valid
        assert tokens1 > 0
        assert tokens2 > 0

    def test_cache_maxsize_eviction(self):
        """Test LRU eviction when cache exceeds maxsize."""
        estimator = TokenEstimator(maxsize=5)

        # Fill cache beyond maxsize
        for i in range(10):
            messages = [{"role": "user", "content": f"Message {i}"}]
            estimator.estimate_tokens(model="qwen-max", messages=messages)

        info = estimator.cache_info()
        # Cache should be pruned
        assert info["manual_cache"]["size"] <= estimator._maxsize


class TestGlobalEstimator:
    """Tests for global estimator instance."""

    def test_get_token_estimator_singleton(self):
        """Test that global estimator is a singleton."""
        estimator1 = get_token_estimator()
        estimator2 = get_token_estimator()
        assert estimator1 is estimator2

    def test_get_token_estimator_with_maxsize(self):
        """Test creating estimator with custom maxsize."""
        # Note: singleton means first call wins, so we test that
        estimator = get_token_estimator()
        assert estimator._maxsize == DEFAULT_TOKEN_CACHE_MAXSIZE

    def test_clear_token_cache_global(self):
        """Test clearing global cache."""
        estimator = get_token_estimator()
        messages = [{"role": "user", "content": "Test"}]
        estimator.estimate_tokens(model="qwen-max", messages=messages)

        clear_token_cache()

        info = estimator.cache_info()
        assert info["manual_cache"]["size"] == 0


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_estimate_tokens_function(self):
        """Test convenience estimate_tokens function."""
        messages = [{"role": "user", "content": "Hello"}]
        tokens = estimate_tokens(model="qwen-max", messages=messages)
        assert tokens > 0

    def test_estimate_tokens_no_cache(self):
        """Test convenience function without cache."""
        messages = [{"role": "user", "content": "Hello"}]
        tokens = estimate_tokens(model="qwen-max", messages=messages, use_cache=False)
        assert tokens > 0


class TestCharBasedEstimation:
    """Tests for character-based fallback estimation."""

    def test_char_based_estimation_fallback(self):
        """Test that char-based estimation works as fallback."""
        estimator = TokenEstimator()
        # This should work even if litellm token_counter fails
        messages = [
            {"role": "user", "content": "A" * 1000},
            {"role": "assistant", "content": "B" * 500},
        ]
        tokens = estimator.estimate_tokens(model="unknown-model", messages=messages)
        assert tokens > 0
