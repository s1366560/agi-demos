"""
Z.AI (ZhipuAI) Official SDK Implementation.

Uses the official zai-sdk for Python.
Documentation: https://docs.bigmodel.cn/cn/guide/develop/python/introduction
"""

import asyncio
import functools
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Optional

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
DEFAULT_MODEL = "glm-4-plus"
DEFAULT_SMALL_MODEL = "glm-4-flash"
DEFAULT_EMBEDDING_MODEL = "embedding-3"
DEFAULT_RERANKER_MODEL = "glm-4-flash"

# Z.AI API endpoint
ZAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

# Embedding dimensions for Z.AI models
# According to https://open.bigmodel.cn/dev/api#embedding
# embedding-3 and embedding-3-pro return 4096 dimensions
ZAI_EMBEDDING_DIMS = {
    "embedding-1": 1024,
    "embedding-2": 1024,
    "embedding-3": 4096,
    "embedding-3-pro": 4096,  # CRITICAL: embedding-3-pro returns 4096 dimensions
}


def _generate_example_from_model(model: type[BaseModel]) -> dict[str, Any]:
    """
    Generate a simple example JSON from a Pydantic model.
    This provides a cleaner example than the full JSON Schema with $defs.
    """
    if model is None:
        return {}

    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    example = {}

    for field_name, field_def in properties.items():
        field_type = field_def.get("type", "string")

        # Get first example from examples list if available
        if "examples" in field_def and field_def["examples"]:
            example[field_name] = field_def["examples"][0]
        elif field_type == "array":
            # For arrays, check if items have examples
            items = field_def.get("items", {})
            if "examples" in items and items["examples"]:
                example[field_name] = [items["examples"][0]]
            else:
                example[field_name] = []
        elif field_type == "object":
            example[field_name] = {}
        elif field_type == "boolean":
            example[field_name] = True
        elif field_type in ("integer", "number"):
            example[field_name] = 0
        else:
            # string or unknown
            default = field_def.get("default")
            if default is not None:
                example[field_name] = default
            else:
                example[field_name] = ""

    return example


def _is_schema_response(data: dict[str, Any]) -> bool:
    """
    Check if the JSON response looks like a JSON Schema rather than actual data.
    This happens when some LLMs echo back the schema instead of generating data.
    """
    if not isinstance(data, dict):
        return False

    # Check for JSON Schema keywords
    schema_keywords = ["$defs", "$schema", "allOf", "anyOf", "oneOf"]

    # If we have $defs or other schema keywords at the top level, it's likely a schema
    if any(keyword in data for keyword in schema_keywords):
        return True

    # If we have "properties" at the top level with "type" being "object",
    # and missing actual expected data fields, it's likely a schema
    if "properties" in data and "type" in data:
        if data.get("type") == "object":
            # Check if properties contain schema metadata (description, type, title)
            # rather than actual data values
            props = data.get("properties", {})
            if props and all(
                isinstance(v, dict) and ("type" in v or "description" in v or "title" in v)
                for v in props.values()
            ):
                return True

    return False


