"""
Abstract base classes for LLM provider implementations.

This module defines the contracts that all LLM provider implementations must follow,
ensuring consistency and enabling easy extension for new providers.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel

from src.domain.llm_providers.llm_types import Message, ModelSize


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM clients.

    All LLM provider implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    async def generate_response(
        self,
        messages: list[Message],
        response_model: Optional[type[BaseModel]] = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        """
        Generate response from LLM.

        Args:
            messages: List of messages (system, user, assistant)
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens in response
            model_size: Which model to use (small or medium)

        Returns:
            Dictionary with response content or parsed structured data

        Raises:
            RateLimitError: If provider rate limit is hit
            Exception: For other errors
        """
        pass

    @abstractmethod
    def _get_model_for_size(self, model_size: ModelSize) -> str:
        """
        Get model name for requested size.

        Args:
            model_size: Small or medium

        Returns:
            Model name string
        """
        pass

    @abstractmethod
    def _get_provider_type(self) -> str:
        """
        Return provider type identifier for observability.

        Returns:
            Provider type string (e.g., "openai", "qwen", "deepseek")
        """
        pass


class BaseEmbedder(ABC):
    """
    Abstract base class for embedders.

    All embedder implementations must inherit from this class
    and implement the required methods.
    """

    @property
    @abstractmethod
    def embedding_dim(self) -> int:
        """
        Get the dimension of embedding vectors.

        Returns:
            Embedding dimension
        """
        pass

    @abstractmethod
    async def create(
        self,
        input_data: str | list[str],
    ) -> list[float]:
        """
        Create embedding for input.

        Args:
            input_data: Text or list of texts to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            ValueError: If input is invalid
            Exception: For API errors
        """
        pass

    @abstractmethod
    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """
        Create embeddings for batch of texts.

        Args:
            input_data_list: List of texts to embed

        Returns:
            List of embedding vectors

        Raises:
            ValueError: If input list is empty
            Exception: For API errors
        """
        pass


class BaseReranker(ABC):
    """
    Abstract base class for rerankers.

    All reranker implementations must inherit from this class
    and implement the required methods.
    """

    @abstractmethod
    async def rank(
        self,
        query: str,
        passages: list[str],
        top_n: Optional[int] = None,
    ) -> list[tuple[str, float]]:
        """
        Rank passages by relevance to query.

        Args:
            query: Search query
            passages: List of passages to rank
            top_n: Optional limit on number of results

        Returns:
            List of (passage, score) tuples sorted by relevance (descending)
            Scores should be normalized to [0, 1] range

        Raises:
            ValueError: If input is invalid
            Exception: For API errors
        """
        pass

    @abstractmethod
    async def score(self, query: str, passage: str) -> float:
        """
        Score single passage relevance to query.

        Args:
            query: Search query
            passage: Passage to score

        Returns:
            Relevance score in [0, 1] range

        Raises:
            ValueError: If input is invalid
            Exception: For API errors
        """
        pass


class ProviderHealthCheck(ABC):
    """
    Abstract base class for provider health checks.

    Allows monitoring and automatic fallback between providers.
    """

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if the provider is healthy and accessible.

        Returns:
            True if provider is healthy, False otherwise
        """
        pass

    @abstractmethod
    async def get_model_info(self, model: str) -> dict[str, Any]:
        """
        Get information about a specific model.

        Args:
            model: Model name

        Returns:
            Dictionary with model information (e.g., max_tokens, context_length)
        """
        pass
