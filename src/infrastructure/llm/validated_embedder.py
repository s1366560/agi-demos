"""
Validated Embedder Wrapper

This module provides a wrapper around embedder implementations that validates
and corrects embedding dimensions to ensure consistency.

This is critical for preventing dimension mismatches that cause Neo4j
vector.similarity.cosine() operations to fail.
"""

import contextlib
import logging
from dataclasses import dataclass

from src.domain.llm_providers.llm_types import EmbedderClient

logger = logging.getLogger(__name__)


@dataclass
class EmbedderConfig:
    """Configuration for validated embedder."""

    embedding_dim: int = 1024
    embedding_model: str | None = None


class ValidatedEmbedder(EmbedderClient):
    """
    Wrapper around embedder implementations that validates embedding dimensions.

    This wrapper ensures that all embeddings returned by the base embedder
    have the expected dimension, automatically padding or truncating as needed.
    This prevents Neo4j vector similarity errors when dimensions don't match.
    """

    def __init__(self, base_embedder: EmbedderClient, config: EmbedderConfig) -> None:
        """
        Initialize the validated embedder wrapper.

        Args:
            base_embedder: The underlying embedder implementation
            config: Embedder configuration with expected embedding_dim
        """
        # Store the base embedder's config
        self._base_config = config
        self._base_embedder = base_embedder

        # Get expected dimension from config
        self._embedding_dim = config.embedding_dim

        # Copy all attributes from base embedder to this wrapper
        # This allows the wrapper to be used as a drop-in replacement
        for attr in dir(base_embedder):
            if not attr.startswith("_") and callable(getattr(base_embedder, attr)):
                # Don't override wrapper's own methods
                if not hasattr(self, attr) or attr == "embedding_dim":
                    with contextlib.suppress(AttributeError, TypeError):
                        setattr(self, attr, getattr(base_embedder, attr))

    @property
    def embedding_dim(self) -> int:
        """Get the expected embedding dimension."""
        return self._embedding_dim

    @property
    def config(self) -> EmbedderConfig:  # type: ignore[override]
        """Get the embedder configuration."""
        return self._base_config

    async def create(  # type: ignore[override]
        self, input_data: str | list[str] | list[int] | list[list[int]]
    ) -> list[float]:
        """
        Create embedding with dimension validation.

        Validates the returned embedding has the expected dimension,
        padding or truncating as needed.

        Args:
            input_data: Text or list of texts to embed

        Returns:
            Embedding vector with guaranteed correct dimension
        """
        # Convert single string to list for embedder
        input_list = [input_data] if isinstance(input_data, str) else input_data
        raw_embedding = await self._base_embedder.create(input_list)  # type: ignore[arg-type]

        # Validate and fix dimension
        embedding = self._validate_and_fix_dimension(raw_embedding, input_data)  # type: ignore[arg-type]

        return embedding

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """
        Create embeddings for batch of texts with dimension validation.

        Args:
            input_data_list: List of texts to embed

        Returns:
            List of embedding vectors with guaranteed correct dimension
        """
        embeddings = await self._base_embedder.create_batch(input_data_list)  # type: ignore[attr-defined]

        # Validate and fix each embedding
        validated_embeddings = []
        for i, embedding in enumerate(embeddings):
            validated = self._validate_and_fix_dimension(
                embedding, input_data_list[i] if i < len(input_data_list) else f"batch[{i}]"
            )
            validated_embeddings.append(validated)

        return validated_embeddings

    def _validate_and_fix_dimension(
        self, embedding: list[float], input_context: str
    ) -> list[float]:
        """
        Validate and fix embedding dimension.

        Args:
            embedding: The embedding vector to validate
            input_context: Context string for logging (e.g., the input text)

        Returns:
            Embedding with correct dimension (padded or truncated)
        """
        if not embedding:
            logger.warning("[ValidatedEmbedder] Empty embedding returned, using zero vector")
            return [0.0] * self._embedding_dim

        actual_dim = len(embedding)
        expected_dim = self._embedding_dim

        if actual_dim == expected_dim:
            return embedding

        # Dimension mismatch detected
        logger.warning(
            f"[ValidatedEmbedder] Dimension mismatch detected!\n"
            f"  Expected: {expected_dim}D\n"
            f"  Got: {actual_dim}D\n"
            f"  Provider: {self._base_embedder.__class__.__name__}\n"
            f"  Input context: {str(input_context)[:50]}...\n"
            f"  Action: {'Truncating' if actual_dim > expected_dim else 'Padding'} to {expected_dim}D"
        )

        if actual_dim > expected_dim:
            # Truncate to expected dimension
            return embedding[:expected_dim]
        else:
            # Pad with zeros to expected dimension
            return embedding + [0.0] * (expected_dim - actual_dim)


def create_validated_embedder(
    base_embedder: EmbedderClient, config: EmbedderConfig
) -> ValidatedEmbedder:
    """
    Factory function to create a validated embedder wrapper.

    Args:
        base_embedder: The underlying embedder implementation
        config: Embedder configuration

    Returns:
        ValidatedEmbedder instance wrapping the base embedder
    """
    return ValidatedEmbedder(base_embedder=base_embedder, config=config)
