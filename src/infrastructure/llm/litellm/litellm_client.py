"""
LiteLLM Client Adapter for Knowledge Graph System

Implements LLMClient interface using LiteLLM library.
Provides unified access to 100+ LLM providers.
"""

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
from src.infrastructure.llm.resilience import (
    get_circuit_breaker_registry,
    get_provider_rate_limiter,
)
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)

# Known max output token limits per model family.
# Used to clamp max_tokens before sending to the provider.
_MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    # Qwen / Dashscope
    "qwen-max": 8192,
    "qwen-plus": 8192,
    "qwen-turbo": 8192,
    "qwen-long": 8192,
    "qwen-vl-max": 8192,
    "qwen-vl-plus": 8192,
    # Deepseek
    "deepseek-chat": 8192,
    "deepseek-coder": 8192,
    "deepseek-reasoner": 8192,
    # ZhipuAI
    "glm-4": 4096,
    "glm-4-flash": 4096,
    # Kimi / Moonshot
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 8192,
    "moonshot-v1-128k": 8192,
}


def _clamp_max_tokens(model: str, max_tokens: int) -> int:
    """Clamp max_tokens to model-specific limits.

    Strips provider prefix (e.g. 'dashscope/qwen-max' -> 'qwen-max') before
    lookup. Returns original value if no known limit exists.
    """
    bare_model = model.split("/", 1)[-1] if "/" in model else model
    limit = _MODEL_MAX_OUTPUT_TOKENS.get(bare_model)
    if limit and max_tokens > limit:
        logger.debug(f"Clamping max_tokens {max_tokens} -> {limit} for model {model}")
        return limit
    return max_tokens


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

        # Decrypt and store API key for per-request passing (multi-tenant safe)
        self._api_key = self.config.api_key or self.encryption_service.decrypt(
            self.provider_config.api_key_encrypted
        )

        # Resolve base URL for this provider
        self._api_base = self._resolve_api_base()

        # Set LiteLLM environment variable for this provider (fallback)
        self._configure_litellm()

    def _resolve_api_base(self) -> str | None:
        """Resolve the API base URL for this provider."""
        provider_type = self.provider_config.provider_type.value
        if provider_type == "zai":
            return self.provider_config.base_url or "https://open.bigmodel.cn/api/paas/v4"
        elif provider_type == "kimi":
            return self.provider_config.base_url or "https://api.moonshot.cn/v1"
        elif self.provider_config.base_url:
            return self.provider_config.base_url
        return None

    def _configure_litellm(self):
        """Configure LiteLLM environment variables as fallback.

        NOTE: Per-request api_key is passed directly in completion_kwargs
        for multi-tenant safety. Env vars remain as fallback only.
        """
        import os

        api_key = self._api_key
        provider_type = self.provider_config.provider_type.value

        # Set env vars as fallback (some LiteLLM codepaths may still check them)
        env_key_map = {
            "openai": "OPENAI_API_KEY",
            "qwen": "DASHSCOPE_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "zai": "ZAI_API_KEY",
            "kimi": "KIMI_API_KEY",
        }
        env_var = env_key_map.get(provider_type)
        if env_var:
            os.environ[env_var] = api_key
        if provider_type == "gemini":
            os.environ["GEMINI_API_KEY"] = api_key

        logger.debug(f"Configured LiteLLM for provider: {provider_type}")

    def _build_completion_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        langfuse_context: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build common completion kwargs for LiteLLM calls.

        Centralizes api_key, api_base, temperature, retries, and
        langfuse metadata — previously duplicated across 3 methods.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": _clamp_max_tokens(model, max_tokens),
            "temperature": self.temperature if temperature is None else temperature,
            "api_key": self._api_key,
            **extra,
        }
        if self._api_base:
            kwargs["api_base"] = self._api_base

        if langfuse_context:
            langfuse_metadata = {
                "trace_name": langfuse_context.get("trace_name", "llm_call"),
                "trace_id": langfuse_context.get("trace_id"),
                "tags": langfuse_context.get("tags", []),
            }
            if langfuse_context.get("extra"):
                langfuse_metadata.update(langfuse_context["extra"])
            kwargs["metadata"] = langfuse_metadata

        settings = get_settings()
        kwargs["num_retries"] = settings.llm_max_retries
        return kwargs

    async def _execute_with_resilience(self, coro_factory):
        """Execute an LLM call with circuit breaker and rate limiter.

        Args:
            coro_factory: A callable that returns an awaitable (the LiteLLM call).

        Returns:
            The response from LiteLLM.
        """
        rate_limiter = get_provider_rate_limiter()
        circuit_breaker_registry = get_circuit_breaker_registry()
        provider_type = self.provider_config.provider_type
        circuit_breaker = circuit_breaker_registry.get(provider_type)

        if not circuit_breaker.can_execute():
            raise RateLimitError(
                f"Circuit breaker open for {provider_type.value}, "
                f"provider is temporarily unavailable"
            )

        try:
            async with await rate_limiter.acquire(provider_type):
                result = await coro_factory()
            circuit_breaker.record_success()
            return result
        except Exception as e:
            circuit_breaker.record_failure()
            error_message = str(e).lower()
            if any(
                kw in error_message
                for kw in ["rate limit", "quota", "throttling", "request denied", "429"]
            ):
                raise RateLimitError(f"Rate limit error: {e}")
            raise

    @staticmethod
    def _convert_message(m: Any) -> dict[str, Any]:
        """Convert a message to LiteLLM dict format, preserving tool-related fields.

        Handles both dict messages and Message objects. Preserves:
        - tool_calls (on assistant messages, required by Anthropic)
        - tool_call_id (on tool result messages, required by Anthropic)
        - name (on tool result messages)
        """
        if isinstance(m, dict):
            msg: dict[str, Any] = {
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
            }
            if "tool_calls" in m:
                msg["tool_calls"] = m["tool_calls"]
            if "tool_call_id" in m:
                msg["tool_call_id"] = m["tool_call_id"]
            if "name" in m:
                msg["name"] = m["name"]
            return msg
        return {"role": m.role, "content": m.content}

    async def generate(
        self,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = 4096,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Generate a non-streaming response with optional tool calling support.

        Args:
            messages: List of messages (dicts or Message objects)
            tools: Optional tool definitions for function calling
            temperature: Sampling temperature (defaults to client temperature)
            max_tokens: Maximum tokens to generate
            model_size: Which model to use (small or medium)
            langfuse_context: Optional context for Langfuse tracing
            **kwargs: Additional LiteLLM parameters

        Returns:
            Dict with content, tool_calls, and finish_reason
        """
        import litellm

        def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        litellm_messages = [self._convert_message(m) for m in messages]
        model = self._get_model_for_size(model_size)
        effective_temp = self.temperature if temperature is None else temperature

        # Check response cache (only for non-tool, deterministic calls)
        if self.cache and not tools and effective_temp == 0:
            from src.infrastructure.llm.cache import get_response_cache

            cache = get_response_cache()
            cached = await cache.get(litellm_messages, model=model, temperature=effective_temp)
            if cached is not None:
                return cached

        completion_kwargs = self._build_completion_kwargs(
            model=model,
            messages=litellm_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            langfuse_context=langfuse_context,
            stream=False,
            **kwargs,
        )
        if tools:
            completion_kwargs["tools"] = tools

        response = await self._execute_with_resilience(
            lambda: litellm.acompletion(**completion_kwargs)
        )

        if not response.choices:
            raise ValueError("No choices in response")

        choice = response.choices[0]
        message = _get_attr(choice, "message", {})

        content = _get_attr(message, "content", "") or ""
        tool_calls = _get_attr(message, "tool_calls", None)
        finish_reason = _get_attr(choice, "finish_reason", None)

        result = {
            "content": content,
            "tool_calls": tool_calls or [],
            "finish_reason": finish_reason,
        }

        # Include usage data for cost tracking
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            result["usage"] = {
                "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            }

        # Store in cache (only for non-tool, deterministic calls)
        if self.cache and not tools and effective_temp == 0:
            from src.infrastructure.llm.cache import get_response_cache

            cache = get_response_cache()
            await cache.set(litellm_messages, result, model=model, temperature=effective_temp)

        return result

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
            langfuse_context: Optional context for Langfuse tracing
            **kwargs: Additional arguments for litellm

        Yields:
            Response chunks
        """
        import litellm

        model = self._get_model_for_size(model_size)
        litellm_messages = [self._convert_message(m) for m in messages]

        completion_kwargs = self._build_completion_kwargs(
            model=model,
            messages=litellm_messages,
            max_tokens=max_tokens,
            langfuse_context=langfuse_context,
            stream=True,
            **kwargs,
        )

        rate_limiter = get_provider_rate_limiter()
        circuit_breaker_registry = get_circuit_breaker_registry()
        provider_type = self.provider_config.provider_type
        circuit_breaker = circuit_breaker_registry.get(provider_type)

        if not circuit_breaker.can_execute():
            raise RateLimitError(
                f"Circuit breaker open for {provider_type.value}, "
                f"provider is temporarily unavailable"
            )

        try:
            async with await rate_limiter.acquire(provider_type):
                response = await litellm.acompletion(**completion_kwargs)
                async for chunk in response:
                    yield chunk
            circuit_breaker.record_success()
        except Exception as e:
            circuit_breaker.record_failure()
            error_message = str(e).lower()
            if any(
                kw in error_message
                for kw in ["rate limit", "quota", "throttling", "request denied", "429"]
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
        Generate response using LiteLLM with optional structured output.

        Args:
            messages: List of messages (system, user, assistant)
            response_model: Optional Pydantic model for structured output
            max_tokens: Maximum tokens in response
            model_size: Which model to use (small or medium)
            langfuse_context: Optional context for Langfuse tracing

        Returns:
            Dictionary with response content or parsed structured data

        Raises:
            RateLimitError: If provider rate limit is hit
            Exception: For other errors
        """
        import litellm

        model = self._get_model_for_size(model_size)
        litellm_messages = [self._convert_message(m) for m in messages]

        completion_kwargs = self._build_completion_kwargs(
            model=model,
            messages=litellm_messages,
            max_tokens=max_tokens,
            langfuse_context=langfuse_context,
        )

        # Add structured output if requested
        if response_model:
            schema = response_model.model_json_schema()
            litellm_messages[0]["content"] += (
                f"\n\nRespond with a JSON object in the following format:\n\n{schema}"
            )
            try:
                completion_kwargs["response_format"] = {"type": "json_object"}
            except Exception as e:
                logger.debug(f"response_format not supported: {e}")

        try:
            response = await self._execute_with_resilience(
                lambda: litellm.acompletion(**completion_kwargs)
            )

            if not response.choices:
                raise ValueError("No choices in response")

            content = response.choices[0].message["content"]

            if response_model:
                try:
                    import json

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
                    logger.error(f"Failed to parse/validate JSON: {e}")
                    logger.error(f"Raw output: {content}")
                    raise

            return {"content": content}

        except RateLimitError:
            raise
        except Exception as e:
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
            # ZhipuAI uses 'zai/' prefix in LiteLLM (not 'zhipu/')
            return f"zai/{model}"
        elif provider_type == "kimi":
            # Moonshot AI (Kimi) uses OpenAI-compatible API
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
