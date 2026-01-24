"""
Deepseek Native SDK Implementation.

Deepseek provides an OpenAI-compatible API.
Documentation: https://platform.deepseek.com/api-docs/
Base URL: https://api.deepseek.com/v1
"""

import json
import logging
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel

from src.domain.llm_providers.base import BaseLLMClient
from src.domain.llm_providers.llm_types import (
    DEFAULT_MAX_TOKENS,
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
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_SMALL_MODEL = "deepseek-coder"
DEFAULT_EMBEDDING_MODEL = "text-embedding-v3"  # Use Qwen as fallback
DEFAULT_RERANKER_MODEL = "deepseek-chat"

# Deepseek API endpoint
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


class DeepseekClient(LLMClient, BaseLLMClient):
    """
    Deepseek LLM client using OpenAI-compatible API.

    Deepseek API documentation: https://platform.deepseek.com/api-docs/

    This implementation uses the OpenAI SDK with Deepseek's base URL.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
        cache: bool = False,
    ):
        """
        Initialize Deepseek client.

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
            temperature=0,
        )

        # Initialize parent class
        super().__init__(config, cache)

        # Create OpenAI client with Deepseek endpoint
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_config.base_url or DEEPSEEK_BASE_URL,
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
        return "deepseek"

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: Optional[type[BaseModel]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """
        Generate response using Deepseek API.

        Args:
            messages: List of messages
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens in response
            model_size: Which model to use
            retry_count: Current retry attempt

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

        # Add structured output if requested (Deepseek supports JSON mode)
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
                    if retry_count < 2:
                        # Retry with feedback
                        messages.append(Message(role="assistant", content=content))
                        messages.append(
                            Message(role="user", content="Please return valid JSON only.")
                        )
                        return await self._generate_response(
                            messages, response_model, max_tokens, model_size, retry_count + 1
                        )
                    raise

            return {"content": content}

        except Exception as e:
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ["rate limit", "429", "quota"]):
                raise RateLimitError(f"Rate limit error: {e}")
            logger.error(f"Deepseek API error: {e}")
            raise


class DeepseekEmbedder(EmbedderClient):
    """
    Deepseek Embedder - Fallback implementation.

    Note: Deepseek does not provide an embedding API.
    This implementation uses Qwen's embedding API as a fallback.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
        fallback_provider_config: Optional[ProviderConfig] = None,
        embedding_dim: int = 1024,
    ):
        """
        Initialize Deepseek embedder with fallback.

        Args:
            provider_config: Deepseek provider configuration
            fallback_provider_config: Config for fallback embedder (e.g., Qwen)
            embedding_dim: Dimension of embedding vectors
        """
        self.provider_config = provider_config
        self.fallback_provider_config = fallback_provider_config
        self._embedding_dim = embedding_dim

        # Import Qwen embedder as fallback
        if fallback_provider_config:
            from src.infrastructure.llm.qwen.qwen_embedder import QwenEmbedder

            self.fallback_embedder = QwenEmbedder(
                config=fallback_provider_config,
                embedding_dim=embedding_dim,
            )
            logger.info("Using Qwen embedder as fallback for Deepseek")
        else:
            self.fallback_embedder = None
            logger.warning("No fallback embedder configured for Deepseek")

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        return self._embedding_dim

    async def create(
        self,
        input_data: str | list[str],
    ) -> list[float]:
        """
        Create embedding using fallback provider.

        Args:
            input_data: Text or list of texts to embed

        Returns:
            Embedding vector as list of floats
        """
        if not self.fallback_embedder:
            raise ValueError(
                "Deepseek does not provide embedding API. "
                "Please configure a fallback provider (e.g., Qwen)."
            )
        return await self.fallback_embedder.create(input_data)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        """
        Create embeddings using fallback provider.

        Args:
            input_data_list: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not self.fallback_embedder:
            raise ValueError(
                "Deepseek does not provide embedding API. "
                "Please configure a fallback provider (e.g., Qwen)."
            )
        return await self.fallback_embedder.create_batch(input_data_list)


class DeepseekReranker(CrossEncoderClient):
    """
    Deepseek Reranker using LLM-based scoring.

    Since Deepseek doesn't have a dedicated reranker API,
    we use LLM-based scoring similar to other providers.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
    ):
        """
        Initialize Deepseek reranker.

        Args:
            provider_config: Provider configuration with encrypted API key
        """
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()

        # Decrypt API key
        api_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Create OpenAI client with Deepseek endpoint
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=provider_config.base_url or DEEPSEEK_BASE_URL,
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
            scores, _ = self._parse_rerank_response(content, len(passages))

            # Combine passages with scores
            passage_scores = list(zip(passages, scores))
            passage_scores.sort(key=lambda x: x[1], reverse=True)

            if top_n:
                passage_scores = passage_scores[:top_n]

            return passage_scores

        except Exception as e:
            logger.error(f"Deepseek reranking error: {e}")
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

    def _parse_rerank_response(
        self, response: str, expected_count: int
    ) -> tuple[list[float], bool]:
        """
        Parse LLM response into scores.

        Args:
            response: LLM response string (JSON)
            expected_count: Expected number of scores

        Returns:
            Tuple of (scores list, whether padding was needed)
        """
        try:
            # Clean markdown code blocks if present
            cleaned_response = response.strip()
            if cleaned_response.startswith("```"):
                lines = cleaned_response.split("\n")
                lines = lines[1:]
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == "```":
                        lines = lines[:i]
                        break
                cleaned_response = "\n".join(lines).strip()

            # Parse JSON
            data = json.loads(cleaned_response)

            # Handle different response formats
            if isinstance(data, dict):
                if "scores" in data:
                    scores = data["scores"]
                elif "score" in data:
                    scores = data["score"]
                else:
                    raise ValueError("No scores found in response")
            elif isinstance(data, list):
                scores = data
            else:
                raise ValueError(f"Unexpected response format: {type(data)}")

            # Validate and normalize scores
            padded = False
            if len(scores) != expected_count:
                logger.warning(
                    f"Expected {expected_count} scores, got {len(scores)}. Padding or truncating..."
                )
                while len(scores) < expected_count:
                    scores.append(0.5)
                scores = scores[:expected_count]
                padded = True

            normalized_scores = []
            for score in scores:
                try:
                    score_float = float(score)
                except (ValueError, TypeError):
                    score_float = 0.5
                score_float = max(0.0, min(1.0, score_float))
                normalized_scores.append(score_float)

            return normalized_scores, padded

        except Exception as e:
            logger.error(f"Failed to parse rerank response: {e}")
            return [0.5] * expected_count, True
