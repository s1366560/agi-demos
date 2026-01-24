"""
OpenAI Native SDK Implementation.

Uses the official OpenAI SDK (openai>=1.77.0) for LLM, embedding, and reranking.
"""

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel

from openai import AsyncOpenAI
from src.domain.llm_providers.base import (
    BaseEmbedder,
    BaseLLMClient,
    BaseReranker,
)
from src.domain.llm_providers.llm_types import (
    CrossEncoderClient,
    EmbedderClient,
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
    RateLimitError,
)
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)

# Default models
DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_SMALL_MODEL = "gpt-4.1-nano"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_RERANKER_MODEL = "gpt-4.1-nano"


class OpenAILLMWrapper(LLMClient, BaseLLMClient):
    """
    OpenAI LLM client with ProviderConfig support.

    Uses the official OpenAI SDK for direct API communication.
    Supports all OpenAI models including GPT-5 reasoning models.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
        cache: bool = False,
    ):
        """
        Initialize OpenAI LLM wrapper.

        Args:
            provider_config: Provider configuration with encrypted API key
            cache: Enable response caching
        """
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()

        # Decrypt API key
        api_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Create LLM config
        config = LLMConfig(
            api_key=api_key,
            model=provider_config.llm_model or DEFAULT_MODEL,
            small_model=provider_config.llm_small_model or DEFAULT_SMALL_MODEL,
            base_url=provider_config.base_url,
            temperature=0,
        )

        # Initialize parent class
        super().__init__(config, cache)

        # Create OpenAI client with custom base URL if provided
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_config.base_url,
        )

        # Store models
        self.model = config.model
        self.small_model = config.small_model or config.model

    def _get_model_for_size(self, model_size: ModelSize) -> str:
        """Get model name for requested size."""
        if model_size == ModelSize.small:
            return self.small_model
        return self.model

    def _get_provider_type(self) -> str:
        """Return provider type identifier."""
        return "openai"

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: Optional[type[BaseModel]] = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        """
        Generate response from OpenAI.

        Args:
            messages: List of messages
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens in response
            model_size: Which model to use

        Returns:
            Dictionary with response content or parsed structured data
        """
        model = self._get_model_for_size(model_size)

        # Convert messages to OpenAI format
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        # Prepare request
        kwargs = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature or 0,
        }

        # Add structured output if requested (OpenAI supports JSON mode)
        if response_model:
            kwargs["response_format"] = {"type": "json_object"}
            # Add JSON instruction to system message
            if api_messages and api_messages[0]["role"] == "system":
                api_messages[0]["content"] += " You must output valid JSON only."

        try:
            response = await self.client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content

            if not content:
                raise ValueError("Empty response content")

            # Parse structured output if needed
            if response_model:
                try:
                    # Clean markdown if present
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    elif content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()

                    parsed_data = json.loads(content)
                    validated = response_model.model_validate(parsed_data)
                    return validated.model_dump()
                except Exception as e:
                    logger.error(f"Failed to parse JSON: {e}")
                    raise

            return {"content": content}

        except Exception as e:
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ["rate limit", "429", "quota"]):
                raise RateLimitError(f"Rate limit error: {e}")
            logger.error(f"OpenAI API error: {e}")
            raise


class OpenAIEmbedderWrapper(EmbedderClient, BaseEmbedder):
    """
    OpenAI Embedder with ProviderConfig support.

    Uses the official OpenAI SDK for embedding generation.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
        embedding_dim: int = 1536,
    ):
        """
        Initialize OpenAI embedder wrapper.

        Args:
            provider_config: Provider configuration with encrypted API key
            embedding_dim: Dimension of embedding vectors (default: 1536 for text-embedding-3-small)
        """
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()
        self._embedding_dim = embedding_dim

        # Decrypt API key
        api_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Store config
        self.embedding_model = provider_config.embedding_model or DEFAULT_EMBEDDING_MODEL

        # Create OpenAI client
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_config.base_url,
        )

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dim

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
        """
        # Normalize input
        if isinstance(input_data, str):
            text = input_data
        elif isinstance(input_data, list) and len(input_data) > 0:
            text = input_data[0] if isinstance(input_data[0], str) else str(input_data[0])
        else:
            raise ValueError("Invalid input for embedding")

        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text,
            )

            embedding = response.data[0].embedding

            # Validate dimension
            if len(embedding) != self._embedding_dim:
                logger.warning(
                    f"[OpenAIEmbedder] Dimension mismatch! Expected {self._embedding_dim}D, "
                    f"got {len(embedding)}D. Adjusting."
                )
                if len(embedding) > self._embedding_dim:
                    embedding = embedding[: self._embedding_dim]
                else:
                    embedding = embedding + [0.0] * (self._embedding_dim - len(embedding))

            return embedding

        except Exception as e:
            logger.error(f"OpenAI embedding error: {e}")
            raise

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """
        Create embeddings for batch of texts.

        Args:
            input_data_list: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not input_data_list:
            return []

        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=input_data_list,
            )

            embeddings = [item.embedding for item in response.data]

            # Validate dimensions
            validated_embeddings = []
            for embedding in embeddings:
                if len(embedding) != self._embedding_dim:
                    logger.warning(
                        f"[OpenAIEmbedder] Batch dimension mismatch! "
                        f"Expected {self._embedding_dim}D, got {len(embedding)}D."
                    )
                    if len(embedding) > self._embedding_dim:
                        embedding = embedding[: self._embedding_dim]
                    else:
                        embedding = embedding + [0.0] * (self._embedding_dim - len(embedding))
                validated_embeddings.append(embedding)

            return validated_embeddings

        except Exception as e:
            logger.error(f"OpenAI batch embedding error: {e}")
            raise


