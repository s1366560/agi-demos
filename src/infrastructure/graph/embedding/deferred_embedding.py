"""Generation-owned embedding resolution independent of graph storage startup."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import override

from src.domain.llm_providers.models import NoActiveProviderError

from .embedding_service import EmbeddingService


class EmbeddingProviderReadiness(ABC):
    """Explicit readiness capability for embedding services and their wrappers."""

    @abstractmethod
    async def ensure_available(self) -> object:
        """Resolve required provider dependencies before using embedding results."""


class DeferredEmbeddingService(EmbeddingService, EmbeddingProviderReadiness):
    """Resolve the real provider and vector indices on the first embedding use.

    Failed resolution is never cached. A later explicit provider configuration
    can recover without replacing the healthy graph storage connection.
    """

    def __init__(self, loader: Callable[[], Awaitable[EmbeddingService]]) -> None:
        self._loader = loader
        self._service: EmbeddingService | None = None
        self._lock = asyncio.Lock()

    @override
    async def ensure_available(self) -> EmbeddingService:
        if self._service is None:
            async with self._lock:
                if self._service is None:
                    try:
                        self._service = await self._loader()
                    except NoActiveProviderError as exc:
                        raise NoActiveProviderError(
                            "provider_unconfigured: no embedding provider configured"
                        ) from exc
        return self._service

    @property
    @override
    def embedding_dim(self) -> int:
        if self._service is None:
            raise NoActiveProviderError("provider_unconfigured: embedding provider is unresolved")
        return self._service.embedding_dim

    @override
    async def embed_text(self, text: str) -> list[float]:
        service = await self.ensure_available()
        return await service.embed_text(text)

    @override
    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 100,
        max_concurrency: int = 5,
    ) -> list[list[float]]:
        service = await self.ensure_available()
        return await service.embed_batch(texts, batch_size, max_concurrency)


async def ensure_embedding_available(service: object) -> None:
    """Resolve only the explicit deferred implementation; ordinary ports stay unchanged."""
    if isinstance(service, EmbeddingProviderReadiness):
        await service.ensure_available()
