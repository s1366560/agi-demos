"""Provider environment auto-configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.domain.llm_providers.models import ProviderType
from src.domain.llm_providers.provider_catalog import AUTO_DETECT_ENV, ENV_ALIASES, env_profiles


@dataclass(frozen=True)
class _EnvField:
    """Environment field config with candidate keys and fallback default."""

    env_vars: tuple[str, ...]
    default: str | None = None


@dataclass(frozen=True)
class _ProviderEnvProfile:
    """Environment profile for one provider type."""

    api_key: _EnvField
    llm_model: _EnvField
    llm_small_model: _EnvField = _EnvField(())
    embedding_model: _EnvField = _EnvField(())
    reranker_model: _EnvField = _EnvField(())
    base_url: _EnvField = _EnvField(())


@dataclass(frozen=True)
class ProviderEnvDefaults:
    """Resolved provider defaults from environment variables."""

    provider_type: ProviderType
    api_key: str | None
    api_key_source: str | None
    base_url: str | None
    base_url_source: str | None
    llm_model: str | None
    llm_model_source: str | None
    llm_small_model: str | None
    llm_small_model_source: str | None
    embedding_model: str | None
    embedding_model_source: str | None
    reranker_model: str | None
    reranker_model_source: str | None
    api_key_env_vars: tuple[str, ...]


PROVIDER_TYPE_MAP: dict[str, ProviderType] = {
    alias: ProviderType(provider_type) for alias, provider_type in ENV_ALIASES.items()
}

PROVIDER_AUTO_DETECT: list[tuple[str, str]] = list(AUTO_DETECT_ENV)


def _build_env_profiles() -> dict[ProviderType, _ProviderEnvProfile]:
    """Build environment profiles from the shared provider catalog."""
    profiles: dict[ProviderType, _ProviderEnvProfile] = {}
    for profile in env_profiles():
        profiles[ProviderType(profile.provider_type)] = _ProviderEnvProfile(
            api_key=_EnvField(profile.api_key_vars),
            llm_model=_EnvField(profile.model_vars, profile.model_default),
            llm_small_model=_EnvField(profile.small_vars, profile.small_default),
            embedding_model=_EnvField(profile.embedding_vars, profile.embedding_default),
            reranker_model=_EnvField(profile.rerank_vars, profile.rerank_default),
            base_url=_EnvField(profile.base_url_vars, profile.base_url_default),
        )
    return profiles


_ENV_PROFILES: dict[ProviderType, _ProviderEnvProfile] = _build_env_profiles()


def provider_type_from_name(provider_name: str) -> ProviderType | None:
    """Resolve provider alias/name to ProviderType."""
    normalized = provider_name.strip().lower()
    return PROVIDER_TYPE_MAP.get(normalized)


def detect_provider_name_from_env(default_provider: str = "gemini") -> str:
    """Auto-detect provider name from known environment variables."""
    for env_var, provider_name in PROVIDER_AUTO_DETECT:
        if os.getenv(env_var):
            return provider_name
    return default_provider


def _resolve_field(field: _EnvField) -> tuple[str | None, str | None]:
    for env_var in field.env_vars:
        raw_value = os.getenv(env_var)
        if raw_value and raw_value.strip():
            return raw_value.strip(), env_var
    if field.default is None:
        return None, None
    return field.default, None


def resolve_provider_env_defaults(provider_type: ProviderType) -> ProviderEnvDefaults:
    """Resolve provider defaults and API key from environment."""
    profile = _ENV_PROFILES.get(provider_type)
    if profile is None:
        return ProviderEnvDefaults(
            provider_type=provider_type,
            api_key=None,
            api_key_source=None,
            base_url=None,
            base_url_source=None,
            llm_model=None,
            llm_model_source=None,
            llm_small_model=None,
            llm_small_model_source=None,
            embedding_model=None,
            embedding_model_source=None,
            reranker_model=None,
            reranker_model_source=None,
            api_key_env_vars=(),
        )

    api_key, api_key_source = _resolve_field(profile.api_key)
    base_url, base_url_source = _resolve_field(profile.base_url)
    llm_model, llm_model_source = _resolve_field(profile.llm_model)
    llm_small_model, llm_small_model_source = _resolve_field(profile.llm_small_model)
    embedding_model, embedding_model_source = _resolve_field(profile.embedding_model)
    reranker_model, reranker_model_source = _resolve_field(profile.reranker_model)

    return ProviderEnvDefaults(
        provider_type=provider_type,
        api_key=api_key,
        api_key_source=api_key_source,
        base_url=base_url,
        base_url_source=base_url_source,
        llm_model=llm_model,
        llm_model_source=llm_model_source,
        llm_small_model=llm_small_model,
        llm_small_model_source=llm_small_model_source,
        embedding_model=embedding_model,
        embedding_model_source=embedding_model_source,
        reranker_model=reranker_model,
        reranker_model_source=reranker_model_source,
        api_key_env_vars=profile.api_key.env_vars,
    )
