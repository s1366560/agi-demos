"""Unit tests for :mod:`src.infrastructure.llm.auto_broker`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.llm_providers.llm_types import Message
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.auto_broker import AutoBroker, BrokerVerdict
from src.infrastructure.llm.model_pool import CandidateModel, PoolFilter

pytestmark = pytest.mark.unit


@dataclass
class _FakePool:
    candidates: list[CandidateModel] = field(default_factory=list)

    async def list_candidates(
        self,
        tenant_id: str | None = None,
        pool_filter: PoolFilter | None = None,
    ) -> list[CandidateModel]:
        if pool_filter and pool_filter.tier == "small":
            return [c for c in self.candidates if c.tier == "small"]
        return list(self.candidates)


class TestAutoBroker:
    async def test_structural_unavailable_verdict_when_no_candidates(self) -> None:
        broker = AutoBroker(pool_service=_FakePool())
        verdict = await broker.decide(
            tenant_id="t1",
            messages=[Message.user("hello")],
            tools=None,
        )
        assert isinstance(verdict, BrokerVerdict)
        assert verdict.source == "unavailable"
        assert verdict.tier is None
        assert verdict.category is None
        assert verdict.require_vision is False
        assert verdict.require_tools is False

    async def test_unavailable_verdict_preserves_structural_capabilities(self) -> None:
        broker = AutoBroker(pool_service=_FakePool())
        verdict = await broker.decide(
            tenant_id="t1",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what is this?"},
                        {"type": "image_url", "image_url": {"url": "..."}},
                    ],
                }
            ],
            tools=[{"function": {"name": "search"}}],
        )
        assert verdict.source == "unavailable"
        assert verdict.tier is None
        assert verdict.category is None
        assert verdict.require_vision is True
        assert verdict.require_tools is True

    async def test_cache_returns_source_cache_on_repeat(
        self, provider_config: ProviderConfig
    ) -> None:
        # No candidates → first call stays unfiltered; second call serves cache.
        broker = AutoBroker(pool_service=_FakePool())
        messages = [Message.user("same prompt")]
        first = await broker.decide(tenant_id="t1", messages=messages, tools=None)
        second = await broker.decide(tenant_id="t1", messages=messages, tools=None)
        assert first.source == "unavailable"
        assert second.source == "cache"
        assert second.tier == first.tier

    async def test_llm_verdict_used_when_broker_call_succeeds(
        self, provider_config: ProviderConfig
    ) -> None:
        cand = CandidateModel(
            provider_config=provider_config,
            model_name="cheap",
            tier="small",
        )
        broker = AutoBroker(pool_service=_FakePool(candidates=[cand]))

        async def fake_llm_decide(
            self_: AutoBroker,
            candidate: CandidateModel,
            messages: Any,
            tools: Any,
        ) -> BrokerVerdict:
            return BrokerVerdict(
                tier="large",
                require_vision=False,
                require_tools=True,
                category="agent_tools",
                rationale="test",
                source="llm",
            )

        broker._llm_decide = fake_llm_decide.__get__(broker, AutoBroker)  # type: ignore[method-assign]

        verdict = await broker.decide(
            tenant_id="t-x",
            messages=[Message.user("complex task")],
            tools=[{"function": {"name": "search"}}],
        )
        assert verdict.source == "llm"
        assert verdict.tier == "large"
        assert verdict.require_tools is True

    async def test_llm_failure_returns_unfiltered_structural_verdict(
        self, provider_config: ProviderConfig
    ) -> None:
        cand = CandidateModel(
            provider_config=provider_config,
            model_name="cheap",
            tier="small",
        )
        broker = AutoBroker(pool_service=_FakePool(candidates=[cand]))

        async def fake_llm_decide(
            self_: AutoBroker,
            candidate: CandidateModel,
            messages: Any,
            tools: Any,
        ) -> BrokerVerdict:
            raise RuntimeError("boom")

        broker._llm_decide = fake_llm_decide.__get__(broker, AutoBroker)  # type: ignore[method-assign]

        verdict = await broker.decide(
            tenant_id="t-y",
            messages=[Message.user("hi")],
            tools=None,
        )
        assert verdict.source == "unavailable"
        assert verdict.tier is None
        assert verdict.category is None
        assert "RuntimeError" in verdict.rationale

    def test_verdict_to_filter_preserves_capabilities(self) -> None:
        v = BrokerVerdict(
            tier="small",
            require_vision=True,
            require_tools=False,
            category="vision",
            rationale="",
            source="llm",
        )
        f = v.to_filter(exclude_keys=frozenset({"k"}))
        assert f.tier == "small"
        assert f.require_vision is True
        assert f.require_tools is False
        assert f.exclude_keys == frozenset({"k"})
