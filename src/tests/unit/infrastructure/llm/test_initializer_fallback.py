"""Tests for default provider initialization fallback behavior."""

import pytest

from src.domain.llm_providers.models import ProviderType
from src.infrastructure.llm import initializer


class _EmptyProviderService:
    """ProviderService stub that simulates an empty provider registry."""

    async def list_providers(self, include_inactive: bool = False):
        return []

    async def clear_all_providers(self) -> int:
        return 0


@pytest.mark.unit
async def test_initialize_defaults_falls_back_to_ollama_when_missing_api_key(monkeypatch):
    captured_config = {}

    async def fake_create_and_verify(provider_service, provider_config):
        captured_config["provider"] = provider_config
        return True

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(initializer, "ProviderService", _EmptyProviderService)
    monkeypatch.setattr(initializer, "_create_and_verify_provider", fake_create_and_verify)

    result = await initializer.initialize_default_llm_providers()

    assert result is True
    assert captured_config["provider"].provider_type == ProviderType.OLLAMA
    assert captured_config["provider"].is_default is True


@pytest.mark.unit
async def test_initialize_defaults_falls_back_to_ollama_for_unknown_provider(monkeypatch):
    captured_config = {}

    async def fake_create_and_verify(provider_service, provider_config):
        captured_config["provider"] = provider_config
        return True

    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")
    monkeypatch.setattr(initializer, "ProviderService", _EmptyProviderService)
    monkeypatch.setattr(initializer, "_create_and_verify_provider", fake_create_and_verify)

    result = await initializer.initialize_default_llm_providers()

    assert result is True
    assert captured_config["provider"].provider_type == ProviderType.OLLAMA
    assert captured_config["provider"].is_default is True
