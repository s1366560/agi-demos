"""Unit tests for provider model filtering (Phase 2).

Tests:
- ProviderConfig.is_model_allowed() logic
- ProviderResolutionService skipping disabled / model-blocked providers
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.application.services.provider_resolution_service import (
    ProviderResolutionService,
)
from src.domain.llm_providers.models import (
    NoActiveProviderError,
    ProviderConfig,
    ProviderType,
)


def _make_provider(**overrides: Any) -> ProviderConfig:
    """Create a ProviderConfig with sensible defaults."""
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "name": "test-provider",
        "provider_type": ProviderType.OPENAI,
        "tenant_id": "default",
        "llm_model": "gpt-4",
        "api_key_encrypted": "enc_key",
        "is_active": True,
        "is_default": False,
        "is_enabled": True,
        "allowed_models": [],
        "blocked_models": [],
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return ProviderConfig(**defaults)


# -------------------------------------------------------------------
# is_model_allowed tests
# -------------------------------------------------------------------


@pytest.mark.unit
class TestIsModelAllowed:
    """Tests for ProviderConfig.is_model_allowed()."""

    def test_empty_lists_allows_all(self) -> None:
        provider = _make_provider()
        assert provider.is_model_allowed("gpt-4") is True
        assert provider.is_model_allowed("anything") is True

    def test_whitelist_only_allows_matching(self) -> None:
        provider = _make_provider(allowed_models=["gpt-4", "gpt-3.5"])
        assert provider.is_model_allowed("gpt-4") is True
        assert provider.is_model_allowed("gpt-3.5-turbo") is True
        assert provider.is_model_allowed("claude-3") is False

    def test_blacklist_only_blocks_matching(self) -> None:
        provider = _make_provider(blocked_models=["gpt-4"])
        assert provider.is_model_allowed("gpt-4") is False
        assert provider.is_model_allowed("gpt-4-turbo") is False
        assert provider.is_model_allowed("gpt-3.5") is True

    def test_blacklist_precedence_over_whitelist(self) -> None:
        provider = _make_provider(
            allowed_models=["gpt-4"],
            blocked_models=["gpt-4-turbo"],
        )
        assert provider.is_model_allowed("gpt-4") is True
        assert provider.is_model_allowed("gpt-4-turbo") is False

    def test_prefix_matching(self) -> None:
        provider = _make_provider(allowed_models=["gpt-"])
        assert provider.is_model_allowed("gpt-4") is True
        assert provider.is_model_allowed("gpt-3.5-turbo") is True
        assert provider.is_model_allowed("claude-3") is False

    def test_case_insensitive(self) -> None:
        provider = _make_provider(
            allowed_models=["GPT-4"],
            blocked_models=["GPT-4-TURBO"],
        )
        assert provider.is_model_allowed("gpt-4") is True
        assert provider.is_model_allowed("gpt-4-turbo") is False
        assert provider.is_model_allowed("GPT-4-mini") is True

    def test_exact_match_in_whitelist(self) -> None:
        provider = _make_provider(allowed_models=["gpt-4"])
        assert provider.is_model_allowed("gpt-4") is True

    def test_no_match_in_whitelist(self) -> None:
        provider = _make_provider(allowed_models=["claude-3"])
        assert provider.is_model_allowed("gpt-4") is False


# -------------------------------------------------------------------
# ProviderResolutionService tests
# -------------------------------------------------------------------


@pytest.mark.unit
class TestProviderResolutionServiceFiltering:
    """Tests for ProviderResolutionService respecting
    is_enabled and model filtering."""

    def _make_service(
        self,
        *,
        tenant_provider: ProviderConfig | None = None,
        default_provider: ProviderConfig | None = None,
        fallback_provider: ProviderConfig | None = None,
    ) -> ProviderResolutionService:
        repo = AsyncMock()
        repo.find_tenant_provider = AsyncMock(return_value=tenant_provider)
        repo.find_default_provider = AsyncMock(return_value=default_provider)
        repo.find_first_active_provider = AsyncMock(return_value=fallback_provider)
        return ProviderResolutionService(repository=repo)

    async def test_resolve_enabled_provider(self) -> None:
        provider = _make_provider(is_enabled=True)
        svc = self._make_service(default_provider=provider)
        result = await svc.resolve_provider()
        assert result.id == provider.id

    async def test_skip_disabled_provider_to_fallback(self) -> None:
        disabled = _make_provider(name="disabled", is_enabled=False)
        fallback = _make_provider(name="fallback", is_enabled=True)
        svc = self._make_service(
            default_provider=disabled,
            fallback_provider=fallback,
        )
        result = await svc.resolve_provider()
        assert result.name == "fallback"

    async def test_skip_model_blocked_provider(self) -> None:
        blocked = _make_provider(
            name="blocked",
            blocked_models=["gpt-4"],
        )
        fallback = _make_provider(name="fallback")
        svc = self._make_service(
            default_provider=blocked,
            fallback_provider=fallback,
        )
        result = await svc.resolve_provider(model_id="gpt-4-turbo")
        assert result.name == "fallback"

    async def test_model_not_in_whitelist_skips(self) -> None:
        whitelist = _make_provider(
            name="whitelist",
            allowed_models=["claude-3"],
        )
        fallback = _make_provider(name="fallback")
        svc = self._make_service(
            default_provider=whitelist,
            fallback_provider=fallback,
        )
        result = await svc.resolve_provider(model_id="gpt-4")
        assert result.name == "fallback"

    async def test_model_in_whitelist_resolves(self) -> None:
        provider = _make_provider(
            allowed_models=["gpt-4"],
        )
        svc = self._make_service(default_provider=provider)
        result = await svc.resolve_provider(model_id="gpt-4-turbo")
        assert result.id == provider.id

    async def test_no_model_id_ignores_filtering(self) -> None:
        provider = _make_provider(
            allowed_models=["claude-3"],
            blocked_models=["gpt-4"],
        )
        svc = self._make_service(default_provider=provider)
        result = await svc.resolve_provider()
        assert result.id == provider.id

    async def test_all_providers_disabled_raises(self) -> None:
        disabled = _make_provider(is_enabled=False)
        svc = self._make_service(
            default_provider=disabled,
            fallback_provider=disabled,
        )
        with pytest.raises(NoActiveProviderError):
            await svc.resolve_provider()

    async def test_cache_key_includes_model_id(self) -> None:
        provider = _make_provider()
        svc = self._make_service(default_provider=provider)

        # Resolve with model_id
        await svc.resolve_provider(model_id="gpt-4")
        # Resolve without model_id
        await svc.resolve_provider()

        # Both should be cached under different keys
        assert len(svc.cache) == 2
        keys = list(svc.cache.keys())
        assert any("gpt-4" in k for k in keys)
        assert any("any" in k for k in keys)

    async def test_tenant_disabled_falls_to_default(self) -> None:
        tenant = _make_provider(name="tenant", is_enabled=False)
        default = _make_provider(name="default-provider", is_enabled=True)
        svc = self._make_service(
            tenant_provider=tenant,
            default_provider=default,
        )
        result = await svc.resolve_provider(tenant_id="t1")
        assert result.name == "default-provider"
