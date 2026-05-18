"""Tests for default provider initialization fallback behavior."""

import pytest

from src.domain.llm_providers.models import OperationType, ProviderType
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
def test_build_provider_configs_splits_model_operations(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("OPENAI_RERANK_MODEL", "rerank-test")

    configs = initializer._build_provider_configs("openai")

    assert [config.operation_type for config in configs] == [
        OperationType.LLM,
        OperationType.EMBEDDING,
        OperationType.RERANK,
    ]
    assert configs[0].llm_model == "gpt-4o"
    assert configs[0].embedding_model is None
    assert configs[1].llm_model is None
    assert configs[1].embedding_model == "text-embedding-3-small"
    assert configs[2].llm_model is None
    assert configs[2].reranker_model == "rerank-test"


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
