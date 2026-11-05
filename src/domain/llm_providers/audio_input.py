"""Explicit audio-input declarations; model names never imply capability."""

from __future__ import annotations

from typing import Any, cast

OPENAI_AUDIO_INPUT_ADAPTERS = frozenset({"openai", "openrouter", "lmstudio", "kimi", "volcengine"})
ARK_CHAT_AUDIO_MAX_FILE_BYTES = 25_000_000


class AudioInputLimitError(ValueError):
    """A protocol limit must stop the request rather than trigger provider failover."""

    status_code: int = 400


def validate_audio_input_size(provider_type: str, size_bytes: int) -> None:
    """Ark Chat accepts at most 25 MB of decoded audio in each inline input."""
    if provider_type == "volcengine" and size_bytes > ARK_CHAT_AUDIO_MAX_FILE_BYTES:
        raise AudioInputLimitError(
            "Invalid parameter: Ark Chat audio exceeds the 25 MB decoded file limit. "
            + "Use a shorter recording; the original recording remains available."
        )


def validate_audio_input_models(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("audio_input_models must be a list of at most 100 exact model IDs")
    items = cast(list[object], value)
    if len(items) > 100:
        raise ValueError("audio_input_models must be a list of at most 100 exact model IDs")
    models: list[str] = []
    for model in items:
        if (
            not isinstance(model, str)
            or not model
            or len(model) > 256
            or model != model.strip()
            or not model.isprintable()
        ):
            raise ValueError("audio_input_models requires unique nonempty exact model IDs")
        models.append(model)
    if len(set(models)) != len(models):
        raise ValueError("audio_input_models requires unique nonempty exact model IDs")
    return models


def declared_audio_input_models(config: dict[str, Any]) -> list[str]:
    """Malformed historical config is disabled, never interpreted as a wildcard."""
    try:
        return validate_audio_input_models(config.get("audio_input_models", []))
    except ValueError:
        return []


def validate_audio_input_declaration(
    provider_type: str,
    config: dict[str, Any],
    models: list[str | None],
) -> None:
    if "audio_input_models" not in config:
        return
    declared = validate_audio_input_models(config.get("audio_input_models", []))
    if declared and (
        provider_type not in OPENAI_AUDIO_INPUT_ADAPTERS or not set(declared).issubset(models)
    ):
        raise ValueError(
            "audio_input_models requires an OpenAI-wire provider and exact configured model IDs"
        )
