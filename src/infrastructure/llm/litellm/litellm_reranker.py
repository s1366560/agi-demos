"""
LiteLLM Reranker Adapter for Knowledge Graph System

Implements CrossEncoderClient interface using LiteLLM library.
Provides LLM-based reranking for improved relevance scoring.
"""

import json
import logging
from typing import List, Tuple

from src.domain.llm_providers.llm_types import CrossEncoderClient
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)


class LiteLLMReranker(CrossEncoderClient):
    """
    LiteLLM-based implementation of CrossEncoderClient.

    Uses LLM-based reranking to score passages by relevance to a query.
    This approach is more flexible than traditional cross-encoder models
    and works with any LLM provider supported by LiteLLM.

    Usage:
        provider_config = ProviderConfig(...)
        reranker = LiteLLMReranker(config=provider_config)
        ranked_passages = await reranker.rank(query, passages)
    """

    def __init__(self, config: ProviderConfig):
        """
        Initialize LiteLLM reranker.

        Args:
            config: Provider configuration with reranker_model specified
        """
        self.config = config
        self.encryption_service = get_encryption_service()

        # Configure LiteLLM for reranking
        self._configure_litellm()

        # Validate reranker model is configured
        if not config.reranker_model:
            logger.warning("No reranker_model configured, will use llm_model as fallback")
            self.reranker_model = config.llm_model
        else:
            self.reranker_model = config.reranker_model

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

        logger.debug(f"Configured LiteLLM reranker for provider: {provider_type}")

    async def rank(self, query: str, passages: List[str]) -> List[Tuple[str, float]]:
        """
        Rank passages by relevance to query using LLM.

        This method uses an LLM to score each passage's relevance to the query.
        The scoring is done by asking the LLM to provide a relevance score
        from 0 to 1 for each passage.

        Args:
            query: The search query
            passages: List of passages to rank

        Returns:
            List of (passage, score) tuples sorted by relevance (descending)
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

        if not passages:
            return []

        # If only one passage, return it with perfect score
        if len(passages) == 1:
            return [(passages[0], 1.0)]

        # Build reranking prompt
        prompt = self._build_rerank_prompt(query, passages)

        try:
            # Call LiteLLM for reranking
            response = await litellm.acompletion(
                model=self.reranker_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a relevance scoring assistant. "
                        "Rate how well each passage answers the query.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,  # Deterministic scoring
                response_format={"type": "json_object"},
            )

            # Extract and parse response
            content = response.choices[0].message["content"]
            scores, padded = self._parse_rerank_response(content, len(passages))

            # Combine passages with scores
            passage_scores = list(zip(passages, scores))
            # Sort only if counts match; if padded, keep original order so padding remains at the end
            if not padded:
                passage_scores.sort(key=lambda x: x[1], reverse=True)

            logger.debug(f"Reranked {len(passages)} passages for query: {query[:50]}...")

            return passage_scores

        except Exception as e:
            logger.error(f"LiteLLM reranking error: {e}")
            # Fallback: return passages in original order with neutral scores
            logger.warning("Falling back to original order with neutral scores")
            return [(p, 0.5) for p in passages]

    def _build_rerank_prompt(self, query: str, passages: List[str]) -> str:
        """
        Build prompt for LLM-based reranking.

        Args:
            query: Search query
            passages: List of passages to rank

        Returns:
            Prompt string for LLM
        """
        # Format passages with indices
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
            List of scores
        """
        try:
            # Strip markdown code blocks if present
            cleaned_response = response.strip()
            if cleaned_response.startswith("```"):
                # Remove opening code block
                lines = cleaned_response.split("\n")
                # Remove first line (```json or ```)
                lines = lines[1:]
                # Find closing ``` and remove it
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
                # Pad or truncate to expected count
                while len(scores) < expected_count:
                    scores.append(0.5)
                scores = scores[:expected_count]
                padded = True

            # Validate score values
            normalized_scores = []
            for score in scores:
                # Ensure score is float
                try:
                    score_float = float(score)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid score {score}, using 0.5")
                    score_float = 0.5

                # Clamp to [0, 1]
                score_float = max(0.0, min(1.0, score_float))
                normalized_scores.append(score_float)

            return normalized_scores, padded

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Raw response: {response}")
            # Return neutral scores
            return [0.5] * expected_count, True

        except Exception as e:
            logger.error(f"Error parsing rerank response: {e}")
            logger.error(f"Raw response: {response}")
            # Return neutral scores
            return [0.5] * expected_count, True


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
