"""
LiteLLM Embedder Adapter for Knowledge Graph System

Implements EmbedderClient interface using LiteLLM library.
Provides unified access to embedding models from 100+ providers.

Supported Providers:
- OpenAI (text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002)
- Cohere (embed-english-v3.0, embed-multilingual-v3.0)
- Google Gemini (text-embedding-004)
- Azure OpenAI (text-embedding-3-small)
- Bedrock (amazon.titan-embed-text-v1)
- Qwen/Dashscope (text-embedding-v3)
- ZhipuAI (embedding-3)
- And many more through LiteLLM
"""

import logging
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from src.domain.llm_providers.base import BaseEmbedder
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


# Default embedding dimensions by provider and model
EMBEDDING_DIMENSIONS = {
    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # Cohere
    "embed-english-v3.0": 1024,
    "embed-multilingual-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-light-v3.0": 384,
    # Google Gemini
    "text-embedding-004": 768,
    "textembedding-gecko": 768,
    # Qwen/Dashscope
    "text-embedding-v3": 1024,
    "text-embedding-v2": 1536,
    # ZhipuAI
    "embedding-3": 1024,
    "embedding-2": 1024,
    # Bedrock
    "amazon.titan-embed-text-v1": 1536,
    "amazon.titan-embed-text-v2:0": 1024,
    # Mistral
    "mistral-embed": 1024,
    # Voyage
    "voyage-2": 1024,
    "voyage-large-2": 1536,
}

# Default models by provider
DEFAULT_EMBEDDING_MODELS = {
    ProviderType.OPENAI: "text-embedding-3-small",
    ProviderType.ANTHROPIC: "text-embedding-3-small",  # Uses OpenAI
    ProviderType.GEMINI: "text-embedding-004",
    ProviderType.QWEN: "text-embedding-v3",
    ProviderType.DEEPSEEK: "text-embedding-v3",  # Uses Qwen fallback
    ProviderType.ZAI: "embedding-3",
    ProviderType.COHERE: "embed-english-v3.0",
    ProviderType.MISTRAL: "mistral-embed",
    ProviderType.AZURE_OPENAI: "text-embedding-3-small",
    ProviderType.BEDROCK: "amazon.titan-embed-text-v1",
    ProviderType.VERTEX: "textembedding-gecko",
    ProviderType.GROQ: "text-embedding-3-small",  # Uses OpenAI
}


@dataclass
class LiteLLMEmbedderConfig:
    """Configuration for LiteLLM Embedder."""

    embedding_model: str
    embedding_dim: int = 1024
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    provider_type: Optional[ProviderType] = None


