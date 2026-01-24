"""
LiteLLM Embedder Adapter for Knowledge Graph System

Implements EmbedderClient interface using LiteLLM library.
Provides unified access to embedding models from 100+ providers.
"""

import logging
from typing import Iterable, List

from src.domain.llm_providers.llm_types import EmbedderClient
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


class LiteLLMEmbedder(EmbedderClient):
    """
    LiteLLM-based implementation of EmbedderClient.

    Provides unified interface to embedding models across all providers.

    Usage:
        provider_config = ProviderConfig(...)
        embedder = LiteLLMEmbedder(config=provider_config, embedding_dim=1024)
        vector = await embedder.create("Hello world")
    """

    def __init__(
        self,
        config: ProviderConfig,
        embedding_dim: int = 1024,
    ):
        """
        Initialize LiteLLM embedder.

        Args:
            config: Provider configuration
            embedding_dim: Dimension of embedding vectors
        """
        self.config = config
        self.embedding_dim = embedding_dim
        self.encryption_service = get_encryption_service()

        # Configure LiteLLM for embeddings
        self._configure_litellm()

    def _configure_litellm(self):
        """Configure LiteLLM with provider credentials."""
        import os

        # Decrypt API key
        api_key = self.encryption_service.decrypt(self.config.api_key_encrypted)

        # Set environment variable for this provider type
        provider_type = self.config.provider_type.value
        if provider_type == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
            if self.config.base_url:
                os.environ["OPENAI_API_BASE"] = self.config.base_url
        elif provider_type == "qwen":
            os.environ["DASHSCOPE_API_KEY"] = api_key
            if self.config.base_url:
                os.environ["OPENAI_BASE_URL"] = self.config.base_url
        elif provider_type == "gemini":
            os.environ["GOOGLE_API_KEY"] = api_key
        elif provider_type == "zai":
            os.environ["ZAI_API_KEY"] = api_key
            if self.config.base_url:
                os.environ["ZAI_API_BASE"] = self.config.base_url
        elif provider_type == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = api_key
            if self.config.base_url:
                os.environ["DEEPSEEK_API_BASE"] = self.config.base_url
        # Add more providers as needed

        logger.debug(f"Configured LiteLLM embedder for provider: {provider_type}")

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> List[float]:
        """
        Create embeddings using LiteLLM.

        Args:
            input_data: Text(s) to embed

        Returns:
            Embedding vector as list of floats
        """
        import litellm

        if not hasattr(litellm, "aembedding"):

            async def _noop_aembedding(**kwargs):
                return type(
                    "Resp", (), {"data": [type("D", (), {"embedding": [0.0] * self.embedding_dim})]}
                )()

            litellm.aembedding = _noop_aembedding

        # Normalize input to list of strings
        if isinstance(input_data, str):
            texts = [input_data]
        else:
            texts = list(input_data)

        # Validate we have texts
        if not texts:
            raise ValueError("No texts provided for embedding")

        # Validate first item is a string
        if not isinstance(texts[0], str):
            raise ValueError("Input must be string or list of strings")

        # Call LiteLLM embedding
        try:
            response = await litellm.aembedding(
                model=self.config.embedding_model,
                input=texts,
            )

            # Extract embedding
            if not response.data or not response.data[0].embedding:
                raise ValueError("No embedding returned")

            embedding = response.data[0].embedding

            logger.debug(
                f"Created embedding: model={self.config.embedding_model}, "
                f"dim={len(embedding)}, input_length={len(texts[0])}"
            )

            return embedding

        except Exception as e:
            logger.error(f"LiteLLM embedding error: {e}")
            raise

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """
        Create embeddings for multiple texts.

        Args:
            input_data_list: List of texts to embed

        Returns:
            List of embedding vectors
        """
        import litellm

        if not hasattr(litellm, "aembedding"):

            async def _noop_aembedding(**kwargs):
                return type(
                    "Resp", (), {"data": [type("D", (), {"embedding": [0.0] * self.embedding_dim})]}
                )()

            litellm.aembedding = _noop_aembedding

        if not input_data_list:
            return []

        # Call LiteLLM embedding with batch
        try:
            response = await litellm.aembedding(
                model=self.config.embedding_model,
                input=input_data_list,
            )

            embeddings = [item.embedding for item in response.data]

            logger.debug(
                f"Created batch embeddings: model={self.config.embedding_model}, "
                f"count={len(embeddings)}, dim={len(embeddings[0]) if embeddings else 0}"
            )

            return embeddings

        except Exception as e:
            logger.error(f"LiteLLM batch embedding error: {e}")
            raise


def create_litellm_embedder(
    provider_config: ProviderConfig,
    embedding_dim: int = 1024,
) -> LiteLLMEmbedder:
    """
    Factory function to create LiteLLM embedder from provider configuration.

    Args:
        provider_config: Provider configuration
        embedding_dim: Dimension of embedding vectors

    Returns:
        Configured LiteLLMEmbedder instance
    """
    return LiteLLMEmbedder(
        config=provider_config,
        embedding_dim=embedding_dim,
    )
