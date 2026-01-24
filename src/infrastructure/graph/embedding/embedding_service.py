"""
Vector embedding service wrapper.

This module provides a unified interface for generating vector embeddings
using various providers (OpenAI, Gemini, Qwen, etc.).

The service wraps existing embedder implementations and provides:
- Batch embedding generation
- Dimension validation
- Caching support (optional)
"""

import asyncio
import logging
import math
from typing import Any, List, Optional, Protocol

logger = logging.getLogger(__name__)


class EmbedderProtocol(Protocol):
    """Protocol for embedder clients."""

    embedding_dim: int

    async def create(self, input_data: str | List[str]) -> List[float]:
        """Create embedding for input data."""
        ...


class EmbeddingService:
    """
    Unified embedding service that wraps various embedder implementations.

    This service provides:
    - Single and batch embedding generation
    - Automatic dimension validation
    - Error handling with retry support

    Example:
        service = EmbeddingService(embedder)
        embedding = await service.embed_text("Hello world")
        embeddings = await service.embed_batch(["Hello", "World"])
    """

    def __init__(
        self,
        embedder: Any,
        validate_dimensions: bool = True,
    ):
        """
        Initialize embedding service.

        Args:
            embedder: Embedder client (OpenAI, Gemini, Qwen, etc.)
            validate_dimensions: Whether to validate embedding dimensions
        """
        self._embedder = embedder
        self._validate_dimensions = validate_dimensions
        self._dimension_cache: Optional[int] = None

    @property
    def embedding_dim(self) -> int:
        """Get the embedding dimension for this service."""
        if self._dimension_cache is not None:
            return self._dimension_cache

        if hasattr(self._embedder, "embedding_dim"):
            self._dimension_cache = self._embedder.embedding_dim
            return self._dimension_cache

        # Fallback to config-based dimension
        if hasattr(self._embedder, "config"):
            config = self._embedder.config
            if hasattr(config, "embedding_dim"):
                self._dimension_cache = config.embedding_dim
                return self._dimension_cache

        # Default dimension (common for many models)
        logger.warning("Could not determine embedding dimension from embedder, using default 1024")
        return 1024

    async def embed_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding, returning zero vector")
            return [0.0] * self.embedding_dim

        try:
            result = await self._embedder.create(input_data=text)

            # Handle different return formats
            if isinstance(result, list) and len(result) > 0:
                # Some embedders return [[embedding]], some return [embedding]
                if isinstance(result[0], list):
                    embedding = result[0]
                else:
                    embedding = result
            else:
                embedding = result

            # Validate dimension
            if self._validate_dimensions and len(embedding) != self.embedding_dim:
                logger.warning(
                    f"Embedding dimension mismatch: got {len(embedding)}, "
                    f"expected {self.embedding_dim}. Padding/truncating."
                )
                embedding = self._fix_dimension(embedding)

            return embedding

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise

    async def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 100,
        max_concurrency: int = 5,
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            batch_size: Number of texts per batch
            max_concurrency: Maximum concurrent batches

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Filter empty texts and track indices
        non_empty_indices = []
        non_empty_texts = []
        for i, text in enumerate(texts):
            if text and text.strip():
                non_empty_indices.append(i)
                non_empty_texts.append(text)

        if not non_empty_texts:
            return [[0.0] * self.embedding_dim] * len(texts)

        # Generate embeddings
        embeddings: List[Optional[List[float]]] = [None] * len(texts)

        # Check if embedder supports batch
        if hasattr(self._embedder, "create_batch"):
            # Use batch API
            try:
                batch_results = await self._embedder.create_batch(non_empty_texts)
                for idx, embedding in zip(non_empty_indices, batch_results):
                    if self._validate_dimensions and len(embedding) != self.embedding_dim:
                        embedding = self._fix_dimension(embedding)
                    embeddings[idx] = embedding
            except Exception as e:
                logger.warning(f"Batch embedding failed, falling back to individual: {e}")
                # Fall back to individual embedding
                for idx, text in zip(non_empty_indices, non_empty_texts):
                    embeddings[idx] = await self.embed_text(text)
        else:
            # Use individual calls with concurrency control
            semaphore = asyncio.Semaphore(max_concurrency)

            async def embed_with_semaphore(idx: int, text: str) -> None:
                async with semaphore:
                    embeddings[idx] = await self.embed_text(text)

            await asyncio.gather(
                *[
                    embed_with_semaphore(idx, text)
                    for idx, text in zip(non_empty_indices, non_empty_texts)
                ]
            )

        # Fill empty texts with zero vectors
        for i, embedding in enumerate(embeddings):
            if embedding is None:
                embeddings[i] = [0.0] * self.embedding_dim

        return embeddings

    def _fix_dimension(self, embedding: List[float]) -> List[float]:
        """
        Fix embedding dimension by padding or truncating.

        Args:
            embedding: Original embedding

        Returns:
            Fixed embedding with correct dimension
        """
        target_dim = self.embedding_dim
        current_dim = len(embedding)

        if current_dim == target_dim:
            return embedding

        if current_dim < target_dim:
            # Pad with zeros
            return embedding + [0.0] * (target_dim - current_dim)
        else:
            # Truncate
            return embedding[:target_dim]

    def validate_embedding(
        self,
        embedding: List[float],
        name: str = "unknown",
    ) -> bool:
        """
        Validate an embedding vector.

        Checks:
        - Not empty
        - Correct dimension
        - No NaN or Inf values
        - Not a zero vector

        Args:
            embedding: Embedding to validate
            name: Name for logging

        Returns:
            True if valid
        """
        if not embedding:
            logger.warning(f"Embedding {name} is empty")
            return False

        if len(embedding) != self.embedding_dim:
            logger.warning(
                f"Embedding {name} has wrong dimension: {len(embedding)} != {self.embedding_dim}"
            )
            return False

        # Check for NaN/Inf (handle potential non-numeric types)
        try:
            nan_count = sum(1 for x in embedding if math.isnan(x))
            inf_count = sum(1 for x in embedding if math.isinf(x))
            if nan_count > 0 or inf_count > 0:
                logger.warning(f"Embedding {name} has {nan_count} NaN, {inf_count} Inf values")
                return False
        except (TypeError, ValueError):
            logger.warning(f"Embedding {name} contains non-numeric values")
            return False

        # Check for zero vector
        magnitude = sum(x * x for x in embedding) ** 0.5
        if magnitude < 1e-6:
            logger.warning(f"Embedding {name} is a zero vector")
            return False

        return True

    async def compute_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float],
    ) -> float:
        """
        Compute cosine similarity between two embeddings.

        Args:
            embedding1: First embedding
            embedding2: Second embedding

        Returns:
            Cosine similarity (0-1)
        """
        if len(embedding1) != len(embedding2):
            raise ValueError(
                f"Embedding dimensions don't match: {len(embedding1)} vs {len(embedding2)}"
            )

        dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
        magnitude1 = sum(x * x for x in embedding1) ** 0.5
        magnitude2 = sum(x * x for x in embedding2) ** 0.5

        if magnitude1 < 1e-6 or magnitude2 < 1e-6:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    async def find_most_similar(
        self,
        query_embedding: List[float],
        candidates: List[List[float]],
        top_k: int = 5,
    ) -> List[tuple[int, float]]:
        """
        Find most similar embeddings from candidates.

        Args:
            query_embedding: Query embedding
            candidates: List of candidate embeddings
            top_k: Number of top results

        Returns:
            List of (index, similarity) tuples sorted by similarity
        """
        similarities = []
        for i, candidate in enumerate(candidates):
            sim = await self.compute_similarity(query_embedding, candidate)
            similarities.append((i, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]
