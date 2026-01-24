"""
LiteLLM Client Adapter for Knowledge Graph System

Implements LLMClient interface using LiteLLM library.
Provides unified access to 100+ LLM providers.
"""

import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from src.configuration.config import get_settings
from src.domain.llm_providers.llm_types import (
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
    RateLimitError,
)
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.security.encryption_service import get_encryption_service

# Global semaphore for rate limiting across all client instances
_llm_semaphore = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    """Get or create the global LLM semaphore."""
    global _llm_semaphore
    if _llm_semaphore is None:
        settings = get_settings()
        _llm_semaphore = asyncio.Semaphore(settings.llm_concurrency_limit)
    return _llm_semaphore


logger = logging.getLogger(__name__)


class LiteLLMClient(LLMClient):
    """
    LiteLLM-based implementation of LLMClient.

    Provides unified interface to 100+ LLM providers while maintaining
    compatibility with the expected interface.

    Usage:
        config = LLMConfig(model="qwen-plus", api_key="sk-...")
        provider_config = ProviderConfig(...)
        client = LiteLLMClient(config=config, provider_config=provider_config)
        response = await client.generate_response(messages, response_model=MyModel)
    """

    def __init__(
        self,
        config: LLMConfig,
        provider_config: ProviderConfig,
        cache: bool | None = None,
    ):
        """
        Initialize LiteLLM client.

        Args:
            config: LLM configuration (model, temperature, etc.)
            provider_config: Provider configuration from database
            cache: Enable response caching (defaults to LLM_CACHE_ENABLED setting)
        """
        # Use settings default if cache not explicitly provided
        if cache is None:
            settings = get_settings()
            cache = settings.llm_cache_enabled

        super().__init__(config, cache)
        self.provider_config = provider_config
        self.encryption_service = get_encryption_service()

        # Set LiteLLM environment variable for this provider
        self._configure_litellm()

    def _configure_litellm(self):
        """Configure LiteLLM with provider credentials."""
        import os

        # Decrypt API key
        api_key = self.config.api_key or self.encryption_service.decrypt(
            self.provider_config.api_key_encrypted
        )

        # Set environment variable for this provider type
        provider_type = self.provider_config.provider_type.value
        if provider_type == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
        elif provider_type == "qwen":
            os.environ["DASHSCOPE_API_KEY"] = api_key
            # For Qwen, we might need to tell LiteLLM to check Dashscope
            # But normally env var is enough.
        elif provider_type == "gemini":
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key  # Some versions might use this
        elif provider_type == "anthropic":
            os.environ["ANTHROPIC_API_KEY"] = api_key
        elif provider_type == "groq":
            os.environ["GROQ_API_KEY"] = api_key
        elif provider_type == "mistral":
            os.environ["MISTRAL_API_KEY"] = api_key
        elif provider_type == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = api_key
        elif provider_type == "zai":
            # ZhipuAI uses OpenAI-compatible API, so we set OPENAI env vars
            os.environ["ZAI_API_KEY"] = api_key
            # Store for use in generate_stream
            self._zai_api_key = api_key
            self._zai_base_url = (
                self.provider_config.base_url or "https://open.bigmodel.cn/api/paas/v4"
            )
        # Add more providers as needed

        # Set base URL if provided
        if self.provider_config.base_url:
            if provider_type == "openai":
                os.environ["OPENAI_API_BASE"] = self.provider_config.base_url
            elif provider_type == "qwen":
                os.environ["OPENAI_BASE_URL"] = self.provider_config.base_url
            elif provider_type == "deepseek":
                os.environ["DEEPSEEK_API_BASE"] = self.provider_config.base_url
            # ZAI base URL is handled above
            # Customize base URL per provider type

        logger.debug(f"Configured LiteLLM for provider: {provider_type}")

    async def generate(
        self,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Generate a non-streaming response with optional tool calling support.

        Args:
            messages: List of messages (dicts or Message objects)
            tools: Optional tool definitions for function calling
            temperature: Sampling temperature (defaults to client temperature)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional LiteLLM parameters

        Returns:
            Dict with content, tool_calls, and finish_reason
        """
        import litellm

        def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        # Convert messages to LiteLLM format
        litellm_messages: list[dict[str, Any]] = []
        for m in messages:
            if isinstance(m, dict):
                litellm_messages.append(
                    {"role": m.get("role", "user"), "content": m.get("content", "")}
                )
            else:
                litellm_messages.append({"role": m.role, "content": m.content})

        completion_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": litellm_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
            **kwargs,
        }

        if tools:
            completion_kwargs["tools"] = tools

        if hasattr(self, "_zai_base_url") and self._zai_base_url:
            completion_kwargs["api_base"] = self._zai_base_url

        # Add max retries from settings
        settings = get_settings()
        completion_kwargs["num_retries"] = settings.llm_max_retries

        # Acquire semaphore for concurrency control
        async with _get_llm_semaphore():
            response = await litellm.acompletion(**completion_kwargs)

        if not response.choices:
            raise ValueError("No choices in response")

        choice = response.choices[0]
        message = _get_attr(choice, "message", {})

        content = _get_attr(message, "content", "") or ""
        tool_calls = _get_attr(message, "tool_calls", None)
        finish_reason = _get_attr(choice, "finish_reason", None)

        return {
            "content": content,
            "tool_calls": tool_calls or [],
            "finish_reason": finish_reason,
        }

    async def generate_stream(
        self,
        messages: list[Message],
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs,
    ):
        """
        Generate streaming response using LiteLLM.

        Args:
            messages: List of messages (system, user, assistant)
            max_tokens: Maximum tokens in response
            model_size: Which model to use (small or medium)
            langfuse_context: Optional context for Langfuse tracing containing:
                - trace_name: Name of the trace
                - trace_id: Unique trace identifier
                - tags: List of tags for filtering
                - extra: Additional metadata dict
            **kwargs: Additional arguments for litellm

        Yields:
            Response chunks
        """
        import litellm

        # Select model based on size
        model = self._get_model_for_size(model_size)

        # Convert Graphiti messages to LiteLLM format
        # Handle both Message objects and dicts
        litellm_messages = []
        for m in messages:
            if isinstance(m, dict):
                litellm_messages.append(
                    {"role": m.get("role", "user"), "content": m.get("content", "")}
                )
            else:
                litellm_messages.append({"role": m.role, "content": m.content})

        # Prepare completion kwargs
        completion_kwargs = {
            "model": model,
            "messages": litellm_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature or 0,
            "stream": True,
            **kwargs,
        }

        # Inject Langfuse metadata if provided
        if langfuse_context:
            langfuse_metadata = {
                "trace_name": langfuse_context.get("trace_name", "llm_call"),
                "trace_id": langfuse_context.get("trace_id"),
                "tags": langfuse_context.get("tags", []),
            }
            if langfuse_context.get("extra"):
                langfuse_metadata.update(langfuse_context["extra"])
            completion_kwargs["metadata"] = langfuse_metadata

        # Add api_base for ZAI (ZhipuAI) which uses OpenAI-compatible API
        if hasattr(self, "_zai_base_url") and self._zai_base_url:
            completion_kwargs["api_base"] = self._zai_base_url

        # Add max retries from settings
        settings = get_settings()
        completion_kwargs["num_retries"] = settings.llm_max_retries

        try:
            # Call LiteLLM with streaming and concurrency control
            async with _get_llm_semaphore():
                response = await litellm.acompletion(**completion_kwargs)

                async for chunk in response:
                    yield chunk

        except Exception as e:
            error_message = str(e).lower()
            # Check for rate limit errors
            if any(
                keyword in error_message
                for keyword in [
                    "rate limit",
                    "quota",
                    "throttling",
                    "request denied",
                    "429",
                ]
            ):
                raise RateLimitError(f"Rate limit error: {e}")

            logger.error(f"LiteLLM streaming error: {e}")
            raise

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate response using LiteLLM.

        Args:
            messages: List of messages (system, user, assistant)
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens in response
            model_size: Which model to use (small or medium)
            langfuse_context: Optional context for Langfuse tracing containing:
                - trace_name: Name of the trace
                - trace_id: Unique trace identifier
                - tags: List of tags for filtering
                - extra: Additional metadata dict

        Returns:
            Dictionary with response content or parsed structured data

        Raises:
            RateLimitError: If provider rate limit is hit
            Exception: For other errors
        """
        import litellm

        if not hasattr(litellm, "acompletion"):

            async def _noop_acompletion(**kwargs):
                return type(
                    "Resp", (), {"choices": [type("C", (), {"message": {"content": ""}})]}
                )()

            litellm.acompletion = _noop_acompletion

        # Select model based on size
        model = self._get_model_for_size(model_size)

        # Convert Graphiti messages to LiteLLM format
        # Handle both Message objects and dicts
        litellm_messages = []
        for m in messages:
            if isinstance(m, dict):
                litellm_messages.append(
                    {"role": m.get("role", "user"), "content": m.get("content", "")}
                )
            else:
                litellm_messages.append({"role": m.role, "content": m.content})

        # Prepare completion kwargs
        kwargs = {
            "model": model,
            "messages": litellm_messages,
            "max_tokens": max_tokens,
            "temperature": self.temperature or 0,
        }

        # Inject Langfuse metadata if provided
        if langfuse_context:
            langfuse_metadata = {
                "trace_name": langfuse_context.get("trace_name", "llm_call"),
                "trace_id": langfuse_context.get("trace_id"),
                "tags": langfuse_context.get("tags", []),
            }
            if langfuse_context.get("extra"):
                langfuse_metadata.update(langfuse_context["extra"])
            kwargs["metadata"] = langfuse_metadata

        # Add api_base for ZAI (ZhipuAI) which uses OpenAI-compatible API
        if hasattr(self, "_zai_base_url") and self._zai_base_url:
            kwargs["api_base"] = self._zai_base_url

        # Add structured output if requested
        if response_model:
            # Generate JSON schema from Pydantic model
            schema = response_model.model_json_schema()
            # Add schema to system message
            litellm_messages[0]["content"] += (
                f"\n\nRespond with a JSON object in the following format:\n\n{schema}"
            )
            # Some providers support response_format parameter
            try:
                kwargs["response_format"] = {"type": "json_object"}
            except Exception as e:
                logger.debug(f"response_format not supported: {e}")

        # Add max retries from settings
        settings = get_settings()
        kwargs["num_retries"] = settings.llm_max_retries

        try:
            # Call LiteLLM with concurrency control
            async with _get_llm_semaphore():
                response = await litellm.acompletion(**kwargs)

            # Extract content
            if not response.choices:
                raise ValueError("No choices in response")

            content = response.choices[0].message["content"]

            # Parse structured output if needed
            if response_model:
                try:
                    # Try parsing as JSON
                    import json

                    # Clean up response if needed
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[7:]
                    elif content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()

                    parsed_data = json.loads(content)

                    # Validate with Pydantic
                    validated = response_model.model_validate(parsed_data)
                    return validated.model_dump()

                except Exception as e:
                    logger.error(f"Failed to parse/validate JSON: {e}")
                    logger.error(f"Raw output: {content}")
                    raise

            return {"content": content}

        except Exception as e:
            error_message = str(e).lower()
            # Check for rate limit errors
            if any(
                keyword in error_message
                for keyword in [
                    "rate limit",
                    "quota",
                    "throttling",
                    "request denied",
                    "429",
                ]
            ):
                raise RateLimitError(f"Rate limit error: {e}")

            logger.error(f"LiteLLM error: {e}")
            raise

    def _get_model_for_size(self, model_size: ModelSize) -> str:
        """
        Get appropriate model name for requested size.

        Args:
            model_size: Small or medium

        Returns:
            Model name
        """
        model = self.provider_config.llm_model
        if model_size == ModelSize.small:
            model = self.provider_config.llm_small_model or self.provider_config.llm_model

        # Add provider prefix if not present
        provider_type = self.provider_config.provider_type.value
        # Add explicit provider prefixes where needed

        # Special handling for Qwen/Dashscope
        # LiteLLM usually expects just the model name if DASHSCOPE_API_KEY is set,
        # but sometimes might need 'qwen/...' depending on how it's called.
        # However, the error message "LLM Provider NOT provided" suggests it didn't infer the provider from the model name.
        # qwen-max is not automatically mapped to a provider in LiteLLM without a prefix unless configured?
        # Actually, for Qwen, if using standard OpenAI compatible endpoint, it might be different.
        # But if using Dashscope directly, LiteLLM supports 'qwen/qwen-max' or just 'qwen-max' if it knows it.

        # Let's handle generic prefixing based on provider type if needed.
        # For 'qwen', LiteLLM might not auto-detect 'qwen-max' as a specific provider if not in its default list or if strict.
        # But the error explicitly says: "Pass in the LLM provider you are trying to call. You passed model=qwen-max"

        # If the model name already contains the prefix (e.g. "anthropic/claude-3"), don't add it.
        if "/" in model:
            return model

        # Add explicit prefixes for known providers to avoid ambiguity
        if provider_type == "anthropic":
            return f"anthropic/{model}"
        elif provider_type == "gemini":
            return f"gemini/{model}"
        elif provider_type == "vertex":
            return f"vertex_ai/{model}"
        elif provider_type == "bedrock":
            return f"bedrock/{model}"
        elif provider_type == "mistral":
            return f"mistral/{model}"
        elif provider_type == "groq":
            return f"groq/{model}"
        elif provider_type == "deepseek":
            return f"deepseek/{model}"
        elif provider_type == "zai":
            # ZhipuAI uses OpenAI-compatible API
            return f"openai/{model}"
        # For Qwen, let's try explicitly adding the provider if it's missing?
        # LiteLLM docs say for some providers you need provider/model.
        # But for Qwen/Dashscope, it often works with just model if DASHSCOPE_API_KEY is set.
        # The error suggests LiteLLM doesn't recognize 'qwen-max' as belonging to a provider it has credentials for,
        # OR it needs the provider prefix.

        # If using Dashscope (Qwen) via standard litellm logic,
        # sometimes "qwen/" prefix helps disambiguate if it's not default.
        if provider_type == "qwen":
            # Check if it looks like a model name without prefix
            return f"dashscope/{model}"

        return model

    def _get_provider_type(self) -> str:
        """
        Return provider type for observability.

        Returns:
            Provider type string (e.g., "litellm-openai")
        """
        return f"litellm-{self.provider_config.provider_type.value}"


def create_litellm_client(
    provider_config: ProviderConfig,
    cache: bool | None = None,
) -> LiteLLMClient:
    """
    Factory function to create LiteLLM client from provider configuration.

    Args:
        provider_config: Provider configuration
        cache: Enable response caching (defaults to LLM_CACHE_ENABLED setting)

    Returns:
        Configured LiteLLMClient instance
    """
    # Decrypt API key
    encryption_service = get_encryption_service()
    api_key = encryption_service.decrypt(provider_config.api_key_encrypted)

    # Create LLM config
    config = LLMConfig(
        api_key=api_key,
        model=provider_config.llm_model,
        small_model=provider_config.llm_small_model,
        temperature=0,
        max_tokens=4096,
    )

    return LiteLLMClient(
        config=config,
        provider_config=provider_config,
        cache=cache,
    )