class ZAIClient(LLMClient, BaseLLMClient):
    """
    Z.AI (ZhipuAI) LLM client using official SDK.

    Uses the official zai-sdk which provides better integration
    with Z.AI's features like thinking mode, web search, and function calling.
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
        cache: bool = False,
    ):
        """
        Initialize Z.AI client with official SDK.

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

        # Import and create official SDK client
        try:
            from zai import ZhipuAiClient

            self.client = ZhipuAiClient(
                api_key=api_key,
                base_url=provider_config.base_url or ZAI_BASE_URL,
            )
        except ImportError as e:
            raise ImportError(
                "zai-sdk is required for Z.AI provider. Install it with: pip install zai-sdk>=0.2.0"
            ) from e

        # Store models
        self.model = config.model
        self.small_model = config.small_model or config.model

        # Create per-instance thread pool for async operations
        # Using a larger pool to avoid deadlocks during concurrent operations
        self._thread_pool = ThreadPoolExecutor(max_workers=50, thread_name_prefix="zai_llm")

    def close(self) -> None:
        """Cleanup resources by shutting down the thread pool."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None

    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close()

    def _get_model_for_size(self, model_size: ModelSize) -> str:
        """Get model name for requested size."""
        if model_size == ModelSize.small:
            return self.small_model
        return self.model

    def _get_provider_type(self) -> str:
        """Return provider type identifier."""
        return "zai"

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in a thread pool."""
        if kwargs:
            # Bind keyword arguments using functools.partial
            func = functools.partial(func, **kwargs)
        # Use get_running_loop() to get the current event loop
        # This is more reliable than get_event_loop() in worker contexts
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._thread_pool, func, *args)

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: Optional[type[BaseModel]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """
        Generate response using Z.AI official SDK.

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

        # Convert messages to Z.AI format
        api_messages = [{"role": m.role, "content": m.content} for m in messages]

        # Prepare request parameters
        kwargs = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature or 0,
        }

        # Add structured output if requested (Z.AI supports JSON mode)
        if response_model:
            # Add native JSON mode to force JSON output
            kwargs["response_format"] = {"type": "json_object"}

            # Add JSON instruction to system message (use simplified example instead of full schema)
            if api_messages and api_messages[0]["role"] == "system":
                # Generate a simple example based on the model structure
                # This avoids LLM echoing back the complex JSON Schema with $defs
                schema_example = json.dumps(
                    _generate_example_from_model(response_model), ensure_ascii=False
                )
                api_messages[0]["content"] += (
                    f" You must output valid JSON data only (not the schema). "
                    f"Example format:\n{schema_example}"
                )

        try:
            # Run the synchronous SDK call in thread pool
            response = await self._run_sync(self.client.chat.completions.create, **kwargs)

            content = response.choices[0].message.content

            if not content:
                raise ValueError("Empty response content")

            # Parse structured output if needed
            if response_model:
                try:
                    # Robust JSON extraction: find first '{' and last '}'
                    # This handles markdown blocks (```json ... ```) and extra text (preamble/postscript)
                    start_idx = content.find("{")
                    end_idx = content.rfind("}")

                    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                        content = content[start_idx : end_idx + 1]
                    else:
                        # Fallback to simple cleanup if braces not found (unlikely for valid JSON)
                        content = content.strip()
                        if content.startswith("```json"):
                            content = content[7:]
                        elif content.startswith("```"):
                            content = content[3:]
                        if content.endswith("```"):
                            content = content[:-3]
                        content = content.strip()

                    parsed_data = json.loads(content)

                    # Check if LLM returned a JSON Schema instead of actual data
                    # This can happen when the LLM echoes back the schema definition
                    if _is_schema_response(parsed_data):
                        logger.warning(
                            "Zai returned JSON Schema instead of data. Retrying with clearer instructions..."
                        )
                        if retry_count < 2:
                            # Add the bad response as assistant message and provide correction
                            messages.append(Message(role="assistant", content=content))
                            messages.append(
                                Message(
                                    role="user",
                                    content="You returned the JSON Schema definition instead of actual data. "
                                    "Please output the JSON object containing the actual extracted data, "
                                    "not the schema itself.",
                                )
                            )
                            return await self._generate_response(
                                messages, response_model, max_tokens, model_size, retry_count + 1
                            )
                        raise ValueError("LLM returned JSON Schema instead of data")

                    validated = response_model.model_validate(parsed_data)
                    return validated.model_dump()
                except Exception as e:
                    logger.error(f"Failed to parse JSON: {e}")
                    if retry_count < 2:
                        # Retry with feedback
                        messages.append(Message(role="assistant", content=content))
                        messages.append(
                            Message(
                                role="user",
                                content="Please return valid JSON data only, not the schema.",
                            )
                        )
                        return await self._generate_response(
                            messages, response_model, max_tokens, model_size, retry_count + 1
                        )
                    raise

            return {"content": content}

        except Exception as e:
            error_msg = str(e).lower()
            # Check for rate limit errors
            if any(kw in error_msg for kw in ["rate limit", "429", "quota", "too many requests"]):
                raise RateLimitError(f"Rate limit error: {e}")
            logger.error(f"Z.AI API error: {e}")
            raise


class ZAIEmbedder(EmbedderClient):
    """
    Z.AI Embedder with official SDK support.

    Uses Z.AI's embedding models: embedding-1, embedding-2, embedding-3
    Documentation: https://open.bigmodel.cn/dev/api#embedding
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
        embedding_dim: int = 1024,
    ):
        """
        Initialize Z.AI embedder with official SDK.

        Args:
            provider_config: Provider configuration with encrypted API key
            embedding_dim: Dimension of embedding vectors (default: 1024)
        """
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()

        # Decrypt API key
        api_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Get embedding model
        self.embedding_model = provider_config.embedding_model or DEFAULT_EMBEDDING_MODEL

        # Determine embedding dimension
        self._embedding_dim = ZAI_EMBEDDING_DIMS.get(self.embedding_model, embedding_dim)

        # Import and create official SDK client
        try:
            from zai import ZhipuAiClient

            self.client = ZhipuAiClient(
                api_key=api_key,
                base_url=provider_config.base_url or ZAI_BASE_URL,
            )
        except ImportError as e:
            raise ImportError(
                "zai-sdk is required for Z.AI provider. Install it with: pip install zai-sdk>=0.2.0"
            ) from e

        # Create per-instance thread pool for async operations
        # Using a larger pool to avoid deadlocks during concurrent operations
        self._thread_pool = ThreadPoolExecutor(max_workers=50, thread_name_prefix="zai_embedder")

        # Create a config object for compatibility with ValidatedEmbedder
        from dataclasses import dataclass

        @dataclass
        class ZAIEmbedderConfig:
            """Config object for ZAIEmbedder."""

            embedding_model: str
            embedding_dim: int

        self.config = ZAIEmbedderConfig(
            embedding_model=self.embedding_model,
            embedding_dim=self._embedding_dim,
        )

    def close(self) -> None:
        """Cleanup resources by shutting down the thread pool."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None

    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close()

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in a thread pool."""
        if kwargs:
            # Bind keyword arguments using functools.partial
            func = functools.partial(func, **kwargs)
        # Use get_running_loop() to get the current event loop
        # This is more reliable than get_event_loop() in worker contexts
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._thread_pool, func, *args)

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
        # Normalize input to list
        if isinstance(input_data, str):
            texts = [input_data]
        else:
            texts = list(input_data)

        if not texts:
            raise ValueError("No texts provided for embedding")

        try:
            # Run the synchronous SDK call in thread pool
            response = await self._run_sync(
                self.client.embeddings.create,
                model=self.embedding_model,
                input=texts[0] if len(texts) == 1 else texts,
            )

            # Extract embedding
            if not response.data or not response.data[0].embedding:
                raise ValueError("No embedding returned")

            embedding = response.data[0].embedding

            # === CRITICAL: Validate embedding dimension ===
            expected_dim = self._embedding_dim
            actual_dim = len(embedding)

            if actual_dim != expected_dim:
                logger.warning(
                    f"[ZAIEmbedder] Dimension mismatch! Expected {expected_dim}D, got {actual_dim}D. "
                    f"Adjusting to prevent downstream errors."
                )
                # Truncate if longer
                if actual_dim > expected_dim:
                    embedding = embedding[:expected_dim]
                # Pad with zeros if shorter (unlikely but safe)
                elif actual_dim < expected_dim:
                    embedding = embedding + [0.0] * (expected_dim - actual_dim)

            logger.debug(
                f"Created Z.AI embedding: model={self.embedding_model}, "
                f"dim={len(embedding)}, input_length={len(texts[0]) if texts else 0}"
            )

            return embedding

        except Exception as e:
            logger.error(f"Z.AI embedding error: {e}")
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

        # Z.AI supports batch embeddings
        try:
            response = await self._run_sync(
                self.client.embeddings.create,
                model=self.embedding_model,
                input=input_data_list,
            )

            embeddings = [item.embedding for item in response.data]

            # === CRITICAL: Validate embedding dimensions ===
            expected_dim = self._embedding_dim
            validated_embeddings = []

            for embedding in embeddings:
                actual_dim = len(embedding)

                if actual_dim != expected_dim:
                    logger.warning(
                        f"[ZAIEmbedder] Batch dimension mismatch! Expected {expected_dim}D, got {actual_dim}D. "
                        f"Adjusting to prevent downstream errors."
                    )
                    # Truncate if longer
                    if actual_dim > expected_dim:
                        embedding = embedding[:expected_dim]
                    # Pad with zeros if shorter
                    elif actual_dim < expected_dim:
                        embedding = embedding + [0.0] * (expected_dim - actual_dim)

                validated_embeddings.append(embedding)

            logger.debug(
                f"Created Z.AI batch embeddings: model={self.embedding_model}, "
                f"count={len(validated_embeddings)}, dim={len(validated_embeddings[0]) if validated_embeddings else 0}"
            )

            return validated_embeddings

        except Exception as e:
            logger.error(f"Z.AI batch embedding error: {e}")
            # Fallback to individual processing
            logger.info("Falling back to individual embedding requests")
            embeddings = []
            for text in input_data_list:
                embedding = await self.create(text)
                embeddings.append(embedding)
            return embeddings


