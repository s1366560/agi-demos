"""Model limits registry for LLM providers.

Centralizes known model constraints (max output tokens, context window)
so that all components (LLM client, agent, compression engine) share a
single source of truth.

Resolution order:
  1. ``ProviderConfig.config`` JSONB overrides (per-tenant DB)
  2. ``ModelCatalogService`` (models_snapshot.json from models.dev)
  3. Static fallback dicts below (only for models absent from the catalog)

The static dicts are intentionally minimal — they cover only models that
are NOT present in the models.dev catalog snapshot (e.g. deepseek-coder,
glm-4, moonshot-v1-*). All other models are served by the catalog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.domain.llm_providers.models import ModelMetadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelLimits:
    """Token limits for a single model."""

    max_output_tokens: int | None = None
    context_window: int = 128_000
    max_input_tokens: int | None = None


# Known max output token limits per model family.
_MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    # Qwen / Dashscope (not in models.dev catalog)
    "qwen-long": 8192,
    # Deepseek (not in models.dev catalog)
    "deepseek-coder": 8192,
    # ZhipuAI (not in models.dev catalog)
    "glm-4": 4096,
    "glm-4-flash": 4096,
    # Kimi / Moonshot (not in models.dev catalog)
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 8192,
    "moonshot-v1-128k": 8192,
}

# Known max INPUT token limits for models where provider-enforced input caps
# are stricter than generic context_window-output calculations.
# Note: All models that were here (qwen-max, qwen-vl-max, qwen-vl-plus) are
# now served by the ModelCatalog snapshot. Dict retained for non-catalog models.
_MODEL_MAX_INPUT_TOKENS: dict[str, int] = {}

# Known context window sizes (total input + output) per model.
_MODEL_CONTEXT_WINDOW: dict[str, int] = {
    # Qwen / Dashscope (not in models.dev catalog)
    "qwen-long": 1_000_000,
    # Deepseek (not in models.dev catalog)
    "deepseek-coder": 65536,
    # ZhipuAI (not in models.dev catalog)
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    # Kimi / Moonshot (not in models.dev catalog)
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 32768,
    "moonshot-v1-128k": 131072,
}

_DEFAULT_CONTEXT_WINDOW = 128_000
_DEFAULT_INPUT_BUDGET_RATIO = 0.9
_DEFAULT_CHARS_PER_TOKEN = 3.0

# Safety ratio for practical input budgeting. This intentionally leaves headroom
# for tokenizer/provider counting differences and hidden system overhead.
_MODEL_INPUT_BUDGET_RATIO: dict[str, float] = {
    # Qwen / Dashscope (not in models.dev catalog)
    "qwen-long": 0.9,
}

# Fallback chars/token estimates for conservative char-based budgeting.
# Lower means stricter budgets.
_MODEL_CHARS_PER_TOKEN: dict[str, float] = {
    # Qwen / Dashscope (not in models.dev catalog)
    "qwen-long": 1.6,
}


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix (e.g. 'dashscope/qwen-max' -> 'qwen-max')."""
    return model.split("/", 1)[-1] if "/" in model else model


def _get_catalog_metadata(bare_name: str) -> ModelMetadata | None:
    """Try to look up *bare_name* in the model catalog.

    Returns the ``ModelMetadata`` instance or ``None`` when the catalog
    is unavailable or does not know the model.
    """
    try:
        from src.infrastructure.llm.model_catalog import (
            get_model_catalog_service,
        )

        return get_model_catalog_service().get_model(bare_name)
    except Exception:
        return None


def get_model_limits(
    model: str,
    provider_config_overrides: dict[str, Any] | None = None,
) -> ModelLimits:
    """Return token limits for *model*, with optional DB overrides.

    Args:
        model: Model identifier, optionally prefixed (e.g. ``dashscope/qwen-max``).
        provider_config_overrides: Optional dict from ``ProviderConfig.config``
            that may contain ``max_output_tokens``, ``context_window``, and/or
            ``max_input_tokens``.
    """
    bare = _strip_provider_prefix(model)

    # Try catalog first, fall back to static dicts
    meta = _get_catalog_metadata(bare)
    if meta is not None:
        max_out = meta.max_output_tokens
        ctx = meta.context_length or _DEFAULT_CONTEXT_WINDOW
        max_in = meta.max_input_tokens
    else:
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

    # Try catalog first
    meta = _get_catalog_metadata(bare)
    limit: int | None = None
    if meta is not None:
        limit = meta.max_output_tokens
    if limit is None:
        limit = _MODEL_MAX_OUTPUT_TOKENS.get(bare)

    if limit and max_tokens > limit:
        logger.debug(
            "Clamping max_tokens %d -> %d for model %s",
            max_tokens,
            limit,
            model,
        )
        return limit
    return max_tokens


def get_model_context_window(model: str) -> int:
    """Return the context window (input + output tokens) for *model*."""
    bare = _strip_provider_prefix(model)

    meta = _get_catalog_metadata(bare)
    if meta is not None and meta.context_length:
        return meta.context_length

    return _MODEL_CONTEXT_WINDOW.get(bare, _DEFAULT_CONTEXT_WINDOW)


def get_model_max_input_tokens(model: str, max_output_tokens: int | None = None) -> int:
    """Return the max INPUT token budget for *model*.

    Uses explicit per-model input caps when known, otherwise derives a safe input
    budget as ``context_window - max_output_tokens``.
    """
    bare = _strip_provider_prefix(model)

    # Try catalog for explicit input cap
    meta = _get_catalog_metadata(bare)
    if meta is not None and meta.max_input_tokens is not None:
        return meta.max_input_tokens

    # Fall back to static dict
    explicit_limit = _MODEL_MAX_INPUT_TOKENS.get(bare)
    if explicit_limit is not None:
        return explicit_limit

    context_window = get_model_context_window(model)
    effective_max_out: int
    if max_output_tokens is not None:
        effective_max_out = max_output_tokens
    elif meta is not None and meta.max_output_tokens:
        effective_max_out = meta.max_output_tokens
    else:
        effective_max_out = _MODEL_MAX_OUTPUT_TOKENS.get(bare, 4096)
    return max(1, context_window - max(0, effective_max_out))


def get_model_input_budget(model: str, max_output_tokens: int | None = None) -> int:
    """Return a conservative practical input budget for *model*.

    This applies a model-specific safety ratio on top of hard input limits to
    avoid provider-side length rejections caused by tokenizer mismatch.
    """
    bare = _strip_provider_prefix(model)
    hard_limit = get_model_max_input_tokens(model, max_output_tokens=max_output_tokens)

    # Try catalog for ratio
    meta = _get_catalog_metadata(bare)
    if meta is not None and meta.input_budget_ratio:
        ratio = meta.input_budget_ratio
    else:
        ratio = _MODEL_INPUT_BUDGET_RATIO.get(bare, _DEFAULT_INPUT_BUDGET_RATIO)

    return max(1, int(hard_limit * ratio))


def get_model_chars_per_token(model: str) -> float:
    """Return fallback chars/token estimate for *model*."""
    bare = _strip_provider_prefix(model)

    meta = _get_catalog_metadata(bare)
    if meta is not None and meta.chars_per_token:
        return meta.chars_per_token

    return _MODEL_CHARS_PER_TOKEN.get(bare, _DEFAULT_CHARS_PER_TOKEN)