class LiteLLMEmbedder(BaseEmbedder):
    """
    LiteLLM-based implementation of EmbedderClient.

    Provides unified interface to embedding models across all providers.

    Usage:
        provider_config = ProviderConfig(...)
        embedder = LiteLLMEmbedder(config=provider_config)
        vector = await embedder.create("Hello world")
    """

    def __init__(
        self,
        config: ProviderConfig | LiteLLMEmbedderConfig,
        embedding_dim: Optional[int] = None,
    ):
        """
        Initialize LiteLLM embedder.

        Args:
            config: Provider configuration or embedder config
            embedding_dim: Override embedding dimension (auto-detected if not provided)
        """
        if isinstance(config, LiteLLMEmbedderConfig):
            self._embedding_model = config.embedding_model
            self._embedding_dim = embedding_dim or config.embedding_dim
            self._api_key = config.api_key
            self._base_url = config.base_url
            self._provider_type = config.provider_type
        else:
            self._provider_config = config
            self._embedding_model = config.embedding_model or self._get_default_model(
                config.provider_type
            )
            self._embedding_dim = embedding_dim or self._detect_embedding_dim(self._embedding_model)
            self._provider_type = config.provider_type
            self._base_url = config.base_url

            # Decrypt API key
            encryption_service = get_encryption_service()
            self._api_key = encryption_service.decrypt(config.api_key_encrypted)

        logger.debug(
            f"LiteLLM embedder initialized: provider={self._provider_type}, "
            f"model={self._embedding_model}, dim={self._embedding_dim}"
        )

    def _get_default_model(self, provider_type: ProviderType) -> str:
        """Get default embedding model for provider."""
        return DEFAULT_EMBEDDING_MODELS.get(provider_type, "text-embedding-3-small")

    def _detect_embedding_dim(self, model: str) -> int:
        """Detect embedding dimension from model name."""
        # Check exact match
        if model in EMBEDDING_DIMENSIONS:
            return EMBEDDING_DIMENSIONS[model]

        # Check partial match (for prefixed models like "gemini/text-embedding-004")
        for key, dim in EMBEDDING_DIMENSIONS.items():
            if key in model:
                return dim

        # Default fallback
        return 1024

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dim

    def _configure_litellm(self):
        """No-op. Kept for backward compatibility.

        API key is now passed per-request via the ``api_key`` parameter to
        ``litellm.aembedding()`` instead of polluting ``os.environ``.
        """

    def _get_litellm_model_name(self) -> str:
        """Get model name in LiteLLM format."""
        model = self._embedding_model
        provider_type = self._provider_type.value if self._provider_type else None

        # Add provider prefix if needed
        if provider_type == "gemini" and not model.startswith("gemini/"):
            return f"gemini/{model}"
        elif provider_type == "cohere" and not model.startswith("cohere/"):
            return f"cohere/{model}"
        elif provider_type == "bedrock" and not model.startswith("bedrock/"):
            return f"bedrock/{model}"
        elif provider_type == "vertex" and not model.startswith("vertex_ai/"):
            return f"vertex_ai/{model}"
        elif provider_type == "mistral" and not model.startswith("mistral/"):
            return f"mistral/{model}"
        elif provider_type == "azure_openai" and not model.startswith("azure/"):
            return f"azure/{model}"
        elif provider_type == "qwen":
            # Qwen uses OpenAI-compatible API via Dashscope
            if not model.startswith("openai/"):
                return f"openai/{model}"
        elif provider_type == "zai":
            # ZhipuAI uses 'zai/' prefix in LiteLLM
            if not model.startswith("zai/"):
                return f"zai/{model}"

        return model

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
                    "Resp",
                    (),
                    {"data": [type("D", (), {"embedding": [0.0] * self._embedding_dim})]},
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

        # Get model name in LiteLLM format
        model = self._get_litellm_model_name()

        # Call LiteLLM embedding
        try:
            embedding_kwargs: dict[str, Any] = {
                "model": model,
                "input": texts,
            }
            # Pass api_key directly (no env var pollution)
            if self._api_key:
                embedding_kwargs["api_key"] = self._api_key
            # Add api_base for custom base URL (supports proxy/self-hosted scenarios)
            if self._base_url:
                embedding_kwargs["api_base"] = self._base_url

            response = await litellm.aembedding(**embedding_kwargs)

            # Extract embedding
            if not response.data or not response.data[0].embedding:
                raise ValueError("No embedding returned")

            embedding = response.data[0].embedding

            # Update detected dimension if different
            if len(embedding) != self._embedding_dim:
                logger.info(
                    f"Embedding dimension mismatch: expected {self._embedding_dim}, "
                    f"got {len(embedding)}. Updating."
                )
                self._embedding_dim = len(embedding)

            logger.debug(
                f"Created embedding: model={model}, "
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
                    "Resp",
                    (),
                    {"data": [type("D", (), {"embedding": [0.0] * self._embedding_dim})]},
                )()

            litellm.aembedding = _noop_aembedding

        if not input_data_list:
            return []

        # Get model name in LiteLLM format
        model = self._get_litellm_model_name()

        # Call LiteLLM embedding with batch
        try:
            batch_kwargs: dict[str, Any] = {
                "model": model,
                "input": input_data_list,
            }
            if self._api_key:
                batch_kwargs["api_key"] = self._api_key
            if self._base_url:
                batch_kwargs["api_base"] = self._base_url

            response = await litellm.aembedding(**batch_kwargs)

            embeddings = [item.embedding for item in response.data]

            logger.debug(
                f"Created batch embeddings: model={model}, "
                f"count={len(embeddings)}, dim={len(embeddings[0]) if embeddings else 0}"
            )

            return embeddings

        except Exception as e:
            logger.error(f"LiteLLM batch embedding error: {e}")
            raise


def create_litellm_embedder(
    provider_config: ProviderConfig,
    embedding_dim: Optional[int] = None,
) -> LiteLLMEmbedder:
    """
    Factory function to create LiteLLM embedder from provider configuration.

    Args:
        provider_config: Provider configuration
        embedding_dim: Override embedding dimension (auto-detected if not provided)

    Returns:
        Configured LiteLLMEmbedder instance
    """
    return LiteLLMEmbedder(
        config=provider_config,
        embedding_dim=embedding_dim,
    )