class ZAIReranker(CrossEncoderClient):
    """
    Z.AI Reranker using official Rerank API.

    Uses Z.AI's dedicated rerank model for relevance scoring.
    API Documentation: https://docs.bigmodel.cn/api-reference/模型-api/文本重排序
    """

    def __init__(
        self,
        provider_config: ProviderConfig,
    ):
        """
        Initialize Z.AI reranker with official SDK.

        Args:
            provider_config: Provider configuration with encrypted API key
        """
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()

        # Decrypt API key
        api_key = self.encryption_service.decrypt(provider_config.api_key_encrypted)

        # Import and create official SDK client
        try:
            from zai import ZhipuAiClient

            self.client = ZhipuAiClient(
                api_key=api_key,
                base_url=provider_config.base_url or ZAI_BASE_URL,
            )
        except ImportError as e:
            raise ImportError(
                "zai-sdk is required for Z.AI provider. Install it with: pip install zai-sdk>=0.2.0"
            ) from e

        # Rerank model is fixed as "rerank" for Z.AI
        self.model = "rerank"

        # Create per-instance thread pool for async operations
        # Using a larger pool to avoid deadlocks during concurrent operations
        self._thread_pool = ThreadPoolExecutor(max_workers=50, thread_name_prefix="zai_reranker")

    def close(self) -> None:
        """Cleanup resources by shutting down the thread pool."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None

    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close()

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in a thread pool."""
        if kwargs:
            # Bind keyword arguments using functools.partial
            func = functools.partial(func, **kwargs)
        # Use get_running_loop() to get the current event loop
        # This is more reliable than get_event_loop() in worker contexts
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._thread_pool, func, *args)

    async def rank(
        self,
        query: str,
        passages: list[str],
        top_n: Optional[int] = None,
    ) -> list[tuple[str, float]]:
        """
        Rank passages by relevance to query using Z.AI's Rerank API.

        Uses the official /rerank endpoint which provides optimized
        relevance scoring for information retrieval scenarios.

        Args:
            query: Search query (max 4096 characters)
            passages: List of passages to rank (max 128 items)
            top_n: Optional limit on number of results

        Returns:
            List of (passage, score) tuples sorted by relevance (descending)
        """
        if not passages:
            return []

        if len(passages) == 1:
            return [(passages[0], 1.0)]

        # Z.AI Rerank API limits
        MAX_DOCUMENTS = 128
        MAX_QUERY_LENGTH = 4096
        MAX_DOCUMENT_LENGTH = 4096

        # Truncate query if needed
        truncated_query = query[:MAX_QUERY_LENGTH]

        # Truncate documents if needed
        truncated_documents = [p[:MAX_DOCUMENT_LENGTH] for p in passages[:MAX_DOCUMENTS]]

        try:
            # Call Z.AI's Rerank API using the post method
            response = await self._run_sync(
                self.client.post,
                path="/paas/v4/rerank",
                body={
                    "model": self.model,
                    "query": truncated_query,
                    "documents": truncated_documents,
                    "top_n": top_n if top_n else len(truncated_documents),
                    "return_documents": True,
                },
            )

            # Parse response - Z.AI SDK returns the response dict directly
            results = response.get("results", [])

            # Build result tuples (passage, score)
            passage_scores = []
            for result in results:
                index = result.get("index", 0)
                score = result.get("relevance_score", 0.5)
                # Use the original passage text (not truncated)
                if 0 <= index < len(passages):
                    passage_scores.append((passages[index], score))

            # Results are already sorted by relevance from the API
            return passage_scores

        except Exception as e:
            logger.error(f"Z.AI reranking error: {e}")
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


