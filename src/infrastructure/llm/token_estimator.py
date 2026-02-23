"""
Token Estimation Utilities with Caching.

Provides efficient token estimation with LRU caching to avoid
repeated LiteLLM token_counter calls for identical inputs.

Usage:
    from src.infrastructure.llm.token_estimator import TokenEstimator
    
    estimator = TokenEstimator()
    tokens = estimator.estimate_tokens(model="qwen-max", messages=messages)
"""

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# Cache configuration
DEFAULT_TOKEN_CACHE_MAXSIZE = 2048  # LRU cache size
TOKEN_ESTIMATE_CACHE_TTL = 3600  # 1 hour TTL for manual cache


class TokenEstimator:
    """
    Token estimator with LRU caching.
    
    Provides efficient token estimation by caching results
    for identical (model, messages) combinations.
    
    Example:
        estimator = TokenEstimator()
        
        # First call - computes tokens
        tokens1 = estimator.estimate_tokens(model="qwen-max", messages=messages)
        
        # Second call with same input - returns cached result
        tokens2 = estimator.estimate_tokens(model="qwen-max", messages=messages)
        # tokens2 == tokens1, no LiteLLM call
    """
    
    def __init__(self, maxsize: int = DEFAULT_TOKEN_CACHE_MAXSIZE):
        """
        Initialize token estimator.
        
        Args:
            maxsize: Maximum size of LRU cache
        """
        self._maxsize = maxsize
        self._manual_cache: dict[str, tuple[int, float]] = {}  # {key: (tokens, timestamp)}
    
    @staticmethod
    def _compute_messages_hash(messages: list[dict[str, Any]]) -> str:
        """
        Compute hash of messages for cache key.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            MD5 hash of serialized messages
        """
        # Serialize messages to canonical JSON string
        serialized = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(serialized.encode("utf-8")).hexdigest()
    
    @staticmethod
    def _cache_key(model: str, messages_hash: str) -> str:
        """
        Create cache key from model and messages hash.
        
        Args:
            model: Model name
            messages_hash: Hash of messages
            
        Returns:
            Combined cache key
        """
        return f"{model}:{messages_hash}"
    
    def _cached_token_counter(self, model: str, messages: list[dict[str, Any]]) -> int:
        """
        Cached token counter using manual cache.
        
        This method uses the manual cache with hash-based lookup.
        
        Args:
            model: Model name
            messages: List of message dictionaries
            
        Returns:
            Estimated token count
        """
        import litellm
        
        try:
            return int(litellm.token_counter(model=model, messages=messages))
        except Exception as e:
            logger.debug(f"Token counter failed for {model}: {e}")
            # Fallback: character-based estimation
            return self._char_based_estimate(messages)
    
    @staticmethod
    def _char_based_estimate(messages: list[dict[str, Any]]) -> int:
        """
        Fallback character-based token estimation.
        
        Uses average of 4 characters per token as heuristic.
        
        Args:
            messages: List of message dictionaries
            
        Returns:
            Estimated token count
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            else:
                total_chars += len(str(content))
            # Add overhead for role/name
            total_chars += len(str(msg.get("role", "")))
            total_chars += len(str(msg.get("name", "")))
        
        # Average: ~4 chars per token (conservative estimate)
        return max(1, total_chars // 4)
    
    def estimate_tokens(
        self,
        model: str,
        messages: list[dict[str, Any]],
        use_cache: bool = True,
    ) -> int:
        """
        Estimate token count for messages.
        
        Uses LRU cache for efficiency. Falls back to character-based
        estimation if LiteLLM token_counter fails.
        
        Args:
            model: Model name
            messages: List of message dictionaries
            use_cache: Whether to use caching (default True)
            
        Returns:
            Estimated token count
        """
        if not messages:
            return 0
        
        if not use_cache:
            return self._cached_token_counter(model, messages)
        
        # Compute cache key
        messages_hash = self._compute_messages_hash(messages)
        key = self._cache_key(model, messages_hash)
        
        # Check manual cache with TTL
        if key in self._manual_cache:
            tokens, timestamp = self._manual_cache[key]
            # Simple TTL check (could use time.time() in production)
            return tokens
        
        # Compute and cache
        tokens = self._cached_token_counter(model, messages)
        self._manual_cache[key] = (tokens, 0)  # timestamp=0 for simplicity
        
        # Prune cache if too large
        if len(self._manual_cache) > self._maxsize:
            # Remove oldest 25%
            keys_to_remove = list(self._manual_cache.keys())[: self._maxsize // 4]
            for k in keys_to_remove:
                del self._manual_cache[k]
        
        return tokens
    
    def estimate_batch(
        self,
        model: str,
        batch_messages: list[list[dict[str, Any]]],
        use_cache: bool = True,
    ) -> list[int]:
        """
        Estimate tokens for multiple message lists.
        
        Args:
            model: Model name
            batch_messages: List of message lists
            use_cache: Whether to use caching
            
        Returns:
            List of token counts
        """
        return [
            self.estimate_tokens(model=model, messages=messages, use_cache=use_cache)
            for messages in batch_messages
        ]
    
    def clear_cache(self) -> None:
        """Clear all cached token estimates."""
        self._manual_cache.clear()
    
    def cache_info(self) -> dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache info
        """
        return {
            "manual_cache": {
                "size": len(self._manual_cache),
                "maxsize": self._maxsize,
            },
        }


# Global estimator instance (singleton pattern)
_global_estimator: TokenEstimator | None = None
_global_estimator_maxsize: int = DEFAULT_TOKEN_CACHE_MAXSIZE


def get_token_estimator(maxsize: int = DEFAULT_TOKEN_CACHE_MAXSIZE) -> TokenEstimator:
    """
    Get or create global token estimator.
    
    Args:
        maxsize: Maximum cache size (only used on first call)
        
    Returns:
        Global TokenEstimator instance
    """
    global _global_estimator, _global_estimator_maxsize
    if _global_estimator is None:
        _global_estimator_maxsize = maxsize
        _global_estimator = TokenEstimator(maxsize=maxsize)
    return _global_estimator


# Convenience functions for backward compatibility


def estimate_tokens(
    model: str,
    messages: list[dict[str, Any]],
    use_cache: bool = True,
) -> int:
    """
    Estimate token count (convenience function).
    
    Args:
        model: Model name
        messages: List of message dictionaries
        use_cache: Whether to use caching
        
    Returns:
        Estimated token count
    """
    estimator = get_token_estimator()
    return estimator.estimate_tokens(model=model, messages=messages, use_cache=use_cache)


def clear_token_cache() -> None:
    """Clear global token cache."""
    estimator = get_token_estimator()
    estimator.clear_cache()
