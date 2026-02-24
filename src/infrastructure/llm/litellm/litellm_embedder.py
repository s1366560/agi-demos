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
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from src.configuration.config import get_settings
from src.domain.llm_providers.base import BaseEmbedder
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.provider_credentials import from_decrypted_api_key
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
    # Local providers
    "nomic-embed-text": 768,
    "text-embedding-nomic-embed-text-v1.5": 768,
}

# Default models by provider
DEFAULT_EMBEDDING_MODELS = {
    ProviderType.OPENAI: "text-embedding-3-small",
    ProviderType.ANTHROPIC: "text-embedding-3-small",  # Uses OpenAI
    ProviderType.GEMINI: "text-embedding-004",
    ProviderType.DASHSCOPE: "text-embedding-v3",
    ProviderType.KIMI: "kimi-embedding-1",
    ProviderType.DEEPSEEK: "text-embedding-v3",  # Uses Dashscope fallback
    ProviderType.MINIMAX: "embo-01",
    ProviderType.ZAI: "embedding-3",
    ProviderType.COHERE: "embed-english-v3.0",
    ProviderType.MISTRAL: "mistral-embed",
    ProviderType.AZURE_OPENAI: "text-embedding-3-small",
    ProviderType.BEDROCK: "amazon.titan-embed-text-v1",
    ProviderType.VERTEX: "textembedding-gecko",
    ProviderType.GROQ: "text-embedding-3-small",  # Uses OpenAI
    ProviderType.OLLAMA: "nomic-embed-text",
    ProviderType.LMSTUDIO: "text-embedding-nomic-embed-text-v1.5",
}

RESERVED_EMBEDDING_KWARGS = {
    "model",
    "input",
    "timeout",
    "api_key",
    "api_base",
    "encoding_format",
    "dimensions",
    "user",
}


