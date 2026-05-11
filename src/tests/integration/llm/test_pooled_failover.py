"""End-to-end integration tests for :class:`PooledLLMClient` failover.

Exercises the pool with two real :class:`ProviderConfig` rows persisted
through ``SQLAlchemyProviderRepository``. The actual LLM HTTP call is
stubbed by pre-seeding the client cache so we never reach LiteLLM.

These tests verify Phase 9 invariants:

1. The pool can pick one of the two seeded providers.
2. On a 429-like failure the pool retries the alternate provider.
3. Failures are recorded in the shared :class:`ProviderHealthStore`.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.application.services.provider_resolution_service import ProviderResolutionService
from src.domain.llm_providers.models import ProviderConfigCreate, ProviderType
from src.infrastructure.llm.failover_chain import FailoverChain
from src.infrastructure.llm.litellm.pooled_llm_client import PooledLLMClient
from src.infrastructure.llm.load_balancer import LeastLoadedBalancer, ProviderHealthStore
from src.infrastructure.llm.model_pool import ModelPoolService
from src.infrastructure.persistence.llm_providers_repository import SQLAlchemyProviderRepository


class _StubLLMClient:
    """Minimal stand-in for :class:`LiteLLMClient` used inside the pool.

    ``PooledLLMClient`` only invokes ``await client.generate(...)`` on
    the cached entry, so a simple async callable is sufficient.
    """

    def __init__(self, *, behaviour: list[Any]) -> None:
        # Each element is either an exception class+message tuple or a
        # response dict. They are consumed in order; the last element is
        # reused if exhausted.
        self._behaviour = list(behaviour)
        self.calls: int = 0

    async def generate(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        idx = min(self.calls - 1, len(self._behaviour) - 1)
        item = self._behaviour[idx]
        if isinstance(item, Exception):
            raise item
        return dict(item)


async def _seed_two_providers(db_session: Any) -> tuple[Any, Any]:
    repo = SQLAlchemyProviderRepository(session=db_session)
    primary = await repo.create(
        ProviderConfigCreate(
            name="pool-primary",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test-primary",
            llm_model="gpt-4o-mini",
        )
    )
    secondary = await repo.create(
        ProviderConfigCreate(
            name="pool-secondary",
            provider_type=ProviderType.OPENAI,
            api_key="sk-test-secondary",
            llm_model="gpt-4o-mini",
        )
    )
    await db_session.commit()
    return primary, secondary


def _build_pooled_client(
    *,
    db_session: Any,
    health_store: ProviderHealthStore,
) -> PooledLLMClient:
    repo = SQLAlchemyProviderRepository(session=db_session)
    resolution = ProviderResolutionService(repository=repo)
    pool = ModelPoolService(resolution_service=resolution)
    balancer = LeastLoadedBalancer(health=health_store)
    return PooledLLMClient(
        tenant_id=None,
        pool_service=pool,
        balancer=balancer,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pool_picks_one_of_two_providers_and_succeeds(db_session: Any) -> None:
    primary, secondary = await _seed_two_providers(db_session)
    store = ProviderHealthStore()
    client = _build_pooled_client(db_session=db_session, health_store=store)

    stub_primary = _StubLLMClient(behaviour=[{"content": "from-primary"}])
    stub_secondary = _StubLLMClient(behaviour=[{"content": "from-secondary"}])
    client._client_cache[str(primary.id)] = stub_primary  # type: ignore[assignment]
    client._client_cache[str(secondary.id)] = stub_secondary  # type: ignore[assignment]

    result = await client.generate(messages=[{"role": "user", "content": "hi"}])

    assert result["content"] in {"from-primary", "from-secondary"}
    # Exactly one provider was called.
    assert (stub_primary.calls + stub_secondary.calls) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pool_failover_retries_second_provider_on_429(db_session: Any) -> None:
    primary, secondary = await _seed_two_providers(db_session)
    store = ProviderHealthStore()
    client = _build_pooled_client(db_session=db_session, health_store=store)

    # One candidate permanently fails with a retryable error; the other
    # succeeds. Whichever order the balancer picks them in, the pool
    # must retry the alternate after the failure and ultimately return a
    # success.
    rate_limit_error = RuntimeError("rate limit exceeded on provider")
    stub_primary = _StubLLMClient(behaviour=[rate_limit_error])
    stub_secondary = _StubLLMClient(behaviour=[{"content": "secondary-ok"}])
    client._client_cache[str(primary.id)] = stub_primary  # type: ignore[assignment]
    client._client_cache[str(secondary.id)] = stub_secondary  # type: ignore[assignment]

    result = await client.generate(messages=[{"role": "user", "content": "hi"}])

    # Success must come from the healthy provider.
    assert result["content"] == "secondary-ok"
    # Secondary was definitely called once (it succeeded). Primary was
    # called either zero (if balancer picked secondary first) or one
    # (if balancer picked primary first then failed over).
    assert stub_secondary.calls == 1
    assert stub_primary.calls in (0, 1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pool_records_failure_in_shared_health_store(db_session: Any) -> None:
    primary, secondary = await _seed_two_providers(db_session)
    store = ProviderHealthStore(cooldown_seconds=600.0)
    client = _build_pooled_client(db_session=db_session, health_store=store)

    # Both providers permanently failing — exhaust max_attempts.
    err = RuntimeError("rate limit exceeded")
    stub_primary = _StubLLMClient(behaviour=[err])
    stub_secondary = _StubLLMClient(behaviour=[err])
    client._client_cache[str(primary.id)] = stub_primary  # type: ignore[assignment]
    client._client_cache[str(secondary.id)] = stub_secondary  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="rate limit"):
        await client.generate(messages=[{"role": "user", "content": "hi"}])

    # At least one of the two candidate keys is now in cooldown — both
    # were attempted (max_attempts default = 3 ≥ 2 candidates).
    primary_key = f"{primary.id}:{primary.llm_model}"
    secondary_key = f"{secondary.id}:{secondary.llm_model}"
    unhealthy = [
        k for k in (primary_key, secondary_key) if not store.is_healthy(k)
    ]
    assert len(unhealthy) >= 1, "expected at least one candidate in cooldown"

    # And a FailoverChain sharing the same store stays isolated thanks to
    # the ``chain:`` key prefix — none of its keys are affected.
    chain = FailoverChain(
        fallback_sequence=[("openai", primary.llm_model)],
        health_store=store,
    )
    assert chain.is_provider_healthy("openai", primary.llm_model) is True
