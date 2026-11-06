"""Provider guidance assembled from the catalog and the model snapshot."""

from __future__ import annotations

from typing import Any

from src.domain.llm_providers.models import ModelMetadata
from src.domain.llm_providers.provider_catalog import (
    ROLE_ORDER,
    role_defaults,
    static_provider_models,
)
from src.domain.llm_providers.role_fit import ModelSignals, assess_model_roles

_ROLE_PURPOSE = {
    "primary": "primary_chat",
    "fast": "fast_chat",
    "embedding": "embedding_index",
    "rerank": "rerank_passages",
    "voice": "voice_audio",
}


def _signals_from_metadata(
    model_id: str,
    metadata: ModelMetadata | None,
    *,
    audio_declared: bool,
) -> ModelSignals:
    if metadata is None:
        return ModelSignals(name=model_id, audio_declared=audio_declared)
    return ModelSignals(
        name=model_id,
        capabilities=frozenset(str(item) for item in metadata.capabilities),
        modalities=frozenset(metadata.modalities),
        known=True,
        deprecated=metadata.is_deprecated,
        audio_declared=audio_declared,
    )


def _profile(
    model_id: str,
    metadata: ModelMetadata | None,
    *,
    provider_type: str,
    audio_declared: bool,
) -> dict[str, Any]:
    signals = _signals_from_metadata(model_id, metadata, audio_declared=audio_declared)
    roles = assess_model_roles(signals, provider_type=provider_type)
    context_window = metadata.context_length if metadata is not None else None
    max_output = metadata.max_output_tokens if metadata is not None else None
    return {
        "id": model_id,
        "known": metadata is not None,
        "context_window": context_window,
        "max_output_tokens": max_output,
        "vision": bool(
            metadata
            and (
                any(str(item).lower() == "vision" for item in metadata.capabilities)
                or "image" in metadata.modalities
            )
        ),
        "tools": bool(metadata and metadata.supports_tool_call),
        "reasoning": bool(metadata and metadata.reasoning),
        "audio_input": any(role.role == "voice" and role.supported for role in roles),
        "deprecated": bool(metadata and metadata.is_deprecated),
        "input_cost_per_1m": metadata.input_cost_per_1m if metadata else None,
        "output_cost_per_1m": metadata.output_cost_per_1m if metadata else None,
        "roles": {
            role.role: {"supported": role.supported, "reason": role.reason} for role in roles
        },
    }


def _suggested_default(
    role: str,
    defaults: dict[str, str | None],
    roster: dict[str, list[str]],
) -> str | None:
    if role == "primary":
        chat = roster.get("chat", [])
        preferred = defaults.get("primary")
        if preferred and (not chat or preferred in chat):
            return preferred
        return chat[0] if chat else preferred
    if role == "fast":
        chat = roster.get("chat", [])
        preferred = defaults.get("fast")
        if preferred and (not chat or preferred in chat):
            return preferred
        return None
    category = "embedding" if role == "embedding" else "rerank" if role == "rerank" else ""
    models = roster.get(category, [])
    return models[0] if models else None


def build_provider_guidance(
    provider_type: str,
    *,
    audio_declared: set[str] | None = None,
) -> dict[str, Any]:
    """Return role purposes and compact capability profiles for suggested models."""
    from src.infrastructure.llm.model_catalog import get_model_catalog_service

    declared = audio_declared or set()
    defaults = role_defaults(provider_type)
    roster = static_provider_models(provider_type)
    model_ids: list[str] = []
    seen: set[str] = set()
    for model_id in (
        *roster.get("chat", []),
        *roster.get("embedding", []),
        *roster.get("rerank", []),
        *roster.get("vision", []),
    ):
        if model_id in seen:
            continue
        seen.add(model_id)
        model_ids.append(model_id)

    catalog = get_model_catalog_service()
    profiles = [
        _profile(
            model_id,
            catalog.get_model(model_id),
            provider_type=provider_type,
            audio_declared=model_id in declared,
        )
        for model_id in model_ids
    ]
    roles = []
    for role in ROLE_ORDER:
        supported = any(profile["roles"][role]["supported"] for profile in profiles)
        default_model = _suggested_default(role, defaults, roster)
        roster_has_role = bool(
            roster.get({"embedding": "embedding", "rerank": "rerank"}.get(role, ""))
        )
        available = (
            supported or roster_has_role or bool(default_model and role in {"primary", "fast"})
        )
        if available:
            reason = "ok"
        elif role == "embedding":
            reason = "provider_has_no_embedding_models"
        elif role == "rerank":
            reason = "provider_has_no_rerank_models"
        elif role == "voice":
            reason = "audio_input_not_declared"
        else:
            reason = "not_a_chat_model"
        roles.append(
            {
                "role": role,
                "purpose_code": _ROLE_PURPOSE[role],
                "default_model": default_model,
                "available": available,
                "reason": reason,
            }
        )
    return {
        "provider_type": provider_type,
        "roles": roles,
        "profiles": profiles,
    }
