"""Adapters bridging backend capabilities to legacy consumption surfaces (R3).

Plugin-provided backends implement the provider-neutral contracts from
``src.domain.ports.plugins`` (``EmbedderCapability``, ``RerankerCapability``,
...). Existing call sites consume LiteLLM-flavored interfaces
(``EmbedderProtocol`` / ``BaseReranker``). These adapters translate between
the two so a registry row can replace the builtin without touching the
consumption code.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, override

from src.domain.llm_providers.base import BaseReranker
from src.domain.model.plugins.runtime import CredentialReference
from src.domain.ports.plugins.contracts import (
    EmbedderCapability,
    RerankerCapability,
    ResolvedLlmRoute,
)

if TYPE_CHECKING:
    from src.domain.llm_providers.models import ProviderConfig

logger = logging.getLogger(__name__)

__all__ = [
    "PluginEmbedderAdapter",
    "PluginRerankerAdapter",
    "route_from_provider_config",
    "validate_backend_implementation",
]

_DEFAULT_TIMEOUT_MS = 30_000


def route_from_provider_config(
    provider_config: ProviderConfig,
    *,
    model_id: str,
) -> ResolvedLlmRoute:
    """Build route facts for a backend capability call.

    The credential stays a host-owned reference; python-trusted plugin
    implementations resolve their own credentials through their own config.
    """
    provider_type = provider_config.provider_type
    provider_id = getattr(provider_type, "value", str(provider_type))
    return ResolvedLlmRoute(
        provider_id=provider_id,
        model_id=model_id,
        base_url=provider_config.base_url or "",
        credential=CredentialReference(
            ref=f"provider:{provider_config.name}",
            revision=0,
        ),
        timeout_ms=_DEFAULT_TIMEOUT_MS,
        context_window=0,
        max_output_tokens=0,
    )


def validate_backend_implementation(implementation: object, protocol: type) -> None:
    """Assert a backend implementation satisfies its domain contract."""
    if not isinstance(implementation, protocol):
        impl_name = type(implementation).__name__
        raise TypeError(
            f"backend implementation {impl_name} does not satisfy {protocol.__name__}"
        )


class PluginEmbedderAdapter:
    """Expose an ``EmbedderCapability`` row through the legacy embedder surface.

    Mirrors the ``LiteLLMEmbedder`` methods consumed by ``EmbeddingService``:
    ``create`` for single/batch input and ``create_batch`` for bulk paths.
    """

    def __init__(
        self,
        implementation: EmbedderCapability,
        route: ResolvedLlmRoute,
        *,
        embedding_dim: int | None = None,
    ) -> None:
        super().__init__()
        self._implementation = implementation
        self._route = route
        self._embedding_dim = embedding_dim or 0

    @property
    def embedding_dim(self) -> int:
        """Return the configured embedding dimension (0 = unknown)."""
        return self._embedding_dim

    async def create(self, input_data: str | list[str]) -> Any:  # noqa: ANN401
        """Embed one text or a list of texts."""
        inputs = [input_data] if isinstance(input_data, str) else list(input_data)
        result = await self._implementation.embed(self._route, inputs)
        vectors = [list(vector) for vector in result.vectors]
        if isinstance(input_data, str):
            return vectors[0] if vectors else []
        return vectors

    async def create_batch(
        self,
        input_data_list: list[str],
        batch_size: int = 128,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> list[list[float]]:
        """Embed a list of texts in one capability call."""
        del batch_size, max_retries, retry_delay  # batching policy is plugin-owned
        result = await self._implementation.embed(self._route, list(input_data_list))
        return [list(vector) for vector in result.vectors]


class PluginRerankerAdapter(BaseReranker):
    """Expose a ``RerankerCapability`` row through the ``BaseReranker`` surface."""

    def __init__(
        self,
        implementation: RerankerCapability,
        route: ResolvedLlmRoute,
    ) -> None:
        super().__init__()
        self._implementation = implementation
        self._route = route

    @override
    async def rank(
        self,
        query: str,
        passages: list[str],
        top_n: int | None = None,
    ) -> list[tuple[str, float]]:
        """Rank passages by relevance to the query, descending."""
        result = await self._implementation.rerank(self._route, query, list(passages))
        if len(result.scores) != len(passages):
            raise ValueError(
                f"reranker returned {len(result.scores)} scores for {len(passages)} passages"
            )
        ranked = sorted(
            zip(passages, result.scores, strict=True),
            key=lambda item: item[1],
            reverse=True,
        )
        if top_n is not None:
            ranked = ranked[:top_n]
        return ranked

    @override
    async def score(self, query: str, passage: str) -> float:
        """Score a single passage via the capability row."""
        result = await self._implementation.rerank(self._route, query, [passage])
        if not result.scores:
            raise ValueError("reranker returned no scores for a single passage")
        return float(result.scores[0])
