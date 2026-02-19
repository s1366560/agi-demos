"""Helpers for provider credential handling."""

from __future__ import annotations

from src.domain.llm_providers.models import ProviderType

NO_API_KEY_SENTINEL = "__MEMSTACK_NO_API_KEY__"
LOCAL_OPTIONAL_KEY_PROVIDERS = {ProviderType.OLLAMA, ProviderType.LMSTUDIO}


def should_require_api_key(provider_type: ProviderType) -> bool:
    """Return whether provider requires a non-empty API key."""
    return provider_type not in LOCAL_OPTIONAL_KEY_PROVIDERS


def to_storable_api_key(provider_type: ProviderType, api_key: str | None) -> str:
    """Convert optional API key to storable plaintext before encryption."""
    normalized = (api_key or "").strip()
    if normalized:
        return normalized

    if should_require_api_key(provider_type):
        raise ValueError(f"API key is required for provider type '{provider_type.value}'")

    return NO_API_KEY_SENTINEL


def from_decrypted_api_key(api_key: str | None) -> str | None:
    """Convert decrypted plaintext to runtime API key."""
    if not api_key:
        return None
    if api_key == NO_API_KEY_SENTINEL:
        return None
    return api_key
