"""
Abstract base classes for LLM provider implementations.

This module defines the contracts that all LLM provider implementations must follow,
ensuring consistency and enabling easy extension for new providers.

For LLM clients, use LLMClient from llm_types.py:
    from src.domain.llm_providers.llm_types import LLMClient
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


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
