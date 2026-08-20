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
    from src.infrastructure.llm.litellm.pooled_llm_client import PooledLLMClient
    from src.infrastructure.llm.litellm.unified_llm_client import UnifiedLLMClient
    from src.infrastructure.plugins.backend_adapters import (
        PluginEmbedderAdapter,
        PluginRerankerAdapter,
    )

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
        model_id: str | None = None,
    ) -> ProviderConfig:
        """Resolve the active provider config from the database."""
        return await self._resolution.resolve_provider(
            tenant_id,
            operation_type,
            model_id=model_id,
        )

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

        litellm_client = create_litellm_client(provider_config, catalog=get_model_catalog_service())
        return UnifiedLLMClient(litellm_client=litellm_client, temperature=temperature)

    def create_pooled_llm_client(
        self,
        tenant_id: str | None = None,
        temperature: float = 0.7,
    ) -> PooledLLMClient:
        """Create a tenant-bound :class:`PooledLLMClient`.

        Unlike :meth:`create_unified_llm_client`, this client is **not**
        tied to a single ``ProviderConfig``: every call fans out across
        the tenant's full provider pool via the load balancer, and
        supports the ``model="auto"`` sentinel for Agent-First routing.

        Embeddings and rerankers still go through
        :meth:`create_unified_llm_client` / :meth:`create_embedder`
        because those operations are single-provider by design.
        """
        from src.infrastructure.llm.litellm.pooled_llm_client import PooledLLMClient

        return PooledLLMClient(tenant_id=tenant_id, temperature=temperature)

    # ------------------------------------------------------------------
    # Embedder
    # ------------------------------------------------------------------

    @staticmethod
    def create_embedder(
        provider_config: ProviderConfig,
        embedding_dim: int | None = None,
    ) -> LiteLLMEmbedder | PluginEmbedderAdapter:
        """Create the embedder from a resolved provider config.

        When the platform plugin registry has an active ``embedder``
        capability row, the plugin implementation (validated against the
        domain ``EmbedderCapability`` contract) wins and is exposed through
        the same legacy surface. Otherwise the builtin ``LiteLLMEmbedder``
        is returned unchanged.

        Returns:
            Configured embedder (builtin ``LiteLLMEmbedder`` or plugin adapter).
        """
        from src.domain.model.plugins import CapabilityKind
        from src.domain.ports.plugins.contracts import EmbedderCapability
        from src.infrastructure.plugins.backend_adapters import (
            PluginEmbedderAdapter,
            route_from_provider_config,
            validate_backend_implementation,
        )
        from src.infrastructure.plugins.backend_runtime import (
            BackendResolutionError,
            resolve_backend,
        )
        from src.infrastructure.plugins.runtime_host import (
            get_platform_plugin_runtime_host,
        )

        registry = get_platform_plugin_runtime_host().capabilities
        try:
            selection = resolve_backend(
                registry,
                CapabilityKind.EMBEDDER,
                validator=lambda impl: validate_backend_implementation(impl, EmbedderCapability),
            )
        except BackendResolutionError:
            selection = None
        if selection is not None:
            model_id = provider_config.embedding_model or ""
            logger.info(
                "Using plugin embedder capability plugin_id=%s",
                selection.plugin_id,
            )
            return PluginEmbedderAdapter(
                selection.implementation,  # type: ignore[arg-type]
                route_from_provider_config(provider_config, model_id=model_id),
                embedding_dim=embedding_dim,
            )

        from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder

        return LiteLLMEmbedder(config=provider_config, embedding_dim=embedding_dim)

    @staticmethod
    def create_embedding_service(
        provider_config: ProviderConfig,
        embedding_dim: int | None = None,
    ) -> EmbeddingService:
        """Create an ``EmbeddingService`` wrapping a LiteLLM embedder.

        If the embedder cannot be created (missing API key, invalid
        model, etc.) a ``NullEmbeddingService`` is returned so that
        search and indexing degrade to FTS-only mode instead of
        crashing.

        Returns:
            ``EmbeddingService`` (or ``NullEmbeddingService`` on failure).
        """
        from src.infrastructure.graph.embedding.embedding_service import (
            EmbeddingService,
            NullEmbeddingService,
        )

        try:
            from src.infrastructure.llm.litellm.litellm_embedder import LiteLLMEmbedder

            embedder = LiteLLMEmbedder(config=provider_config, embedding_dim=embedding_dim)
            return EmbeddingService(embedder=embedder)  # type: ignore[arg-type]
        except Exception as e:
            logger.warning(
                "Failed to create embedding service, falling back to NullEmbeddingService: %s",
                e,
            )
            return NullEmbeddingService()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Reranker
    # ------------------------------------------------------------------

    @staticmethod
    def create_reranker(
        provider_config: ProviderConfig,
    ) -> LiteLLMReranker | PluginRerankerAdapter:
        """Create the reranker from a resolved provider config.

        When the platform plugin registry has an active ``reranker``
        capability row, the plugin implementation (validated against the
        domain ``RerankerCapability`` contract) wins and is exposed through
        the ``BaseReranker`` surface. Otherwise the builtin
        ``LiteLLMReranker`` is returned unchanged.

        Returns:
            Configured reranker (builtin ``LiteLLMReranker`` or plugin adapter).
        """
        from src.domain.model.plugins import CapabilityKind
        from src.domain.ports.plugins.contracts import RerankerCapability
        from src.infrastructure.plugins.backend_adapters import (
            PluginRerankerAdapter,
            route_from_provider_config,
            validate_backend_implementation,
        )
        from src.infrastructure.plugins.backend_runtime import (
            BackendResolutionError,
            resolve_backend,
        )
        from src.infrastructure.plugins.runtime_host import (
            get_platform_plugin_runtime_host,
        )

        registry = get_platform_plugin_runtime_host().capabilities
        try:
            selection = resolve_backend(
                registry,
                CapabilityKind.RERANKER,
                validator=lambda impl: validate_backend_implementation(impl, RerankerCapability),
            )
        except BackendResolutionError:
            selection = None
        if selection is not None:
            model_id = provider_config.reranker_model or ""
            logger.info(
                "Using plugin reranker capability plugin_id=%s",
                selection.plugin_id,
            )
            return PluginRerankerAdapter(
                selection.implementation,  # type: ignore[arg-type]
                route_from_provider_config(provider_config, model_id=model_id),
            )

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
        """Create a ``LiteLLMClient`` with structured category model selection.

        ``CategoryRouter.detect_category`` is a synchronous safe fallback:
        it does not perform semantic keyword matching on ``task_description``.
        It returns a conservative category unless the caller supplies a
        structured signal through the router API. Subjective intent
        classification belongs to the agent-backed auto broker.

        The selected category is then routed against the provider's available
        models, and the model in ``provider_config`` is overridden when a
        category-preferred model is available.

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

        provider_configs = {
            provider_config.provider_type.value: [
                model
                for model in (
                    provider_config.llm_model,
                    provider_config.llm_small_model,
                )
                if model
            ]
        }
        router = CategoryRouter(provider_configs=provider_configs)
        detected_category = router.detect_category(task_description)
        routed = router.route(category=detected_category)
        if routed.preferred_models:
            # Override the model in provider config with the top pick
            preferred = routed.preferred_models[0]
            logger.info(
                "Category router selected model=%s for category=%s (original=%s)",
                preferred,
                routed.category.value,
                provider_config.llm_model,
            )
            provider_config = provider_config.model_copy(update={"llm_model": preferred})
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
