"""Unit tests for :mod:`src.infrastructure.llm.model_pool`."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.domain.llm_providers.models import OperationType, ProviderConfig
from src.infrastructure.llm.model_catalog import ModelCatalogService
from src.infrastructure.llm.model_pool import (
    CandidateModel,
    ModelPoolService,
    PoolFilter,
)

pytestmark = pytest.mark.unit


@dataclass
class _FakeResolution:
    providers: list[ProviderConfig] = field(default_factory=list)
    calls: list[tuple[str | None, OperationType]] = field(default_factory=list)

    async def list_pool_providers(
        self, tenant_id: str | None, operation_type: OperationType
    ) -> list[ProviderConfig]:
        self.calls.append((tenant_id, operation_type))
        return list(self.providers)


def _catalog() -> ModelCatalogService:
    return ModelCatalogService()


class TestModelPoolService:
    async def test_expand_provider_yields_primary_small_and_secondary(
        self, provider_config: ProviderConfig
    ) -> None:
        # provider_config fixture has llm_model=test-model, llm_small_model=test-small-model
        object.__setattr__(provider_config, "secondary_models", ["extra-1", "extra-2"])
        object.__setattr__(provider_config, "pool_weight", 2.0)
        resolution = _FakeResolution(providers=[provider_config])
        pool = ModelPoolService(resolution_service=resolution, catalog=_catalog())

        cands = await pool.list_candidates(tenant_id="t1")

        names = [c.model_name for c in cands]
        assert names == ["test-model", "test-small-model", "extra-1", "extra-2"]
        small = next(c for c in cands if c.model_name == "test-small-model")
        assert small.tier == "small"
        assert all(c.weight == 2.0 for c in cands)
        assert resolution.calls == [("t1", OperationType.LLM)]

    async def test_caches_provider_list(self, provider_config: ProviderConfig) -> None:
        resolution = _FakeResolution(providers=[provider_config])
        pool = ModelPoolService(resolution_service=resolution, catalog=_catalog())

        await pool.list_candidates(tenant_id="t1")
        await pool.list_candidates(tenant_id="t1")

        assert len(resolution.calls) == 1

    async def test_exclude_keys_drops_candidate(
        self, provider_config: ProviderConfig
    ) -> None:
        resolution = _FakeResolution(providers=[provider_config])
        pool = ModelPoolService(resolution_service=resolution, catalog=_catalog())

        all_cands = await pool.list_candidates(tenant_id="t1")
        first_key = all_cands[0].candidate_key

        filtered = await pool.list_candidates(
            tenant_id="t1",
            pool_filter=PoolFilter(exclude_keys=frozenset([first_key])),
        )
        assert first_key not in {c.candidate_key for c in filtered}

    async def test_tier_filter_relaxes_when_empty(
        self, provider_config: ProviderConfig
    ) -> None:
        # No tier configured on provider; strict "large" filter would
        # match nothing — pool relaxes and returns all candidates.
        resolution = _FakeResolution(providers=[provider_config])
        pool = ModelPoolService(resolution_service=resolution, catalog=_catalog())

        cands = await pool.list_candidates(
            tenant_id="t1", pool_filter=PoolFilter(tier="large")
        )
        assert len(cands) >= 1

    async def test_blocked_model_is_skipped(
        self, provider_config: ProviderConfig
    ) -> None:
        object.__setattr__(provider_config, "blocked_models", ["test-small-model"])
        resolution = _FakeResolution(providers=[provider_config])
        pool = ModelPoolService(resolution_service=resolution, catalog=_catalog())

        cands = await pool.list_candidates(tenant_id="t1")
        names = [c.model_name for c in cands]
        assert "test-small-model" not in names

    def test_candidate_key_is_provider_id_plus_model(
        self, provider_config: ProviderConfig
    ) -> None:
        cand = CandidateModel(
            provider_config=provider_config,
            model_name="gpt-4o",
        )
        assert cand.candidate_key == f"{provider_config.id}:gpt-4o"
