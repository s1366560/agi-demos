"""Least-loaded LLM load balancer.

Picks one :class:`~src.infrastructure.llm.model_pool.CandidateModel` from
a pool by (inflight count, EWMA latency, weight, deterministic tiebreak).

Health and cooldown tracking is delegated to :class:`ProviderHealthStore`
so the existing :class:`~src.infrastructure.llm.failover_chain.FailoverChain`
and this balancer can share state without diverging.

State is in-memory and per-process — see ``further_considerations`` in
the plan note for the Ray-actor implications. A future Redis-backed
store can drop in by implementing the same protocol.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.infrastructure.llm.model_pool import CandidateModel

logger = logging.getLogger(__name__)

# EWMA smoothing factor (0..1). Higher = more weight on recent samples.
_EWMA_ALPHA = 0.3

# Default cooldown after a failover-worthy failure.
_DEFAULT_COOLDOWN_SECONDS = 60.0


@dataclass(kw_only=True)
class CandidateHealth:
    """Mutable health record per ``CandidateModel.candidate_key``."""

    consecutive_failures: int = 0
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    cooldown_until: datetime | None = None

    def is_in_cooldown(self, now: datetime) -> bool:
        return self.cooldown_until is not None and self.cooldown_until > now


class ProviderHealthStore:
    """Shared health state keyed by ``CandidateModel.candidate_key``.

    Both the balancer (forward decisions) and the failover chain
    (post-failure book-keeping) read and mutate the same records.
    """

    def __init__(self, *, cooldown_seconds: float = _DEFAULT_COOLDOWN_SECONDS) -> None:
        self._records: dict[str, CandidateHealth] = {}
        self._cooldown_seconds = cooldown_seconds

    def get(self, key: str) -> CandidateHealth:
        rec = self._records.get(key)
        if rec is None:
            rec = CandidateHealth()
            self._records[key] = rec
        return rec

    def is_healthy(self, key: str, *, now: datetime | None = None) -> bool:
        rec = self._records.get(key)
        if rec is None:
            return True
        return not rec.is_in_cooldown(now or datetime.now(UTC))

    def record_failure(self, key: str) -> None:
        rec = self.get(key)
        rec.consecutive_failures += 1
        now = datetime.now(UTC)
        rec.last_failure_at = now
        rec.cooldown_until = now + timedelta(seconds=self._cooldown_seconds)
        logger.debug(
            "Health: %s entered cooldown until %s (failures=%d)",
            key,
            rec.cooldown_until.isoformat(),
            rec.consecutive_failures,
        )

    def record_success(self, key: str) -> None:
        rec = self.get(key)
        rec.consecutive_failures = 0
        rec.last_success_at = datetime.now(UTC)
        rec.last_failure_at = None
        rec.cooldown_until = None

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._records.clear()
            return
        self._records.pop(key, None)


@dataclass(kw_only=True)
class CandidateStats:
    """Aggregated runtime stats for one candidate."""

    inflight: int = 0
    latency_ewma_ms: float = 0.0
    total_calls: int = 0
    total_failures: int = 0


class _LatencyEWMA:
    def __init__(self) -> None:
        self._values: dict[str, float] = {}

    def record(self, key: str, latency_ms: float) -> float:
        prev = self._values.get(key)
        new = latency_ms if prev is None else prev + _EWMA_ALPHA * (latency_ms - prev)
        self._values[key] = new
        return new

    def get(self, key: str) -> float:
        return self._values.get(key, 0.0)


class _InflightCounter:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def increment(self, key: str) -> None:
        async with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1

    async def decrement(self, key: str) -> None:
        async with self._lock:
            current = self._counts.get(key, 0)
            self._counts[key] = max(0, current - 1)

    def get(self, key: str) -> int:
        return self._counts.get(key, 0)


@dataclass(kw_only=True)
class LoadBalancerDecision:
    """Result of a balancer pick — useful for structured logging."""

    chosen: CandidateModel
    score: tuple[int, float, float]
    alternatives: list[CandidateModel] = field(default_factory=list)


class LeastLoadedBalancer:
    """Pick the candidate with the fewest inflight calls.

    Scoring tuple (lower is better):

    1. inflight count
    2. EWMA latency in ms
    3. ``-weight`` (so higher weight wins ties)

    Final tiebreak is uniform-random over the remaining ties to avoid
    pinning all traffic on the first-listed candidate when stats are
    cold.
    """

    def __init__(self, *, health: ProviderHealthStore | None = None) -> None:
        self._health = health or ProviderHealthStore()
        self._latency = _LatencyEWMA()
        self._inflight = _InflightCounter()

    @property
    def health_store(self) -> ProviderHealthStore:
        return self._health

    def pick(
        self,
        candidates: list[CandidateModel],
        *,
        now: datetime | None = None,
    ) -> LoadBalancerDecision | None:
        """Return the best candidate or ``None`` if every option is unhealthy."""
        if not candidates:
            return None

        now = now or datetime.now(UTC)
        healthy = [c for c in candidates if self._health.is_healthy(c.candidate_key, now=now)]
        pool = healthy or candidates  # All in cooldown — fall through.

        if not healthy:
            logger.info(
                "Balancer: all %d candidates in cooldown — falling through to full pool",
                len(candidates),
            )

        scored: list[tuple[tuple[int, float, float], CandidateModel]] = []
        for cand in pool:
            score = (
                self._inflight.get(cand.candidate_key),
                self._latency.get(cand.candidate_key),
                -cand.weight,
            )
            scored.append((score, cand))

        # Sort by score, then break ties by random shuffle.
        scored.sort(key=lambda item: item[0])
        best_score = scored[0][0]
        tied = [cand for sc, cand in scored if sc == best_score]
        chosen = random.choice(tied) if len(tied) > 1 else tied[0]

        return LoadBalancerDecision(
            chosen=chosen,
            score=best_score,
            alternatives=[c for _, c in scored if c is not chosen],
        )

    @asynccontextmanager
    async def track(self, candidate: CandidateModel) -> AsyncIterator[None]:
        """Async context manager that records inflight + latency.

        Usage::

            async with balancer.track(cand):
                response = await client.generate(...)
        """
        key = candidate.candidate_key
        await self._inflight.increment(key)
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            await self._inflight.decrement(key)
            self._latency.record(key, elapsed_ms)

    def record_success(self, candidate: CandidateModel) -> None:
        self._health.record_success(candidate.candidate_key)

    def record_failure(self, candidate: CandidateModel) -> None:
        self._health.record_failure(candidate.candidate_key)

    def stats(self, candidate: CandidateModel) -> CandidateStats:
        key = candidate.candidate_key
        rec = self._health.get(key)
        return CandidateStats(
            inflight=self._inflight.get(key),
            latency_ewma_ms=self._latency.get(key),
            total_calls=0,
            total_failures=rec.consecutive_failures,
        )


# Module-level singleton -----------------------------------------------------

_balancer: LeastLoadedBalancer | None = None


def get_load_balancer() -> LeastLoadedBalancer:
    """Return the process-wide load balancer singleton."""
    global _balancer
    if _balancer is None:
        _balancer = LeastLoadedBalancer()
    return _balancer


def reset_load_balancer() -> None:
    """Reset the singleton (test helper)."""
    global _balancer
    _balancer = None
