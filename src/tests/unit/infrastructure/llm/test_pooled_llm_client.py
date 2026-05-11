"""Unit tests for :class:`PooledLLMClient` retry / failover behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.domain.llm_providers.llm_types import Message, ModelSize, RateLimitError
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.auto_broker import AutoBroker, BrokerVerdict
from src.infrastructure.llm.litellm.pooled_llm_client import PooledLLMClient
from src.infrastructure.llm.load_balancer import LeastLoadedBalancer
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
        excluded = pool_filter.exclude_keys if pool_filter else frozenset()
        return [c for c in self.candidates if c.candidate_key not in excluded]


class _FakeLiteLLMClient:
    """Stand-in for LiteLLMClient — records calls, optionally raises."""

    def __init__(self, *, raise_on_first: Exception | None = None) -> None:
        self._raise_on_first = raise_on_first
        self.calls: list[dict[str, Any]] = []

    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raise_on_first is not None and len(self.calls) == 1:
            err = self._raise_on_first
            self._raise_on_first = None
            raise err
        return {"content": "ok", "model": kwargs.get("model")}


class _StubBroker(AutoBroker):
    def __init__(self, verdict: BrokerVerdict) -> None:
        self._verdict = verdict

    async def decide(self, **_kwargs: Any) -> BrokerVerdict:  # type: ignore[override]
        return self._verdict


def _cand(provider_config: ProviderConfig, name: str) -> CandidateModel:
    return CandidateModel(provider_config=provider_config, model_name=name)


class TestPooledLLMClient:
    async def test_generate_dispatches_to_picked_candidate(
        self, provider_config: ProviderConfig
    ) -> None:
        cand = _cand(provider_config, "model-a")
        pool = _FakePool(candidates=[cand])
        fake_litellm = _FakeLiteLLMClient()

        client = PooledLLMClient(
            tenant_id="t1",
            pool_service=pool,
            balancer=LeastLoadedBalancer(),
            broker=_StubBroker(
                BrokerVerdict(
                    tier=None,  # type: ignore[arg-type]
                    require_vision=False,
                    require_tools=False,
                    category="chat",
                    rationale="",
                    source="llm",
                )
            ),
        )
        # Seed client cache with a fake LiteLLM client so _get_client returns it.
        client._client_cache[str(provider_config.id)] = fake_litellm  # type: ignore[assignment]

        resp = await client.generate(messages=[Message.user("hi")])

        assert resp["content"] == "ok"
        assert fake_litellm.calls[0]["model"] == "model-a"
        assert resp["_pool"]["model"] == "model-a"
        assert resp["_pool"]["attempts"] == 1

    async def test_retries_on_failover_worthy_error_then_succeeds(
        self, provider_config: ProviderConfig
    ) -> None:
        cand_a = _cand(provider_config, "model-a")
        cand_b = _cand(provider_config, "model-b")
        pool = _FakePool(candidates=[cand_a, cand_b])

        # First call: 429 rate-limit (failover-worthy). Second call: success.
        fake_litellm = _FakeLiteLLMClient(
            raise_on_first=RateLimitError("rate limit exceeded")
        )

        bal = LeastLoadedBalancer()
        client = PooledLLMClient(
            tenant_id="t1",
            pool_service=pool,
            balancer=bal,
            broker=_StubBroker(
                BrokerVerdict(
                    tier=None,  # type: ignore[arg-type]
                    require_vision=False,
                    require_tools=False,
                    category="chat",
                    rationale="",
                    source="llm",
                )
            ),
            max_attempts=3,
        )
        client._client_cache[str(provider_config.id)] = fake_litellm  # type: ignore[assignment]

        resp = await client.generate(messages=[Message.user("hi")])

        assert resp["content"] == "ok"
        # Two attempts: first failed, second succeeded with a different model.
        assert len(fake_litellm.calls) == 2
        assert fake_litellm.calls[0]["model"] != fake_litellm.calls[1]["model"]
        assert resp["_pool"]["attempts"] == 2
        # The failed candidate is marked unhealthy.
        first_key = f"{provider_config.id}:{fake_litellm.calls[0]['model']}"
        assert bal.health_store.is_healthy(first_key) is False

    async def test_non_retryable_error_propagates_immediately(
        self, provider_config: ProviderConfig
    ) -> None:
        cand = _cand(provider_config, "model-a")
        pool = _FakePool(candidates=[cand])
        fake_litellm = _FakeLiteLLMClient(raise_on_first=ValueError("bad request"))

        client = PooledLLMClient(
            tenant_id="t1",
            pool_service=pool,
            balancer=LeastLoadedBalancer(),
            broker=_StubBroker(
                BrokerVerdict(
                    tier=None,  # type: ignore[arg-type]
                    require_vision=False,
                    require_tools=False,
                    category="chat",
                    rationale="",
                    source="llm",
                )
            ),
        )
        client._client_cache[str(provider_config.id)] = fake_litellm  # type: ignore[assignment]

        with pytest.raises(ValueError, match="bad request"):
            await client.generate(messages=[Message.user("hi")])

        assert len(fake_litellm.calls) == 1  # No retry.

    async def test_concrete_model_arg_filters_pool(
        self, provider_config: ProviderConfig
    ) -> None:
        cand_a = _cand(provider_config, "model-a")
        cand_b = _cand(provider_config, "model-b")
        pool = _FakePool(candidates=[cand_a, cand_b])
        fake_litellm = _FakeLiteLLMClient()

        client = PooledLLMClient(
            tenant_id="t1",
            pool_service=pool,
            balancer=LeastLoadedBalancer(),
            broker=_StubBroker(
                BrokerVerdict(
                    tier=None,  # type: ignore[arg-type]
                    require_vision=False,
                    require_tools=False,
                    category="chat",
                    rationale="",
                    source="llm",
                )
            ),
        )
        client._client_cache[str(provider_config.id)] = fake_litellm  # type: ignore[assignment]

        await client.generate(messages=[Message.user("hi")], model="model-b")
        assert fake_litellm.calls[0]["model"] == "model-b"

    async def test_auto_model_invokes_broker(
        self, provider_config: ProviderConfig
    ) -> None:
        cand = _cand(provider_config, "model-large")
        pool = _FakePool(candidates=[cand])
        fake_litellm = _FakeLiteLLMClient()

        captured: dict[str, Any] = {}

        class CapturingBroker(AutoBroker):
            def __init__(self) -> None:
                pass

            async def decide(self, **kwargs: Any) -> BrokerVerdict:  # type: ignore[override]
                captured["called"] = True
                captured["tenant_id"] = kwargs.get("tenant_id")
                return BrokerVerdict(
                    tier="large",
                    require_vision=False,
                    require_tools=False,
                    category="analysis",
                    rationale="stub",
                    source="llm",
                )

        client = PooledLLMClient(
            tenant_id="tenant-x",
            pool_service=pool,
            balancer=LeastLoadedBalancer(),
            broker=CapturingBroker(),
        )
        client._client_cache[str(provider_config.id)] = fake_litellm  # type: ignore[assignment]

        await client.generate(messages=[Message.user("hi")], model="auto")
        assert captured.get("called") is True
        assert captured.get("tenant_id") == "tenant-x"

    async def test_normalize_model_arg(self) -> None:
        assert PooledLLMClient._normalize_model_arg(None) is None
        assert PooledLLMClient._normalize_model_arg("") is None
        assert PooledLLMClient._normalize_model_arg("auto") == "auto"
        assert PooledLLMClient._normalize_model_arg("Auto") == "auto"
        assert PooledLLMClient._normalize_model_arg("AUTO") == "auto"
        assert PooledLLMClient._normalize_model_arg("gpt-4o") == "gpt-4o"

    async def test_model_size_to_tier(self) -> None:
        assert PooledLLMClient._model_size_to_tier(ModelSize.small) == "small"
        assert PooledLLMClient._model_size_to_tier(ModelSize.large) == "large"
        assert PooledLLMClient._model_size_to_tier(ModelSize.medium) is None
