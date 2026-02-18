"""Model limits registry for LLM providers.

Centralizes known model constraints (max output tokens, context window)
so that all components (LLM client, agent, compression engine) share a
single source of truth.

Override mechanism: ProviderConfig.config JSONB can store custom limits
under the keys ``max_output_tokens`` and ``context_window``, which take
precedence over the static tables below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelLimits:
    """Token limits for a single model."""

    max_output_tokens: Optional[int] = None
    context_window: int = 128_000


# Known max output token limits per model family.
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

# Known context window sizes (total input + output) per model.
_MODEL_CONTEXT_WINDOW: dict[str, int] = {
    # Qwen / Dashscope
    "qwen-max": 32768,
    "qwen-plus": 131072,
    "qwen-turbo": 131072,
    "qwen-long": 1_000_000,
    "qwen-vl-max": 32768,
    "qwen-vl-plus": 32768,
    # Deepseek
    "deepseek-chat": 65536,
    "deepseek-coder": 65536,
    "deepseek-reasoner": 65536,
    # ZhipuAI
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    # Kimi / Moonshot
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 32768,
    "moonshot-v1-128k": 131072,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8192,
    # Anthropic
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    # Gemini
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
}

_DEFAULT_CONTEXT_WINDOW = 128_000


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix (e.g. 'dashscope/qwen-max' -> 'qwen-max')."""
    return model.split("/", 1)[-1] if "/" in model else model


def get_model_limits(
    model: str,
    provider_config_overrides: Optional[dict] = None,
) -> ModelLimits:
    """Return token limits for *model*, with optional DB overrides.

    Args:
        model: Model identifier, optionally prefixed (e.g. ``dashscope/qwen-max``).
        provider_config_overrides: Optional dict from ``ProviderConfig.config``
            that may contain ``max_output_tokens`` and/or ``context_window``.
    """
    bare = _strip_provider_prefix(model)
    max_out = _MODEL_MAX_OUTPUT_TOKENS.get(bare)
    ctx = _MODEL_CONTEXT_WINDOW.get(bare, _DEFAULT_CONTEXT_WINDOW)

    if provider_config_overrides:
        max_out = provider_config_overrides.get("max_output_tokens", max_out)
        ctx = provider_config_overrides.get("context_window", ctx)

    return ModelLimits(max_output_tokens=max_out, context_window=ctx)


def clamp_max_tokens(model: str, max_tokens: int) -> int:
    """Clamp *max_tokens* to the model-specific output limit.

    Returns the original value when no known limit exists.
    """
    bare = _strip_provider_prefix(model)
    limit = _MODEL_MAX_OUTPUT_TOKENS.get(bare)
    if limit and max_tokens > limit:
        logger.debug(f"Clamping max_tokens {max_tokens} -> {limit} for model {model}")
        return limit
    return max_tokens


def get_model_context_window(model: str) -> int:
    """Return the context window (input + output tokens) for *model*."""
    bare = _strip_provider_prefix(model)
    return _MODEL_CONTEXT_WINDOW.get(bare, _DEFAULT_CONTEXT_WINDOW)