@dataclass
class ZAISimpleEmbedderConfig:
    """Simple config for ZAISimpleEmbedder."""

    embedding_model: str = "embedding-3"
    embedding_dim: int = 1024
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class ZAISimpleEmbedder(EmbedderClient):
    """
    Simple Z.AI Embedder that works with direct settings.

    Unlike ZAIEmbedder which requires ProviderConfig with encrypted API key,
    this class accepts direct parameters like QwenEmbedder.

    Documentation: https://open.bigmodel.cn/dev/api#embedding
    """

    def __init__(
        self,
        config: Optional[ZAISimpleEmbedderConfig] = None,
    ):
        """
        Initialize Z.AI embedder with direct settings.

        Args:
            config: Embedder configuration with API key, model, etc.
        """
        if config is None:
            config = ZAISimpleEmbedderConfig()

        self.config = config

        # Get embedding model
        self.embedding_model = config.embedding_model or DEFAULT_EMBEDDING_MODEL

        # Determine embedding dimension from model or config
        self._embedding_dim = ZAI_EMBEDDING_DIMS.get(self.embedding_model, config.embedding_dim)

        # Get API key
        api_key = config.api_key
        if not api_key:
            import os

            api_key = os.environ.get("ZHIPU_API_KEY") or os.environ.get("ZAI_API_KEY")
            if not api_key:
                logger.warning(
                    "API key not provided and ZHIPU_API_KEY/ZAI_API_KEY environment variable not set"
                )

        # Import and create official SDK client
        try:
            from zai import ZhipuAiClient

            self.client = ZhipuAiClient(
                api_key=api_key,
                base_url=config.base_url or ZAI_BASE_URL,
            )
        except ImportError as e:
            raise ImportError(
                "zai-sdk is required for Z.AI provider. Install it with: pip install zai-sdk>=0.2.0"
            ) from e

        # Create per-instance thread pool for async operations
        self._thread_pool = ThreadPoolExecutor(
            max_workers=50, thread_name_prefix="zai_simple_embedder"
        )

    def close(self) -> None:
        """Cleanup resources by shutting down the thread pool."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None

    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close()

    def _run_sync(self, func, *args, **kwargs):
        """Run a synchronous function in a thread pool."""
        if kwargs:
            func = functools.partial(func, **kwargs)
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._thread_pool, func, *args)

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
        # Normalize input to list
        if isinstance(input_data, str):
            texts = [input_data]
        else:
            texts = list(input_data)

        if not texts:
            raise ValueError("No texts provided for embedding")

        try:
            # Run the synchronous SDK call in thread pool
            response = await self._run_sync(
                self.client.embeddings.create,
                model=self.embedding_model,
                input=texts[0] if len(texts) == 1 else texts,
            )

            # Extract embedding
            if not response.data or not response.data[0].embedding:
                raise ValueError("No embedding returned")

            embedding = response.data[0].embedding

            # Validate embedding dimension
            expected_dim = self._embedding_dim
            actual_dim = len(embedding)

            if actual_dim != expected_dim:
                logger.warning(
                    f"[ZAISimpleEmbedder] Dimension mismatch! Expected {expected_dim}D, got {actual_dim}D. "
                    f"Adjusting to prevent downstream errors."
                )
                if actual_dim > expected_dim:
                    embedding = embedding[:expected_dim]
                elif actual_dim < expected_dim:
                    embedding = embedding + [0.0] * (expected_dim - actual_dim)

            logger.debug(
                f"Created Z.AI embedding: model={self.embedding_model}, "
                f"dim={len(embedding)}, input_length={len(texts[0]) if texts else 0}"
            )

            return embedding

        except Exception as e:
            logger.error(f"Z.AI embedding error: {e}")
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
            response = await self._run_sync(
                self.client.embeddings.create,
                model=self.embedding_model,
                input=input_data_list,
            )

            embeddings = [item.embedding for item in response.data]

            # Validate embedding dimensions
            expected_dim = self._embedding_dim
            validated_embeddings = []

            for embedding in embeddings:
                actual_dim = len(embedding)

                if actual_dim != expected_dim:
                    logger.warning(
                        f"[ZAISimpleEmbedder] Batch dimension mismatch! Expected {expected_dim}D, got {actual_dim}D. "
                        f"Adjusting to prevent downstream errors."
                    )
                    if actual_dim > expected_dim:
                        embedding = embedding[:expected_dim]
                    elif actual_dim < expected_dim:
                        embedding = embedding + [0.0] * (expected_dim - actual_dim)

                validated_embeddings.append(embedding)

            logger.debug(
                f"Created Z.AI batch embeddings: model={self.embedding_model}, "
                f"count={len(validated_embeddings)}, dim={len(validated_embeddings[0]) if validated_embeddings else 0}"
            )

            return validated_embeddings

        except Exception as e:
            logger.error(f"Z.AI batch embedding error: {e}")
            # Fallback to individual processing
            logger.info("Falling back to individual embedding requests")
            embeddings = []
            for text in input_data_list:
                embedding = await self.create(text)
                embeddings.append(embedding)
            return embeddings
