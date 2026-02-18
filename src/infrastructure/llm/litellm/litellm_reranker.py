"""
LiteLLM Reranker Adapter for Knowledge Graph System

Implements BaseReranker interface using LiteLLM library.
Provides unified reranking across providers:
- Cohere: Uses native rerank API (best quality)
- Others: Uses LLM-based relevance scoring

Usage:
    provider_config = ProviderConfig(...)
    reranker = LiteLLMReranker(config=provider_config)
    ranked_passages = await reranker.rank(query, passages)
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from src.domain.llm_providers.base import BaseReranker
from src.domain.llm_providers.llm_types import RateLimitError
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


# Providers with native rerank API
NATIVE_RERANK_PROVIDERS = {
    ProviderType.COHERE,
}

# Default rerank models by provider
DEFAULT_RERANK_MODELS = {
    ProviderType.COHERE: "rerank-english-v3.0",
    ProviderType.OPENAI: "gpt-4o-mini",
    ProviderType.ANTHROPIC: "claude-3-5-haiku-20241022",
    ProviderType.GEMINI: "gemini-1.5-flash",
    ProviderType.QWEN: "qwen-turbo",
    ProviderType.DEEPSEEK: "deepseek-chat",
    ProviderType.ZAI: "glm-4-flash",
    ProviderType.MISTRAL: "mistral-small-latest",
}


@dataclass
class LiteLLMRerankerConfig:
    """Configuration for LiteLLM Reranker."""

    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    provider_type: Optional[ProviderType] = None


class LiteLLMReranker(BaseReranker):
    """
    LiteLLM-based implementation of BaseReranker.

    For Cohere, uses the native rerank API for best quality.
    For other providers, uses LLM-based relevance scoring.

    Usage:
        provider_config = ProviderConfig(...)
        reranker = LiteLLMReranker(config=provider_config)
        ranked_passages = await reranker.rank(query, passages)
    """

    def __init__(
        self,
        config: ProviderConfig | LiteLLMRerankerConfig,
    ):
        """
        Initialize LiteLLM reranker.

        Args:
            config: Provider configuration or reranker config
        """
        if isinstance(config, LiteLLMRerankerConfig):
            self._model = config.model
            self._api_key = config.api_key
            self._base_url = config.base_url
            self._provider_type = config.provider_type
        else:
            self._provider_config = config
            self._provider_type = config.provider_type
            self._model = config.reranker_model or self._get_default_model(config.provider_type)
            self._base_url = config.base_url

            # Decrypt API key
            encryption_service = get_encryption_service()
            self._api_key = encryption_service.decrypt(config.api_key_encrypted)

        self._use_native_rerank = self._provider_type in NATIVE_RERANK_PROVIDERS

        logger.debug(
            f"LiteLLM reranker initialized: provider={self._provider_type}, "
            f"model={self._model}, native={self._use_native_rerank}"
        )

    def _get_default_model(self, provider_type: ProviderType) -> str:
        """Get default rerank model for provider."""
        return DEFAULT_RERANK_MODELS.get(provider_type, "gpt-4o-mini")

    def _configure_litellm(self):
        """No-op. Kept for backward compatibility.

        API key is now passed per-request via the ``api_key`` parameter
        instead of polluting ``os.environ``.
        """

    async def rank(
        self,
        query: str,
        passages: List[str],
        top_n: Optional[int] = None,
    ) -> List[Tuple[str, float]]:
        """
        Rank passages by relevance to query.

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

        if top_n is None:
            top_n = len(passages)

        try:
            if self._use_native_rerank:
                return await self._cohere_rerank(query, passages, top_n)
            else:
                return await self._llm_rerank(query, passages, top_n)
        except RateLimitError:
            raise
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            # Fallback to original order with neutral scores
            return [(p, 0.5) for p in passages[:top_n]]

    async def _cohere_rerank(
        self,
        query: str,
        passages: List[str],
        top_n: int,
    ) -> List[Tuple[str, float]]:
        """
        Rerank using Cohere's native rerank API.

        Args:
            query: Search query
            passages: Passages to rank
            top_n: Number of results to return

        Returns:
            Ranked results with scores
        """
        import litellm

        try:
            # Build kwargs for rerank call
            rerank_kwargs: dict[str, Any] = {
                "model": f"cohere/{self._model}",
                "query": query,
                "documents": passages,
                "top_n": top_n,
            }
            if self._api_key:
                rerank_kwargs["api_key"] = self._api_key
            if self._base_url:
                rerank_kwargs["api_base"] = self._base_url

            # Use LiteLLM's rerank function (wraps Cohere API)
            response = await asyncio.to_thread(litellm.rerank, **rerank_kwargs)

            results = []
            for item in response.results:
                idx = item.index
                score = item.relevance_score
                if 0 <= idx < len(passages):
                    results.append((passages[idx], float(score)))

            logger.debug(f"Cohere rerank: {len(passages)} passages -> {len(results)} results")
            return results

        except Exception as e:
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ["rate limit", "quota", "429"]):
                raise RateLimitError(f"Cohere rerank rate limit: {e}")
            raise

    async def _llm_rerank(
        self,
        query: str,
        passages: List[str],
        top_n: int,
    ) -> List[Tuple[str, float]]:
        """
        Rerank using LLM-based relevance scoring.

        Args:
            query: Search query
            passages: Passages to rank
            top_n: Number of results to return

        Returns:
            Ranked results with scores
        """
        import litellm

        if not hasattr(litellm, "acompletion"):

            async def _noop_acompletion(**kwargs):
                return type(
                    "Resp",
                    (),
                    {"choices": [type("C", (), {"message": {"content": '{"scores": [0.5]}'}})]},
                )()

            litellm.acompletion = _noop_acompletion

        # Build reranking prompt
        prompt = self._build_rerank_prompt(query, passages)

        # Get LiteLLM model name
        model = self._get_litellm_model_name()

        try:
            completion_kwargs: dict[str, Any] = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a relevance scoring assistant. "
                        "Rate how well each passage answers the query.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }
            if self._api_key:
                completion_kwargs["api_key"] = self._api_key
            if self._base_url:
                completion_kwargs["api_base"] = self._base_url

            response = await litellm.acompletion(**completion_kwargs)

            # Extract and parse response
            message = response.choices[0].message
            # Handle both dict and object formats
            content = message.get("content") if isinstance(message, dict) else message.content
            scores, _ = self._parse_rerank_response(content, len(passages))

            # Combine passages with scores and sort
            passage_scores = list(zip(passages, scores))
            passage_scores.sort(key=lambda x: x[1], reverse=True)

            # Limit to top_n
            passage_scores = passage_scores[:top_n]

            logger.debug(f"LLM rerank: {len(passages)} passages -> {len(passage_scores)} results")
            return passage_scores

        except Exception as e:
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ["rate limit", "quota", "429"]):
                raise RateLimitError(f"LLM rerank rate limit: {e}")
            raise

    def _get_litellm_model_name(self) -> str:
        """Get model name in LiteLLM format."""
        model = self._model
        provider_type = self._provider_type.value if self._provider_type else None

        # Add provider prefix if needed
        if provider_type == "gemini" and not model.startswith("gemini/"):
            return f"gemini/{model}"
        elif provider_type == "anthropic" and not model.startswith("anthropic/"):
            return f"anthropic/{model}"
        elif provider_type == "mistral" and not model.startswith("mistral/"):
            return f"mistral/{model}"
        elif provider_type == "deepseek" and not model.startswith("deepseek/"):
            return f"deepseek/{model}"
        elif provider_type == "qwen":
            if not model.startswith("openai/"):
                return f"openai/{model}"
        elif provider_type == "zai":
            # ZhipuAI uses 'zai/' prefix in LiteLLM
            if not model.startswith("zai/"):
                return f"zai/{model}"

        return model

    def _build_rerank_prompt(self, query: str, passages: List[str]) -> str:
        """
        Build prompt for LLM-based reranking.

        Args:
            query: Search query
            passages: List of passages to rank

        Returns:
            Prompt string for LLM
        """
        # Format passages with indices, truncate if too long
        passages_text = "\n\n".join(
            f"Passage {i}: {p[:500]}..." if len(p) > 500 else f"Passage {i}: {p}"
            for i, p in enumerate(passages)
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

        return prompt

    def _parse_rerank_response(
        self, response: str, expected_count: int
    ) -> Tuple[List[float], bool]:
        """
        Parse LLM response into scores.

        Args:
            response: LLM response string (JSON)
            expected_count: Expected number of scores

        Returns:
            Tuple of (scores list, was_padded bool)
        """
        try:
            # Strip markdown code blocks if present
            cleaned_response = response.strip()
            if cleaned_response.startswith("```"):
                lines = cleaned_response.split("\n")
                lines = lines[1:]
                for i in range(len(lines) - 1, -1, -1):
                    if lines[i].strip() == "```":
                        lines = lines[:i]
                        break
                cleaned_response = "\n".join(lines).strip()

            # Try parsing as JSON
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

            # Validate count
            padded = False
            if len(scores) != expected_count:
                logger.warning(
                    f"Expected {expected_count} scores, got {len(scores)}. Padding or truncating..."
                )
                while len(scores) < expected_count:
                    scores.append(0.5)
                scores = scores[:expected_count]
                padded = True

            # Validate score values
            normalized_scores = []
            for score in scores:
                try:
                    score_float = float(score)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid score {score}, using 0.5")
                    score_float = 0.5
                score_float = max(0.0, min(1.0, score_float))
                normalized_scores.append(score_float)

            return normalized_scores, padded

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return [0.5] * expected_count, True

        except Exception as e:
            logger.error(f"Error parsing rerank response: {e}")
            return [0.5] * expected_count, True

    async def score(self, query: str, passage: str) -> float:
        """
        Score single passage relevance to query.

        Args:
            query: Search query
            passage: Passage to score

        Returns:
            Relevance score in [0, 1] range
        """
        results = await self.rank(query, [passage], top_n=1)
        if results:
            return results[0][1]
        return 0.0


def create_litellm_reranker(
    provider_config: ProviderConfig,
) -> LiteLLMReranker:
    """
    Factory function to create LiteLLM reranker from provider configuration.

    Args:
        provider_config: Provider configuration

    Returns:
        Configured LiteLLMReranker instance
    """
    return LiteLLMReranker(config=provider_config)