class OpenAIRerankerWrapper(CrossEncoderClient, BaseReranker):
    """
    OpenAI Reranker with ProviderConfig support.

    Uses LLM-based scoring for relevance ranking.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
    ):
        """
        Initialize OpenAI reranker wrapper.

        Args:
            provider_config: Provider configuration with encrypted API key
        """
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()

        # Decrypt API key
        api_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Create OpenAI client
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_config.base_url,
        )

        self.model = provider_config.reranker_model or DEFAULT_RERANKER_MODEL

    async def rank(
        self,
        query: str,
        passages: list[str],
        top_n: Optional[int] = None,
    ) -> list[tuple[str, float]]:
        """
        Rank passages by relevance to query using LLM-based scoring.

        Args:
            query: Search query
            passages: List of passages to rank
            top_n: Optional limit on number of results

        Returns:
            List of (passage, score) tuples sorted by relevance (descending)
        """
        if not passages:
            return []

        if len(passages) == 1:
            return [(passages[0], 1.0)]

        # Build reranking prompt
        passages_text = "\n\n".join(
            [f"Passage {i}: {passage}" for i, passage in enumerate(passages)]
        )

        prompt = f"""Given the following query and passages, rate the relevance of each passage to the query on a scale from 0.0 to 1.0.

Query: {query}

Passages:
{passages_text}

Return a JSON object with a "scores" array containing the relevance scores for each passage in order. For example:
{{"scores": [0.95, 0.72, 0.34, 0.89]}}

Ensure:
- Scores are between 0.0 and 1.0
- The array has exactly {len(passages)} scores
- Scores reflect how well each passage answers the query
- Higher scores indicate better relevance
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a relevance scoring assistant. Rate how well each passage answers the query.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            scores = self._parse_scores(content, len(passages))

            # Combine passages with scores
            passage_scores = list(zip(passages, scores))
            passage_scores.sort(key=lambda x: x[1], reverse=True)

            if top_n:
                passage_scores = passage_scores[:top_n]

            return passage_scores

        except Exception as e:
            logger.error(f"OpenAI reranking error: {e}")
            # Fallback: return passages in original order with neutral scores
            return [(p, 0.5) for p in passages]

    async def score(self, query: str, passage: str) -> float:
        """
        Score single passage relevance to query.

        Args:
            query: Search query
            passage: Passage to score

        Returns:
            Relevance score in [0, 1] range
        """
        result = await self.rank(query, [passage])
        return result[0][1] if result else 0.5

    def _parse_scores(self, response: str, expected_count: int) -> list[float]:
        """
        Parse LLM response into scores.

        Args:
            response: LLM response string (JSON)
            expected_count: Expected number of scores

        Returns:
            List of normalized scores
        """
        try:
            # Clean markdown code blocks if present
            cleaned = response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = lines[1:]
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == "```":
                        lines = lines[:i]
                        break
                cleaned = "\n".join(lines).strip()

            # Parse JSON
            data = json.loads(cleaned)

            # Handle different response formats
            if isinstance(data, dict):
                if "scores" in data:
                    scores = data["scores"]
                elif "score" in data:
                    scores = data["score"]
                else:
                    scores = [0.5] * expected_count
            elif isinstance(data, list):
                scores = data
            else:
                scores = [0.5] * expected_count

            # Validate and normalize
            if len(scores) != expected_count:
                while len(scores) < expected_count:
                    scores.append(0.5)
                scores = scores[:expected_count]

            normalized = []
            for score in scores:
                try:
                    s = float(score)
                    s = max(0.0, min(1.0, s))
                except (ValueError, TypeError):
                    s = 0.5
                normalized.append(s)

            return normalized

        except Exception as e:
            logger.error(f"Failed to parse rerank scores: {e}")
            return [0.5] * expected_count
