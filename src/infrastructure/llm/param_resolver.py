"""LLM parameter resolution with multi-layer precedence chain.

Resolution chain (highest → lowest priority):
  1. ``user_overrides``  — per-request overrides from the caller
  2. ``provider_config``  — per-tenant/per-provider config from DB
  3. Model metadata defaults — from models.dev snapshot via catalog
  4. Omit (parameter not included in the returned dict)

Unsupported parameters are silently dropped based on
``ModelMetadata.supports_*`` flags from the catalog.

Temperature and top_p are clamped to the model's allowed range
(``temperature_range`` / ``top_p_range``) when available.

The resolved dict always includes ``drop_params=True`` so that
LiteLLM silently drops any parameter the underlying provider
doesn't recognise rather than raising an error.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.llm_providers.models import ModelMetadata
from src.infrastructure.llm.model_catalog import ModelCatalogService

logger = logging.getLogger(__name__)

# Parameters managed by the resolver alongside their
# ``ModelMetadata`` support-flag name and default-value field name.
# (param_key, support_flag, default_field)
_PARAM_SPEC: list[tuple[str, str | None, str | None]] = [
    ("temperature", "supports_temperature", "default_temperature"),
    ("top_p", "supports_top_p", "default_top_p"),
    ("frequency_penalty", "supports_frequency_penalty", "default_frequency_penalty"),
    ("presence_penalty", "supports_presence_penalty", "default_presence_penalty"),
    ("seed", "supports_seed", "default_seed"),
    ("stop", "supports_stop", "default_stop"),
    ("response_format", "supports_response_format", None),
    ("max_tokens", None, None),  # always supported, no default lookup
]


def resolve_llm_params(
    model_name: str,
    *,
    user_overrides: dict[str, Any] | None = None,
    provider_config: dict[str, Any] | None = None,
    catalog: ModelCatalogService | None = None,
) -> dict[str, Any]:
    """Build a resolved parameter dict for a single LLM call.

    Parameters
    ----------
    model_name:
        The model identifier (e.g. ``"gpt-4o"``, ``"qwen-max"``).
    user_overrides:
        Per-request overrides supplied by the caller.  Highest priority.
    provider_config:
        Per-tenant provider configuration from the database
        (``llm_provider_configs.config`` JSONB column).
    catalog:
        ``ModelCatalogService`` instance for metadata lookups.

    Returns
    -------
    dict[str, Any]
        Resolved parameters ready for ``litellm.completion(**params)``.
        Always includes ``drop_params=True``.
    """
    user_overrides = user_overrides or {}
    provider_config = provider_config or {}

    meta = _get_metadata(model_name, catalog)

    resolved: dict[str, Any] = {}
    for param_key, support_flag, default_field in _PARAM_SPEC:
        value = _resolve_single(
            param_key,
            support_flag=support_flag,
            default_field=default_field,
            user_overrides=user_overrides,
            provider_config=provider_config,
            meta=meta,
        )
        if value is not None:
            resolved[param_key] = value

    # Clamp numeric ranges
    _clamp_range(resolved, "temperature", meta)
    _clamp_range(resolved, "top_p", meta)

    # Always tell LiteLLM to silently drop unrecognised params
    resolved["drop_params"] = True
    return resolved


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _get_metadata(
    model_name: str,
    catalog: ModelCatalogService | None,
) -> ModelMetadata | None:
    """Attempt to look up model metadata from the catalog."""
    if catalog is None:
        return None
    meta = catalog.get_model_fuzzy(model_name)
    if meta is None:
        logger.debug("param_resolver: no catalog entry for %r", model_name)
    return meta


def _resolve_single(
    param_key: str,
    *,
    support_flag: str | None,
    default_field: str | None,
    user_overrides: dict[str, Any],
    provider_config: dict[str, Any],
    meta: ModelMetadata | None,
) -> Any:  # noqa: ANN401
    """Resolve a single parameter through the precedence chain.

    Returns the resolved value, or ``None`` to signal "omit this param".
    """
    # Walk the precedence chain: user > provider > model default
    value: Any = None
    found = False

    if param_key in user_overrides:
        value = user_overrides[param_key]
        found = True
    elif param_key in provider_config:
        value = provider_config[param_key]
        found = True
    elif default_field is not None and meta is not None:
        default_val = getattr(meta, default_field, None)
        if default_val is not None:
            value = default_val
            found = True

    if not found:
        return None

    # Even explicitly-set values are dropped if unsupported
    if not _is_supported(param_key, support_flag, meta):
        logger.debug(
            "param_resolver: dropping %r (unsupported by model)",
            param_key,
        )
        return None

    return value


def _is_supported(
    param_key: str,
    support_flag: str | None,
    meta: ModelMetadata | None,
) -> bool:
    """Check whether a parameter is supported by the model.

    When no metadata is available, we optimistically assume support
    (LiteLLM's ``drop_params=True`` handles the rest).
    """
    if meta is None:
        return True
    if support_flag is None:
        # No flag defined for this param (e.g. max_tokens) — always ok
        return True
    return bool(getattr(meta, support_flag, True))


def _clamp_range(
    resolved: dict[str, Any],
    param_key: str,
    meta: ModelMetadata | None,
) -> None:
    """Clamp a numeric parameter to the model's allowed range."""
    if param_key not in resolved or meta is None:
        return

    range_field = f"{param_key}_range"
    allowed_range: list[float] | None = getattr(meta, range_field, None)
    if allowed_range is None or len(allowed_range) != 2:
        return

    value = resolved[param_key]
    if not isinstance(value, (int, float)):
        return

    low, high = allowed_range
    clamped = max(low, min(high, float(value)))
    if clamped != float(value):
        logger.debug(
            "param_resolver: clamped %s from %s to %s (range %s)",
            param_key,
            value,
            clamped,
            allowed_range,
        )
        resolved[param_key] = clamped
