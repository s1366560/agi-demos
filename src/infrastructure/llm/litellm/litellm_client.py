"""
LiteLLM Client Adapter for Knowledge Graph System

Implements LLMClient interface using LiteLLM library.
Provides unified access to 100+ LLM providers.
"""

import logging
import math
import warnings
from typing import Any

from pydantic import BaseModel

# Suppress Pydantic serialization warnings from litellm's ModelResponse when
# providers inject dynamic fields (e.g. Anthropic's server_tool_use for web search).
# These warnings are harmless -- the field is simply not in the declared schema.
warnings.filterwarnings(
    "ignore",
    message=r"Pydantic serializer warnings",
    category=UserWarning,
)

from src.configuration.config import get_settings
from src.domain.llm_providers.llm_types import (
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
    RateLimitError,
)
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.model_registry import (
    clamp_max_tokens as _clamp_max_tokens,
    get_model_chars_per_token,
    get_model_input_budget,
    get_model_max_input_tokens,
)
from src.infrastructure.llm.provider_credentials import from_decrypted_api_key
from src.infrastructure.llm.resilience import (
    get_circuit_breaker_registry,
    get_provider_rate_limiter,
)
from src.infrastructure.security.encryption_service import get_encryption_service

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

        # Decrypt and store API key for per-request passing (multi-tenant safe)
        self._api_key = self.config.api_key or self.encryption_service.decrypt(
            self.provider_config.api_key_encrypted
        )
        self._api_key = from_decrypted_api_key(self._api_key)

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
        elif provider_type == "ollama":
            return self.provider_config.base_url or "http://localhost:11434"
        elif provider_type == "lmstudio":
            return self.provider_config.base_url or "http://localhost:1234/v1"
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
            "dashscope": "DASHSCOPE_API_KEY",
            "gemini": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "zai": "ZAI_API_KEY",
            "kimi": "KIMI_API_KEY",
        }
        env_var = env_key_map.get(provider_type)
        if env_var and api_key:
            os.environ[env_var] = api_key
        if provider_type == "gemini" and api_key:
            os.environ["GEMINI_API_KEY"] = api_key

        logger.debug(f"Configured LiteLLM for provider: {provider_type}")

    def _build_completion_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        langfuse_context: dict[str, Any] | None = None,
        **extra: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """Build common completion kwargs for LiteLLM calls.

        Centralizes api_key, api_base, temperature, retries, and
        langfuse metadata — previously duplicated across 3 methods.
        """
        clamped_max_tokens = _clamp_max_tokens(model, max_tokens)
        normalized_messages = self._trim_messages_to_input_limit(
            model=model,
            messages=messages,
            max_tokens=clamped_max_tokens,
        )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": normalized_messages,
            "max_tokens": clamped_max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            **extra,
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
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

    @staticmethod
    def _estimate_input_tokens(model: str, messages: list[dict[str, Any]]) -> int | None:
        """Estimate input tokens using LiteLLM tokenizer for provider-aware counting."""
        import litellm

        try:
            return int(litellm.token_counter(model=model, messages=messages))
        except Exception as e:
            logger.debug(f"Failed to estimate prompt tokens for {model}: {e}")
            return None

    @staticmethod
    def _estimate_message_chars(messages: list[dict[str, Any]]) -> int:
        """Estimate message size in characters for conservative fallback budgeting."""
        total_chars = 0
        for msg in messages:
            total_chars += len(str(msg.get("role", "")))
            total_chars += len(str(msg.get("name", "")))
            total_chars += len(str(msg.get("tool_call_id", "")))
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            else:
                total_chars += len(str(content))
            tool_calls = msg.get("tool_calls")
            if tool_calls is not None:
                total_chars += len(str(tool_calls))
        return total_chars

    def _estimate_effective_input_tokens(self, model: str, messages: list[dict[str, Any]]) -> int:
        """Estimate effective input tokens using tokenizer + char-based guard."""
        token_count = self._estimate_input_tokens(model, messages)
        chars = self._estimate_message_chars(messages)
        chars_per_token = max(0.1, get_model_chars_per_token(model))
        char_estimate = math.ceil(chars / chars_per_token)
        if token_count is None:
            return char_estimate
        return max(token_count, char_estimate)

    @staticmethod
    def _truncate_text_middle(text: str, max_chars: int) -> str:
        """Truncate text while preserving both head and tail context."""
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        marker = "\n...[truncated]...\n"
        if max_chars <= len(marker) + 20:
            return text[-max_chars:]
        head = (max_chars - len(marker)) // 2
        tail = max_chars - len(marker) - head
        return f"{text[:head]}{marker}{text[-tail:]}"

    def _truncate_largest_message(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
        current_tokens: int,
        prefer_non_system: bool,
    ) -> bool:
        """Truncate the largest string content message in-place."""
        candidates = [
            idx
            for idx, msg in enumerate(messages)
            if isinstance(msg.get("content"), str) and msg.get("content")
        ]
        if not candidates:
            return False
        if prefer_non_system:
            non_system = [idx for idx in candidates if messages[idx].get("role") != "system"]
            if non_system:
                candidates = non_system
        target_idx = max(candidates, key=lambda idx: len(str(messages[idx].get("content", ""))))
        original = str(messages[target_idx]["content"])
        if not original:
            return False
        shrink_ratio = min(0.95, max(0.05, target_tokens / max(1, current_tokens)))
        next_chars = max(128, int(len(original) * shrink_ratio))
        if next_chars >= len(original):
            next_chars = max(1, len(original) - max(32, len(original) // 10))
        messages[target_idx]["content"] = self._truncate_text_middle(original, next_chars)
        return True

    def _trim_messages_to_input_limit(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Trim oldest context when estimated input tokens exceed model input budget."""
        hard_input_limit = get_model_max_input_tokens(model, max_tokens)
        input_limit = get_model_input_budget(model, max_tokens)
        token_count = self._estimate_effective_input_tokens(model, messages)
        if token_count <= input_limit:
            return messages

        original_count = token_count
        trimmed = [dict(msg) for msg in messages]
        keep_system_prompt = bool(trimmed and trimmed[0].get("role") == "system")
        min_messages = 2 if keep_system_prompt else 1

        while token_count > input_limit and len(trimmed) > min_messages:
            del trimmed[1 if keep_system_prompt else 0]
            token_count = self._estimate_effective_input_tokens(model, trimmed)

        # Last resort: drop system prompt if still above limit.
        if token_count > input_limit and keep_system_prompt and len(trimmed) > 1:
            del trimmed[0]
            token_count = self._estimate_effective_input_tokens(model, trimmed)

        # Final fallback: truncate largest remaining content until within budget.
        truncate_attempts = 0
        while token_count > input_limit and truncate_attempts < 8:
            updated = self._truncate_largest_message(
                messages=trimmed,
                target_tokens=input_limit,
                current_tokens=token_count,
                prefer_non_system=True,
            )
            if not updated:
                break
            token_count = self._estimate_effective_input_tokens(model, trimmed)
            truncate_attempts += 1

        if token_count > input_limit:
            logger.warning(
                "Prompt still exceeds input budget after trimming: "
                f"model={model}, tokens={token_count}, budget={input_limit}, hard_limit={hard_input_limit}"
            )
            return trimmed

        logger.info(
            "Trimmed prompt to input budget: "
            f"model={model}, tokens={original_count}->{token_count}, "
            f"budget={input_limit}, hard_limit={hard_input_limit}, "
            f"messages={len(messages)}->{len(trimmed)}"
        )
        return trimmed

    @staticmethod
    def _is_client_error(e: Exception) -> bool:
        """Check if an exception is a client-side error (400-level).

        Client errors (invalid params, input too long, etc.) should NOT trip
        the circuit breaker because the provider is healthy — the request
        was simply invalid.
        """
        error_str = str(e).lower()
        client_indicators = [
            "invalidparameter",
            "invalid_parameter",
            "invalid parameter",
            "bad request",
            "400",
            "invalid_request_error",
            "context_length_exceeded",
            "content_policy_violation",
        ]
        return any(indicator in error_str for indicator in client_indicators)

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
            if not self._is_client_error(e):
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
        **kwargs: Any,  # noqa: ANN401
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
            if not self._is_client_error(e):
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
        # For 'dashscope', LiteLLM might not auto-detect 'qwen-max' as a specific provider if not in its default list or if strict.
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
        elif provider_type == "ollama":
            return f"ollama/{model}"
        elif provider_type == "lmstudio":
            # LM Studio exposes OpenAI-compatible API.
            return f"openai/{model}"
        # For Dashscope, let's try explicitly adding the provider if it's missing?
        # LiteLLM docs say for some providers you need provider/model.
        # But for Qwen/Dashscope, it often works with just model if DASHSCOPE_API_KEY is set.
        # The error suggests LiteLLM doesn't recognize 'qwen-max' as belonging to a provider it has credentials for,
        # OR it needs the provider prefix.

        # If using Dashscope (Qwen) via standard litellm logic,
        # sometimes "qwen/" prefix helps disambiguate if it's not default.
        if provider_type == "dashscope":
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
