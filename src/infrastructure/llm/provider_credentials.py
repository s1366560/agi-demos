"""Helpers for provider credential handling."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from src.domain.llm_providers.models import (
    ProviderAuthMethod,
    ProviderCredentialRequiredError,
    ProviderType,
    UnsupportedProviderAuthError,
    provider_environment_variables,
)
from src.domain.llm_providers.security_policy import (
    environment_credential_endpoint_is_official,
)

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


def configured_provider_auth_method(
    provider_type: ProviderType,
    config: object,
) -> ProviderAuthMethod:
    """Read the structured persisted auth method, with legacy-compatible defaults."""
    raw_config = config if isinstance(config, Mapping) else {}
    configured = raw_config.get("auth_method")
    if configured is not None:
        try:
            return ProviderAuthMethod(str(configured))
        except ValueError as exc:
            raise UnsupportedProviderAuthError(
                "Unsupported persisted authentication method"
            ) from exc
    if provider_type in LOCAL_OPTIONAL_KEY_PROVIDERS:
        return ProviderAuthMethod.NONE
    return ProviderAuthMethod.API_KEY


def configured_environment_variable(
    provider_type: ProviderType,
    config: object,
) -> str | None:
    """Return a persisted environment reference only when it is provider allow-listed."""
    raw_config = config if isinstance(config, Mapping) else {}
    value = raw_config.get("environment_variable")
    normalized = value.strip() if isinstance(value, str) else ""
    if normalized and normalized in provider_environment_variables(provider_type):
        return normalized
    return None


def resolve_persisted_provider_credential(
    *,
    provider_type: ProviderType,
    config: Mapping[str, Any] | None,
    base_url: str | None,
    api_key_encrypted: str,
    decrypt: Callable[[str], str],
    getenv: Callable[[str], str | None] = os.getenv,
) -> str | None:
    """Resolve a persisted credential only at the runtime call boundary."""
    auth_method = configured_provider_auth_method(provider_type, config)
    if auth_method == ProviderAuthMethod.ENVIRONMENT:
        environment_variable = configured_environment_variable(provider_type, config)
        if environment_variable is None:
            raise ProviderCredentialRequiredError(
                "Persisted environment credential reference is invalid"
            )
        if not environment_credential_endpoint_is_official(provider_type, base_url):
            raise ProviderCredentialRequiredError(
                "Environment credentials require an official provider endpoint"
            )
        credential = (getenv(environment_variable) or "").strip()
        if not credential or credential == NO_API_KEY_SENTINEL:
            raise ProviderCredentialRequiredError("Environment credential is not configured")
        return credential

    if auth_method == ProviderAuthMethod.NONE:
        if provider_type not in LOCAL_OPTIONAL_KEY_PROVIDERS:
            raise UnsupportedProviderAuthError(
                "No-auth authentication is not supported for remote providers"
            )
        return None

    if auth_method != ProviderAuthMethod.API_KEY:
        raise UnsupportedProviderAuthError("Unsupported persisted authentication method")

    decrypted_credential = from_decrypted_api_key(decrypt(api_key_encrypted))
    if decrypted_credential is None:
        raise ProviderCredentialRequiredError("Provider credential is not configured")
    return decrypted_credential
