"""Pooled LLM client implementing the domain ``LLMClient`` interface.

Per call the client:

1. Resolves the candidate pool for the tenant. ``model="auto"``  routes
   through :class:`~src.infrastructure.llm.auto_broker.AutoBroker` (an
   Agent-First LLM tool-call) to derive a tier/capability filter.
   Concrete model names route through a name-match filter so existing
   callers see no behavior change.
2. Asks the :class:`~src.infrastructure.llm.load_balancer.LeastLoadedBalancer`
   to pick one candidate from the filtered pool.
3. Binds a per-provider :class:`LiteLLMClient` (cached by provider id)
   and invokes ``generate`` / ``generate_stream`` with the candidate's
   model name as a ``model=`` override.
4. On failover-worthy errors records the failure with the balancer and
   re-picks, excluding the failed candidate, up to ``max_attempts``
   times.
5. Streaming reuses step 2 once; mid-stream retries are out of scope
   (the existing failover chain handles those in the agent layer).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any, override

from src.domain.llm_providers.llm_types import (
    DEFAULT_MAX_TOKENS,
    LLMClient,
    LLMConfig,
    Message,
    ModelSize,
)
from src.domain.llm_providers.models import ProviderConfig
from src.infrastructure.llm.auto_broker import AutoBroker, get_auto_broker
from src.infrastructure.llm.failover_chain import is_failover_worthy
from src.infrastructure.llm.litellm.litellm_client import (
    LiteLLMClient,
    create_litellm_client,
)
from src.infrastructure.llm.load_balancer import (
    LeastLoadedBalancer,
    get_load_balancer,
)
from src.infrastructure.llm.model_catalog import get_model_catalog_service
from src.infrastructure.llm.model_pool import (
    CandidateModel,
    ModelPoolService,
    ModelTier,
    PoolFilter,
    get_model_pool_service,
)
from src.infrastructure.llm.structured_logger import get_llm_logger

logger = logging.getLogger(__name__)

_AUTO_MODEL_SENTINEL = "auto"
_DEFAULT_MAX_ATTEMPTS = 3


class PooledLLMClient(LLMClient):
    """``LLMClient`` that fans out across the tenant pool per call.

    The instance is tenant-bound but model-agnostic. Caller-supplied
    ``model`` kwargs are honored: a concrete name pins to that model
    across providers; ``"auto"`` (case-insensitive) delegates to the
    broker.
    """

    def __init__(
        self,
        *,
        tenant_id: str | None,
        pool_service: ModelPoolService | None = None,
        balancer: LeastLoadedBalancer | None = None,
        broker: AutoBroker | None = None,
        temperature: float = 0.7,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        super().__init__(config=LLMConfig(temperature=temperature), cache=True)
        self._tenant_id = tenant_id
        self._pool = pool_service or get_model_pool_service()
        self._balancer = balancer or get_load_balancer()
        self._broker = broker or get_auto_broker()
        self._max_attempts = max(1, max_attempts)
        self._client_cache: dict[str, LiteLLMClient] = {}

    @property
    def tenant_id(self) -> str | None:
        return self._tenant_id

    # ------------------------------------------------------------------
    # LLMClient surface
    # ------------------------------------------------------------------

    @override
    async def _generate_response(
        self,
        messages: list[Message],
        response_model: Any = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        return await self.generate(
            messages=messages,
            max_tokens=max_tokens,
            model_size=model_size,
        )

    @override
    async def generate(
        self,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a non-streaming response, retrying on failover-worthy errors."""
        excluded: set[str] = set()
        last_error: Exception | None = None

        for attempt in range(self._max_attempts):
            candidate = await self._pick_candidate(
                messages=messages,
                tools=tools,
                model_arg=(
                    kwargs.pop("model", None) if attempt == 0 else None
                ),
                model_size=model_size,
                excluded=excluded,
            )
            if candidate is None:
                break

            client = self._get_client(candidate.provider_config)
            try:
                async with self._balancer.track(candidate):
                    response = await client.generate(
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model_size=model_size,
                        langfuse_context=langfuse_context,
                        model=candidate.model_name,
                        **kwargs,
                    )
                self._balancer.record_success(candidate)
                self._annotate_response(response, candidate, attempt)
                return response
            except Exception as exc:
                last_error = exc
                if not is_failover_worthy(exc):
                    logger.debug(
                        "PooledLLMClient: non-retryable error on %s — raising",
                        candidate.candidate_key,
                    )
                    raise
                self._balancer.record_failure(candidate)
                excluded.add(candidate.candidate_key)
                logger.warning(
                    "PooledLLMClient: retryable error on %s (attempt %d/%d): %s",
                    candidate.candidate_key,
                    attempt + 1,
                    self._max_attempts,
                    exc,
                )
                get_llm_logger().log_pool_failover(
                    tenant_id=self._tenant_id,
                    failed_candidate_key=candidate.candidate_key,
                    error_type=type(exc).__name__,
                    attempt=attempt + 1,
                    max_attempts=self._max_attempts,
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError(
            f"PooledLLMClient: no candidate model available for tenant={self._tenant_id}"
        )

    @override
    async def generate_stream(
        self,
        messages: list[Message],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
        langfuse_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """Stream from a single candidate. Mid-stream failover is out of scope."""
        candidate = await self._pick_candidate(
            messages=messages,
            tools=kwargs.get("tools"),
            model_arg=kwargs.pop("model", None),
            model_size=model_size,
            excluded=set(),
        )
        if candidate is None:
            raise RuntimeError(
                f"PooledLLMClient: no candidate model available for tenant={self._tenant_id}"
            )

        client = self._get_client(candidate.provider_config)
        async with self._balancer.track(candidate):
            try:
                async for chunk in client.generate_stream(
                    messages=messages,
                    max_tokens=max_tokens,
                    model_size=model_size,
                    langfuse_context=langfuse_context,
                    model=candidate.model_name,
                    **kwargs,
                ):
                    yield chunk
                self._balancer.record_success(candidate)
            except Exception as exc:
                if is_failover_worthy(exc):
                    self._balancer.record_failure(candidate)
                raise

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _pick_candidate(
        self,
        *,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model_arg: object,
        model_size: ModelSize,
        excluded: set[str],
    ) -> CandidateModel | None:
        """Resolve a candidate honoring caller-supplied ``model``."""
        pool_filter = await self._resolve_filter(
            messages=messages,
            tools=tools,
            model_arg=model_arg,
            model_size=model_size,
            excluded=excluded,
        )
        candidates = await self._pool.list_candidates(
            tenant_id=self._tenant_id,
            pool_filter=pool_filter,
        )

        # If caller supplied a concrete model name, keep only that model.
        concrete = self._normalize_model_arg(model_arg)
        if concrete is not None and concrete != _AUTO_MODEL_SENTINEL:
            candidates = [c for c in candidates if c.model_name == concrete]

        if not candidates:
            logger.warning(
                "PooledLLMClient: empty candidate set (tenant=%s, model=%s, excluded=%d)",
                self._tenant_id,
                model_arg,
                len(excluded),
            )
            return None

        decision = self._balancer.pick(candidates)
        if decision is None:
            return None
        chosen = decision.chosen
        stats = self._balancer.stats(chosen)
        get_llm_logger().log_pool_pick(
            tenant_id=self._tenant_id,
            candidate_key=chosen.candidate_key,
            model=chosen.model_name,
            provider_type=chosen.provider_type,
            inflight=stats.inflight,
            latency_ewma_ms=stats.latency_ewma_ms,
            weight=chosen.weight,
            alternatives_count=len(decision.alternatives),
        )
        return chosen

    async def _resolve_filter(
        self,
        *,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model_arg: object,
        model_size: ModelSize,
        excluded: set[str],
    ) -> PoolFilter:
        """Build the ``PoolFilter`` from request hints + optional broker."""
        exclude_keys = frozenset(excluded)
        normalized = self._normalize_model_arg(model_arg)

        if normalized == _AUTO_MODEL_SENTINEL:
            verdict = await self._broker.decide(
                tenant_id=self._tenant_id,
                messages=messages,
                tools=tools,
            )
            return verdict.to_filter(exclude_keys=exclude_keys)

        # Concrete model name OR no override: map ModelSize → tier and apply
        # weak filters. Tier is intentionally relaxed inside ModelPoolService
        # when nothing matches, so this stays a hint.
        tier_hint = self._model_size_to_tier(model_size)
        return PoolFilter(
            tier=tier_hint,
            require_vision=False,
            require_tools=bool(tools),
            exclude_keys=exclude_keys,
        )

    @staticmethod
    def _normalize_model_arg(model_arg: object) -> str | None:
        if model_arg is None:
            return None
        if not isinstance(model_arg, str):
            return None
        bare = model_arg.strip()
        if not bare:
            return None
        if bare.lower() == _AUTO_MODEL_SENTINEL:
            return _AUTO_MODEL_SENTINEL
        return bare

    @staticmethod
    def _model_size_to_tier(size: ModelSize) -> ModelTier | None:
        if size == ModelSize.small:
            return "small"
        if size == ModelSize.large:
            return "large"
        # ``medium`` is the implicit default — leave tier unconstrained
        # to keep backward compatibility with single-tier deployments.
        return None

    def _get_client(self, provider_config: ProviderConfig) -> LiteLLMClient:
        key = str(provider_config.id)
        cached = self._client_cache.get(key)
        if cached is not None:
            return cached
        client = create_litellm_client(
            provider_config, catalog=get_model_catalog_service()
        )
        self._client_cache[key] = client
        return client

    @staticmethod
    def _annotate_response(
        response: dict[str, Any], candidate: CandidateModel, attempt: int
    ) -> None:
        """Stamp the chosen candidate onto the response for downstream telemetry."""
        if not isinstance(response, dict):
            return
        meta = response.setdefault("_pool", {})
        meta["candidate"] = candidate.candidate_key
        meta["provider_type"] = candidate.provider_type
        meta["model"] = candidate.model_name
        meta["attempts"] = attempt + 1
