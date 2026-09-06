"""Startup never repairs inaccessible provider credentials by deleting stored records.

All storage and encryption dependencies are replaced before the real initializer runs.
No database fixture or production ProviderService instance is used.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.llm import initializer
from src.infrastructure.security import encryption_service


@pytest.fixture
def registry(monkeypatch):
    records = [
        SimpleNamespace(name=f"existing-{i}", api_key_encrypted="sealed", active=True)
        for i in range(3)
    ]

    async def list_records(include_inactive=False):
        return list(records) if include_inactive else [r for r in records if r.active]

    async def clear_records():
        count = len(records)
        records.clear()
        return count

    service = Mock()
    service.list_providers = AsyncMock(side_effect=list_records)
    service.clear_all_providers = AsyncMock(side_effect=clear_records)
    factory = Mock(return_value=service)
    monkeypatch.setattr(initializer, "ProviderService", factory)
    cipher = Mock()
    cipher.decrypt.return_value = "fixture-only"
    encryption = Mock(return_value=cipher)
    monkeypatch.setattr(encryption_service, "get_encryption_service", encryption)
    config = object()
    build = Mock(return_value=[config])
    create = AsyncMock(return_value=True)
    monkeypatch.setattr(initializer, "_build_provider_configs", build)
    monkeypatch.setattr(initializer, "_create_and_verify_provider", create)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    return SimpleNamespace(
        records=records,
        service=service,
        factory=factory,
        cipher=cipher,
        encryption=encryption,
        build=build,
        create=create,
    )


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["missing_key", "decrypt_failure"])
async def test_inaccessible_existing_providers_are_preserved(registry, failure):
    original = tuple(registry.records)
    if failure == "missing_key":
        registry.encryption.side_effect = ValueError("encryption unavailable")
    else:
        registry.cipher.decrypt.side_effect = ValueError("cannot decrypt")

    assert await initializer.initialize_default_llm_providers() is False
    assert tuple(registry.records) == original
    registry.factory.assert_called_once_with()
    registry.service.clear_all_providers.assert_not_awaited()
    registry.build.assert_not_called()
    registry.create.assert_not_awaited()


@pytest.mark.unit
async def test_healthy_existing_providers_skip_initialization(registry):
    original = tuple(registry.records)
    assert await initializer.initialize_default_llm_providers() is False
    assert tuple(registry.records) == original
    registry.service.clear_all_providers.assert_not_awaited()
    registry.create.assert_not_awaited()


@pytest.mark.unit
async def test_inactive_existing_providers_are_not_treated_as_an_empty_registry(registry):
    for record in registry.records:
        record.active = False
    original = tuple(registry.records)
    registry.cipher.decrypt.side_effect = ValueError("cannot decrypt")
    assert await initializer.initialize_default_llm_providers() is False
    assert tuple(registry.records) == original
    registry.service.clear_all_providers.assert_not_awaited()
    registry.create.assert_not_awaited()


@pytest.mark.unit
async def test_empty_registry_initializes_without_clearing(registry):
    registry.records.clear()
    assert await initializer.initialize_default_llm_providers() is True
    registry.service.clear_all_providers.assert_not_awaited()
    registry.create.assert_awaited_once()


@pytest.mark.unit
async def test_explicit_force_recreate_still_clears_and_creates(registry):
    assert await initializer.initialize_default_llm_providers(force_recreate=True) is True
    registry.service.clear_all_providers.assert_awaited_once_with()
    assert registry.records == []
    registry.create.assert_awaited_once()
    registry.encryption.assert_not_called()
