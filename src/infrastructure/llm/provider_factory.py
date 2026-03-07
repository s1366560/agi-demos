"""Unified AI Service Factory.

Creates LLM clients, embedders, and rerankers from database-resolved
provider configuration. This is the single entry point that replaces
the scattered creation logic in ``factories.py``.

All services share the same ``ProviderConfig`` resolved via
``ProviderResolutionService``, ensuring consistent API key usage and
multi-tenant isolation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
    from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder
    from src.infrastructure.llm.litellm.litellm_reranker import LiteLLMReranker
    from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient

from src.application.services.provider_resolution_service import (
    ProviderResolutionService,
    get_provider_resolution_service,
)
from src.domain.llm_providers.models import OperationType, ProviderConfig

logger = logging.getLogger(__name__)


class AIServiceFactory:
    """Create AI services (LLM, embedding, rerank) from DB provider config.

    Usage::

        factory = AIServiceFactory()
        provider = await factory.resolve_provider(tenant_id)
        llm = factory.create_llm_client(provider)
        embedder = factory.create_embedder(provider)
        reranker = factory.create_reranker(provider)
    """

    def __init__(
        self,
        resolution_service: ProviderResolutionService | None = None,
    ) -> None:
        self._resolution = resolution_service or get_provider_resolution_service()

    async def resolve_provider(
        self,
        tenant_id: str | None = None,
        operation_type: OperationType = OperationType.LLM,
    ) -> ProviderConfig:
        """Resolve the active provider config from the database."""
        return await self._resolution.resolve_provider(tenant_id, operation_type)

    async def resolve_embedding_provider(
        self,
        tenant_id: str | None = None,
    ) -> ProviderConfig:
        """Resolve provider config for embedding operations."""
        return await self.resolve_provider(tenant_id, operation_type=OperationType.EMBEDDING)

    async def resolve_rerank_provider(
        self,
        tenant_id: str | None = None,
    ) -> ProviderConfig:
        """Resolve provider config for rerank operations."""
        return await self.resolve_provider(tenant_id, operation_type=OperationType.RERANK)

    # ------------------------------------------------------------------
    # LLM Client
    # ------------------------------------------------------------------

    @staticmethod
    def create_llm_client(
        provider_config: ProviderConfig,
        cache: bool | None = None,
    ) -> LiteLLMClient:
        """Create a ``LiteLLMClient`` from a resolved provider config.

        Returns:
            Configured ``LiteLLMClient`` instance.
        """
        from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
        from src.infrastructure.llm.model_catalog import get_model_catalog_service

        return create_litellm_client(
            provider_config, cache=cache, catalog=get_model_catalog_service()
        )

    @staticmethod
    def create_unified_llm_client(
        provider_config: ProviderConfig,
        temperature: float = 0.7,
    ) -> UnifiedLLMClient:
        """Create a ``UnifiedLLMClient`` that wraps LiteLLMClient.

        Returns:
            ``UnifiedLLMClient`` with the domain ``LLMClient`` interface.
        """
        from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
        from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient
        from src.infrastructure.llm.model_catalog import get_model_catalog_service

        litellm_client = create_litellm_client(
            provider_config, catalog=get_model_catalog_service()
        )
        return UnifiedLLMClient(litellm_client=litellm_client, temperature=temperature)

    # ------------------------------------------------------------------
    # Embedder
    # ------------------------------------------------------------------

    @staticmethod
    def create_embedder(
        provider_config: ProviderConfig,
        embedding_dim: int | None = None,
    ) -> LiteLLMEmbedder:
        """Create a ``LiteLLMEmbedder`` from a resolved provider config.

        The embedder uses ``ProviderConfig.embedding_model`` (falls back to
        the provider's default if not set) and passes the decrypted API key
        per-request — no global ``os.environ`` mutation.

        Returns:
            Configured ``LiteLLMEmbedder`` instance.
        """
        from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder

        return LiteLLMEmbedder(config=provider_config, embedding_dim=embedding_dim)

    @staticmethod
    def create_embedding_service(
        provider_config: ProviderConfig,
        embedding_dim: int | None = None,
    ) -> EmbeddingService:
        """Create an ``EmbeddingService`` wrapping a LiteLLM embedder.

        Returns:
            ``EmbeddingService`` with the unified graph embedding interface.
        """
        from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
        from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder

        embedder = LiteLLMEmbedder(config=provider_config, embedding_dim=embedding_dim)
        return EmbeddingService(embedder=embedder)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Reranker
    # ------------------------------------------------------------------

    @staticmethod
    def create_reranker(
        provider_config: ProviderConfig,
    ) -> LiteLLMReranker:
        """Create a ``LiteLLMReranker`` from a resolved provider config.

        Returns:
            Configured ``LiteLLMReranker`` instance.
        """
        from src.infrastructure.llm.litellm.litellm_reranker import LiteLLMReranker

        return LiteLLMReranker(config=provider_config)


    # ------------------------------------------------------------------
    # Category-Based Model Routing
    # ------------------------------------------------------------------

    @staticmethod
    def create_llm_client_for_category(
        provider_config: ProviderConfig,
        task_description: str,
        cache: bool | None = None,
    ) -> LiteLLMClient:
        """Create a ``LiteLLMClient`` with category-based model selection.

        Detects the task category from the description and overrides the
        model in ``provider_config`` with the category-optimal model when
        available.

        Args:
            provider_config: Base provider config (used for API keys, etc.).
            task_description: Text description of the task to route.
            cache: Enable response caching.

        Returns:
            Configured ``LiteLLMClient`` with category-optimal model.
        """
        from src.infrastructure.llm.category_router import CategoryRouter
        from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
        from src.infrastructure.llm.model_catalog import get_model_catalog_service

        router = CategoryRouter()
        routed = router.route(task_description=task_description)
        if routed.preferred_models:
            # Override the model in provider config with the top pick
            preferred = routed.preferred_models[0]
            logger.info(
                "Category router selected model=%s for category=%s "
                "(confidence=%.2f, original=%s)",
                preferred,
                routed.category.value,
                routed.confidence,
                provider_config.model,
            )
            provider_config = ProviderConfig(
                provider=provider_config.provider,
                model=preferred,
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                embedding_model=provider_config.embedding_model,
                rerank_model=provider_config.rerank_model,
            )
        return create_litellm_client(
            provider_config, cache=cache, catalog=get_model_catalog_service()
        )

# Module-level convenience ------------------------------------------------

_factory: AIServiceFactory | None = None


def get_ai_service_factory() -> AIServiceFactory:
    """Return the module-level ``AIServiceFactory`` singleton."""
    global _factory
    if _factory is None:
        _factory = AIServiceFactory()
    return _factory
