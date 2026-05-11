"""Tenant LLM model pool.

Aggregates every ``ProviderConfig`` in the platform into the set of
``CandidateModel`` entries an agent can fan-out across. The pool is the
input to :class:`~src.infrastructure.llm.load_balancer.LeastLoadedBalancer`
and to the auto-routing broker.

A *candidate* is a concrete ``(provider_config, model_name, tier, weight)``
quadruple. One ``ProviderConfig`` can produce multiple candidates:

- one for ``llm_model`` (its declared primary)
- one for ``llm_small_model`` (when distinct)
- one each for entries in ``secondary_models``

Models filtered by ``allowed_models`` / ``blocked_models`` whitelists and
by capability requirements (vision, etc.) are dropped. The catalog is
consulted for capability/deprecation metadata when available; unknown
models are kept with conservative defaults so newly-released models are
not silently invisible.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from src.domain.llm_providers.models import OperationType, ProviderConfig
from src.infrastructure.llm.model_catalog import (
    ModelCatalogService,
    get_model_catalog_service,
)

logger = logging.getLogger(__name__)

ModelTier = Literal["small", "medium", "large"]


@dataclass(frozen=True, kw_only=True)
class CandidateModel:
    """One concrete model the pool can route to.

    Attributes:
        provider_config: The owning provider row. Source of API key,
            base URL, and provider type.
        model_name: Bare model name (without provider prefix).
        tier: Capability tier hint, or ``None`` when unknown.
        weight: Pool weight inherited from the provider row.
        supports_vision: Cached capability flag.
        supports_tools: Cached capability flag (defaults True).
    """

    provider_config: ProviderConfig
    model_name: str
    tier: ModelTier | None = None
    weight: float = 1.0
    supports_vision: bool = False
    supports_tools: bool = True

    @property
    def provider_type(self) -> str:
        """Lowercase provider type string."""
        pt = self.provider_config.provider_type
        return str(getattr(pt, "value", pt)).lower()

    @property
    def candidate_key(self) -> str:
        """Stable identifier for health / metrics keyed maps."""
        return f"{self.provider_config.id}:{self.model_name}"

    def __repr__(self) -> str:
        return (
            f"CandidateModel(provider={self.provider_type}, "
            f"model={self.model_name}, tier={self.tier}, weight={self.weight})"
        )


@dataclass(kw_only=True)
class PoolFilter:
    """Structured filters applied before balancer picks."""

    tier: ModelTier | None = None
    require_vision: bool = False
    require_tools: bool = False
    exclude_keys: frozenset[str] = field(default_factory=frozenset)


class ModelPoolService:
    """Build the list of candidate models for a tenant.

    Caches the raw provider list for a short TTL (matching the existing
    ``ProviderResolutionService`` cache) so high-frequency callers do not
    hit the database on every turn.
    """

    CACHE_TTL_SECONDS = 60

    def __init__(
        self,
        *,
        resolution_service: object | None = None,
        catalog: ModelCatalogService | None = None,
    ) -> None:
        # Lazy import keeps the module light for type-checking
        if resolution_service is None:
            from src.application.services.provider_resolution_service import (
                get_provider_resolution_service,
            )

            resolution_service = get_provider_resolution_service()
        self._resolution = resolution_service
        self._catalog = catalog or get_model_catalog_service()
        self._cache: dict[str, tuple[list[ProviderConfig], float]] = {}

    async def list_candidates(
        self,
        tenant_id: str | None = None,
        pool_filter: PoolFilter | None = None,
    ) -> list[CandidateModel]:
        """Return every candidate eligible for ``tenant_id``.

        The list ordering is stable (provider creation order, model role
        order). The balancer is responsible for picking within the list.
        """
        providers = await self._fetch_providers(tenant_id)
        filt = pool_filter or PoolFilter()

        candidates: list[CandidateModel] = []
        for provider in providers:
            for cand in self._expand_provider(provider):
                if cand.candidate_key in filt.exclude_keys:
                    continue
                if filt.require_vision and not cand.supports_vision:
                    continue
                if filt.require_tools and not cand.supports_tools:
                    continue
                if filt.tier is not None and cand.tier is not None and cand.tier != filt.tier:
                    # Strict tier match only when both sides declared.
                    continue
                candidates.append(cand)

        if not candidates and filt.tier is not None:
            # No tier-specific match — relax tier filter and try again so
            # the caller never gets an empty pool just because tiers are
            # not configured on the provider rows yet.
            relaxed = PoolFilter(
                tier=None,
                require_vision=filt.require_vision,
                require_tools=filt.require_tools,
                exclude_keys=filt.exclude_keys,
            )
            logger.debug(
                "Pool tier filter %s produced no candidates; relaxing tier", filt.tier
            )
            return await self.list_candidates(tenant_id=tenant_id, pool_filter=relaxed)

        return candidates

    async def _fetch_providers(self, tenant_id: str | None) -> list[ProviderConfig]:
        cache_key = tenant_id or "default"
        cached = self._cache.get(cache_key)
        if cached is not None:
            providers, cached_at = cached
            if time.monotonic() - cached_at <= self.CACHE_TTL_SECONDS:
                return providers
            del self._cache[cache_key]

        list_pool = getattr(self._resolution, "list_pool_providers", None)
        if list_pool is None:
            # Defensive fallback for test doubles / older resolution objects.
            logger.warning(
                "Resolution service lacks list_pool_providers; degrading to single resolve"
            )
            single = await self._resolution.resolve_provider(  # type: ignore[union-attr]
                tenant_id,
                OperationType.LLM,
            )
            providers = [single]
        else:
            providers = await list_pool(tenant_id, OperationType.LLM)
        self._cache[cache_key] = (providers, time.monotonic())
        return providers

    def _expand_provider(self, provider: ProviderConfig) -> list[CandidateModel]:
        """Expand one provider row into one candidate per model role."""
        seen: set[str] = set()
        out: list[CandidateModel] = []

        # Primary model
        if provider.llm_model:
            out.extend(self._maybe_candidate(provider, provider.llm_model, seen))

        # Small model (different tier hint)
        if provider.llm_small_model and provider.llm_small_model != provider.llm_model:
            out.extend(
                self._maybe_candidate(
                    provider,
                    provider.llm_small_model,
                    seen,
                    tier_override="small",
                )
            )

        # Extra secondary models share the same key/base_url
        for secondary in provider.secondary_models or []:
            out.extend(self._maybe_candidate(provider, secondary, seen))

        return out

    def _maybe_candidate(
        self,
        provider: ProviderConfig,
        raw_model: str,
        seen: set[str],
        *,
        tier_override: ModelTier | None = None,
    ) -> list[CandidateModel]:
        model_name = (raw_model or "").strip()
        if not model_name:
            return []
        if model_name in seen:
            return []
        if not provider.is_model_allowed(model_name):
            return []

        # Drop a deprecated model only when the catalog says so. Unknown
        # models flow through with conservative defaults.
        meta = self._catalog.get_model_fuzzy(model_name)
        if meta is not None and meta.is_deprecated:
            logger.debug("Skipping deprecated model %s", model_name)
            return []

        seen.add(model_name)

        tier: ModelTier | None = tier_override
        if tier is None:
            declared = provider.model_tier
            if declared in ("small", "medium", "large"):
                tier = declared  # type: ignore[assignment]

        supports_vision = False
        if meta is not None:
            supports_vision = self._catalog.supports_vision(model_name)

        return [
            CandidateModel(
                provider_config=provider,
                model_name=model_name,
                tier=tier,
                weight=provider.pool_weight or 1.0,
                supports_vision=supports_vision,
                supports_tools=True,
            )
        ]

    def invalidate(self, tenant_id: str | None = None) -> None:
        """Drop cached provider list (called after config changes)."""
        if tenant_id is None:
            self._cache.clear()
            return
        self._cache.pop(tenant_id, None)


# Module-level singleton -----------------------------------------------------

_model_pool_service: ModelPoolService | None = None


def get_model_pool_service() -> ModelPoolService:
    """Return the process-wide ``ModelPoolService`` singleton."""
    global _model_pool_service
    if _model_pool_service is None:
        _model_pool_service = ModelPoolService()
    return _model_pool_service


def reset_model_pool_service() -> None:
    """Reset the singleton (test helper)."""
    global _model_pool_service
    _model_pool_service = None
