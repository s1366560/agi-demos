"""Unit tests for :mod:`src.infrastructure.llm.load_balancer`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.load_balancer import (
    LeastLoadedBalancer,
    ProviderHealthStore,
)
from src.infrastructure.llm.model_pool import CandidateModel

pytestmark = pytest.mark.unit


def _cand(provider_config: ProviderConfig, name: str, weight: float = 1.0) -> CandidateModel:
    return CandidateModel(
        provider_config=provider_config,
        model_name=name,
        weight=weight,
    )


class TestProviderHealthStore:
    def test_new_key_is_healthy(self) -> None:
        store = ProviderHealthStore()
        assert store.is_healthy("unknown:m") is True

    def test_record_failure_sets_cooldown(self) -> None:
        store = ProviderHealthStore(cooldown_seconds=60.0)
        store.record_failure("k1")
        assert store.is_healthy("k1") is False
        rec = store.get("k1")
        assert rec.consecutive_failures == 1
        assert rec.cooldown_until is not None

    def test_record_success_clears_cooldown(self) -> None:
        store = ProviderHealthStore()
        store.record_failure("k1")
        store.record_success("k1")
        assert store.is_healthy("k1") is True
        assert store.get("k1").consecutive_failures == 0

    def test_is_healthy_recovers_after_cooldown_expires(self) -> None:
        store = ProviderHealthStore(cooldown_seconds=60.0)
        store.record_failure("k1")
        future = datetime.now(UTC) + timedelta(seconds=120)
        assert store.is_healthy("k1", now=future) is True


class TestLeastLoadedBalancer:
    def test_pick_returns_none_for_empty_pool(self) -> None:
        bal = LeastLoadedBalancer()
        assert bal.pick([]) is None

    def test_pick_prefers_higher_weight_on_ties(
        self, provider_config: ProviderConfig
    ) -> None:
        bal = LeastLoadedBalancer()
        low = _cand(provider_config, "m-low", weight=1.0)
        high = _cand(provider_config, "m-high", weight=5.0)
        decision = bal.pick([low, high])
        assert decision is not None
        assert decision.chosen is high

    def test_pick_skips_unhealthy_when_others_available(
        self, provider_config: ProviderConfig
    ) -> None:
        bal = LeastLoadedBalancer()
        bad = _cand(provider_config, "bad")
        good = _cand(provider_config, "good")
        bal.record_failure(bad)

        decision = bal.pick([bad, good])
        assert decision is not None
        assert decision.chosen is good

    def test_pick_falls_through_when_all_unhealthy(
        self, provider_config: ProviderConfig
    ) -> None:
        bal = LeastLoadedBalancer()
        a = _cand(provider_config, "a")
        b = _cand(provider_config, "b")
        bal.record_failure(a)
        bal.record_failure(b)

        decision = bal.pick([a, b])
        assert decision is not None
        assert decision.chosen in (a, b)

    async def test_track_increments_then_decrements_inflight(
        self, provider_config: ProviderConfig
    ) -> None:
        bal = LeastLoadedBalancer()
        cand = _cand(provider_config, "m1")

        async with bal.track(cand):
            assert bal.stats(cand).inflight == 1
        assert bal.stats(cand).inflight == 0
        # Latency EWMA recorded a value.
        assert bal.stats(cand).latency_ewma_ms >= 0.0

    def test_record_failure_then_success_resets_health(
        self, provider_config: ProviderConfig
    ) -> None:
        bal = LeastLoadedBalancer()
        cand = _cand(provider_config, "m1")
        bal.record_failure(cand)
        assert bal.health_store.is_healthy(cand.candidate_key) is False
        bal.record_success(cand)
        assert bal.health_store.is_healthy(cand.candidate_key) is True
