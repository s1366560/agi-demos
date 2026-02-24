"""Model limits registry for LLM providers.

Centralizes known model constraints (max output tokens, context window)
so that all components (LLM client, agent, compression engine) share a
single source of truth.

Override mechanism: ProviderConfig.config JSONB can store custom limits
under the keys ``max_output_tokens``, ``context_window``, and ``max_input_tokens``, which take
precedence over the static tables below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelLimits:
    """Token limits for a single model."""

    max_output_tokens: int | None = None
    context_window: int = 128_000
    max_input_tokens: int | None = None


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

# Known max INPUT token limits for models where provider-enforced input caps
# are stricter than generic context_window-output calculations.
_MODEL_MAX_INPUT_TOKENS: dict[str, int] = {
    # Qwen / Dashscope
    "qwen-max": 30_720,
    "qwen-vl-max": 30_720,
    "qwen-vl-plus": 30_720,
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
_DEFAULT_INPUT_BUDGET_RATIO = 0.9
_DEFAULT_CHARS_PER_TOKEN = 3.0

# Safety ratio for practical input budgeting. This intentionally leaves headroom
# for tokenizer/provider counting differences and hidden system overhead.
_MODEL_INPUT_BUDGET_RATIO: dict[str, float] = {
    "qwen-max": 0.85,
    "qwen-plus": 0.9,
    "qwen-turbo": 0.9,
    "qwen-long": 0.9,
    "qwen-vl-max": 0.85,
    "qwen-vl-plus": 0.85,
}

# Fallback chars/token estimates for conservative char-based budgeting.
# Lower means stricter budgets.
_MODEL_CHARS_PER_TOKEN: dict[str, float] = {
    "qwen-max": 1.2,
    "qwen-plus": 1.4,
    "qwen-turbo": 1.4,
    "qwen-long": 1.6,
    "qwen-vl-max": 1.2,
    "qwen-vl-plus": 1.2,
}


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix (e.g. 'dashscope/qwen-max' -> 'qwen-max')."""
    return model.split("/", 1)[-1] if "/" in model else model


def get_model_limits(
    model: str,
    provider_config_overrides: dict | None = None,
) -> ModelLimits:
    """Return token limits for *model*, with optional DB overrides.

    Args:
        model: Model identifier, optionally prefixed (e.g. ``dashscope/qwen-max``).
        provider_config_overrides: Optional dict from ``ProviderConfig.config``
            that may contain ``max_output_tokens``, ``context_window``, and/or
            ``max_input_tokens``.
    """
    bare = _strip_provider_prefix(model)
    max_out = _MODEL_MAX_OUTPUT_TOKENS.get(bare)
    ctx = _MODEL_CONTEXT_WINDOW.get(bare, _DEFAULT_CONTEXT_WINDOW)
    max_in = _MODEL_MAX_INPUT_TOKENS.get(bare)

    if provider_config_overrides:
        max_out = provider_config_overrides.get("max_output_tokens", max_out)
        ctx = provider_config_overrides.get("context_window", ctx)
        max_in = provider_config_overrides.get("max_input_tokens", max_in)

    return ModelLimits(
        max_output_tokens=max_out,
        context_window=ctx,
        max_input_tokens=max_in,
    )


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


def get_model_max_input_tokens(model: str, max_output_tokens: int | None = None) -> int:
    """Return the max INPUT token budget for *model*.

    Uses explicit per-model input caps when known, otherwise derives a safe input
    budget as ``context_window - max_output_tokens``.
    """
    bare = _strip_provider_prefix(model)

    explicit_limit = _MODEL_MAX_INPUT_TOKENS.get(bare)
    if explicit_limit is not None:
        return explicit_limit

    context_window = _MODEL_CONTEXT_WINDOW.get(bare, _DEFAULT_CONTEXT_WINDOW)
    if max_output_tokens is None:
        max_output_tokens = _MODEL_MAX_OUTPUT_TOKENS.get(bare, 4096)

    return max(1, context_window - max(0, max_output_tokens))


def get_model_input_budget(model: str, max_output_tokens: int | None = None) -> int:
    """Return a conservative practical input budget for *model*.

    This applies a model-specific safety ratio on top of hard input limits to
    avoid provider-side length rejections caused by tokenizer mismatch.
    """
    bare = _strip_provider_prefix(model)
    hard_limit = get_model_max_input_tokens(model, max_output_tokens=max_output_tokens)
    ratio = _MODEL_INPUT_BUDGET_RATIO.get(bare, _DEFAULT_INPUT_BUDGET_RATIO)
    return max(1, int(hard_limit * ratio))


def get_model_chars_per_token(model: str) -> float:
    """Return fallback chars/token estimate for *model*."""
    bare = _strip_provider_prefix(model)
    return _MODEL_CHARS_PER_TOKEN.get(bare, _DEFAULT_CHARS_PER_TOKEN)