@dataclass
class LiteLLMEmbedderConfig:
    """Configuration for LiteLLM Embedder."""

    embedding_model: str
    embedding_dim: int | None = None
    dimensions: int | None = None
    encoding_format: str | None = None
    user: str | None = None
    timeout: float | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    api_key: str | None = None
    base_url: str | None = None
    provider_type: ProviderType | None = None


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
        embedding_dim: int | None = None,
    ) -> None:
        """
        Initialize LiteLLM embedder.

        Args:
            config: Provider configuration or embedder config
            embedding_dim: Override embedding dimension (auto-detected if not provided)
        """
        self._dimensions_override: int | None = None
        self._encoding_format: str | None = None
        self._embedding_user: str | None = None
        self._provider_options: dict[str, Any] = {}
        timeout_override: float | None = None

        if isinstance(config, LiteLLMEmbedderConfig):
            self._embedding_model = config.embedding_model
            self._dimensions_override = self._normalize_optional_int(config.dimensions)
            configured_dim = embedding_dim or config.embedding_dim or self._dimensions_override
            self._embedding_dim = configured_dim or self._detect_embedding_dim(
                self._embedding_model
            )
            self._encoding_format = self._normalize_encoding_format(config.encoding_format)
            self._embedding_user = self._normalize_optional_str(config.user)
            self._provider_options = self._normalize_provider_options(config.provider_options)
            timeout_override = self._normalize_optional_float(config.timeout)
            self._api_key = config.api_key
            self._provider_type = config.provider_type
            self._base_url = self._resolve_api_base(self._provider_type, config.base_url)
        else:
            self._provider_config = config
            embedding_cfg = self._get_embedding_config_payload(config)
            configured_model = self._normalize_optional_str(embedding_cfg.get("model"))
            self._embedding_model = (
                configured_model
                or config.embedding_model
                or self._get_default_model(config.provider_type)
            )
            self._dimensions_override = self._normalize_optional_int(
                embedding_cfg.get("dimensions")
            )
            self._embedding_dim = (
                embedding_dim
                or self._dimensions_override
                or self._detect_embedding_dim(self._embedding_model)
            )
            self._encoding_format = self._normalize_encoding_format(
                embedding_cfg.get("encoding_format")
            )
            self._embedding_user = self._normalize_optional_str(embedding_cfg.get("user"))
            self._provider_options = self._normalize_provider_options(
                embedding_cfg.get("provider_options")
            )
            timeout_override = self._normalize_optional_float(embedding_cfg.get("timeout"))
            self._provider_type = config.provider_type
            self._base_url = self._resolve_api_base(self._provider_type, config.base_url)

            # Decrypt API key
            encryption_service = get_encryption_service()
            self._api_key = encryption_service.decrypt(config.api_key_encrypted)
            self._api_key = from_decrypted_api_key(self._api_key)

        self._timeout_seconds = timeout_override or float(get_settings().llm_timeout)

        logger.debug(
            f"LiteLLM embedder initialized: provider={self._provider_type}, "
            f"model={self._embedding_model}, dim={self._embedding_dim}, "
            f"dimensions_override={self._dimensions_override}"
        )

    @staticmethod
    def _normalize_optional_str(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _normalize_optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _normalize_provider_options(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _normalize_encoding_format(cls, value: Any) -> str | None:
        normalized = cls._normalize_optional_str(value)
        if normalized in {"float", "base64"}:
            return normalized
        return None

    def _get_embedding_config_payload(self, provider_config: ProviderConfig) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        embedding_config = getattr(provider_config, "embedding_config", None)
        if embedding_config is not None:
            if hasattr(embedding_config, "model_dump"):
                payload = embedding_config.model_dump(exclude_none=True)
            elif isinstance(embedding_config, dict):
                payload = dict(embedding_config)

        raw_config = provider_config.config if isinstance(provider_config.config, dict) else {}
        raw_embedding = raw_config.get("embedding")
        if isinstance(raw_embedding, dict):
            payload = {**raw_embedding, **payload}

        if provider_config.embedding_model and not payload.get("model"):
            payload["model"] = provider_config.embedding_model

        return payload

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

    @staticmethod
    def _resolve_api_base(provider_type: ProviderType | None, base_url: str | None) -> str | None:
        """Resolve api_base using configured value or local-provider defaults."""
        if base_url:
            return base_url
        if provider_type == ProviderType.OLLAMA:
            return "http://localhost:11434"
        if provider_type == ProviderType.LMSTUDIO:
            return "http://localhost:1234/v1"
        return None

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dim

    def _configure_litellm(self) -> None:
        """No-op. Kept for backward compatibility.

        API key is now passed per-request via the ``api_key`` parameter to
        ``litellm.aembedding()`` instead of polluting ``os.environ``.
        """

    def _apply_embedding_options(self, request_kwargs: dict[str, Any]) -> None:
        """Apply structured embedding options to LiteLLM request kwargs."""
        if self._dimensions_override is not None:
            request_kwargs["dimensions"] = self._dimensions_override

        if self._encoding_format:
            request_kwargs["encoding_format"] = self._encoding_format
        elif self._provider_type == ProviderType.DASHSCOPE:
            # Dashscope embedding endpoint validates encoding_format strictly.
            request_kwargs["encoding_format"] = "float"

        if self._embedding_user:
            request_kwargs["user"] = self._embedding_user

        for key, value in self._provider_options.items():
            if key in RESERVED_EMBEDDING_KWARGS:
                logger.warning("Ignoring reserved embedding provider option: %s", key)
                continue
            request_kwargs[key] = value

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
        elif provider_type == "dashscope":
            # Dashscope uses OpenAI-compatible API
            if not model.startswith("openai/"):
                return f"openai/{model}"
        elif provider_type == "kimi":
            # Kimi uses OpenAI-compatible API
            if not model.startswith("openai/"):
                return f"openai/{model}"
        elif provider_type == "minimax":
            if not model.startswith("minimax/"):
                return f"minimax/{model}"
        elif provider_type == "zai":
            # ZhipuAI embedding API is OpenAI-compatible.
            if not model.startswith("openai/"):
                return f"openai/{model}"
        elif provider_type == "ollama":
            if not model.startswith("ollama/"):
                return f"ollama/{model}"
        elif provider_type == "lmstudio":
            if not model.startswith("openai/"):
                return f"openai/{model}"

        return model

    async def create(
        self,
        input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]],
    ) -> list[float]:
        """
        Create embeddings using LiteLLM.

        Args:
            input_data: Text(s) to embed

        Returns:
            Embedding vector as list of floats
        """
        import litellm

        if not hasattr(litellm, "aembedding"):

            async def _noop_aembedding(**kwargs: Any) -> None:
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
                "timeout": self._timeout_seconds,
            }
            # Pass api_key directly (no env var pollution)
            if self._api_key:
                embedding_kwargs["api_key"] = self._api_key
            # Add api_base for custom base URL (supports proxy/self-hosted scenarios)
            if self._base_url:
                embedding_kwargs["api_base"] = self._base_url
            self._apply_embedding_options(embedding_kwargs)

            response = await litellm.aembedding(**embedding_kwargs)

            # Extract embedding
            if not response.data:
                raise ValueError("No embedding returned")

            first_item = response.data[0]
            if isinstance(first_item, dict):
                embedding = first_item.get("embedding")
            else:
                embedding = getattr(first_item, "embedding", None)
            if not embedding:
                raise ValueError("No embedding returned")

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

    async def create_batch(
        self,
        input_data_list: list[str],
        batch_size: int = 128,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> list[list[float]]:
        """
        Create embeddings for multiple texts with batch processing.

        Optimizations:
        - Splits large batches into smaller chunks to avoid API limits
        - Automatic retries with exponential backoff
        - Progress logging for large batches
        - Graceful degradation on partial failures

        Args:
            input_data_list: List of texts to embed
            batch_size: Maximum texts per API call (default 128)
            max_retries: Maximum retry attempts per batch
            retry_delay: Initial delay between retries in seconds

        Returns:
            List of embedding vectors

        Example:
            embeddings = await embedder.create_batch(texts, batch_size=64)
        """
        import asyncio

        import litellm

        if not hasattr(litellm, "aembedding"):

            async def _noop_aembedding(**kwargs: Any) -> None:
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

        # Split into batches
        batches = [
            input_data_list[i : i + batch_size] for i in range(0, len(input_data_list), batch_size)
        ]

        all_embeddings: list[list[float]] = []
        total_batches = len(batches)

        for batch_idx, batch in enumerate(batches, 1):
            retry_count = 0
            current_delay = retry_delay

            while retry_count <= max_retries:
                try:
                    batch_kwargs: dict[str, Any] = {
                        "model": model,
                        "input": batch,
                        "timeout": self._timeout_seconds,
                    }
                    if self._api_key:
                        batch_kwargs["api_key"] = self._api_key
                    if self._base_url:
                        batch_kwargs["api_base"] = self._base_url
                    self._apply_embedding_options(batch_kwargs)

                    response = await litellm.aembedding(**batch_kwargs)

                    # Extract embeddings
                    batch_embeddings = []
                    for item in response.data:
                        if isinstance(item, dict):
                            embedding = item.get("embedding")
                        else:
                            embedding = getattr(item, "embedding", None)
                        if not embedding:
                            raise ValueError("No embedding returned for item")
                        batch_embeddings.append(embedding)

                    all_embeddings.extend(batch_embeddings)

                    logger.debug(
                        f"Batch {batch_idx}/{total_batches} embeddings created: "
                        f"model={model}, count={len(batch_embeddings)}"
                    )

                    break  # Success, exit retry loop

                except Exception as e:
                    retry_count += 1
                    error_msg = str(e).lower()

                    # Check if rate limit error
                    is_rate_limit = any(
                        kw in error_msg for kw in ["rate limit", "quota", "429", "throttling"]
                    )

                    if retry_count > max_retries:
                        logger.error(
                            f"Batch {batch_idx}/{total_batches} embedding failed after "
                            f"{max_retries} retries: {e}"
                        )
                        # Return partial results instead of failing completely
                        # Fill remaining slots with zero vectors
                        remaining = len(batch) - (
                            len(all_embeddings) % batch_size if all_embeddings else 0
                        )
                        zero_embeddings = [[0.0] * self._embedding_dim] * remaining
                        all_embeddings.extend(zero_embeddings)
                        break

                    if is_rate_limit:
                        # Exponential backoff for rate limits
                        wait_time = current_delay * (2 ** (retry_count - 1))
                        logger.warning(
                            f"Rate limit hit for batch {batch_idx}/{total_batches}, "
                            f"retrying in {wait_time:.1f}s (attempt {retry_count}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                        current_delay *= 2
                    else:
                        # For other errors, retry immediately
                        logger.warning(
                            f"Batch {batch_idx}/{total_batches} embedding error (attempt "
                            f"{retry_count}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(current_delay)

        logger.info(
            f"Completed batch embeddings: model={model}, "
            f"total={len(all_embeddings)}, batches={total_batches}"
        )

        return all_embeddings


def create_litellm_embedder(
    provider_config: ProviderConfig,
    embedding_dim: int | None = None,
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
