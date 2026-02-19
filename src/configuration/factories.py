"""
Factory functions for creating LLM clients and NativeGraphAdapter.

This module provides factory functions that create LLM clients using native SDKs
for each provider, and the NativeGraphAdapter for knowledge graph operations.
"""

import logging
from typing import Optional

from src.configuration.config import get_settings
from src.domain.llm_providers.llm_types import LLMClient
from src.domain.llm_providers.models import OperationType

logger = logging.getLogger(__name__)

# Default embedding dimensions by provider
EMBEDDING_DIMS = {
    "openai": 1536,
    "gemini": 768,
    "dashscope": 1024,
    "deepseek": 1024,  # Uses fallback
    "zai": 1024,
}


async def create_native_graph_adapter(
    tenant_id: Optional[str] = None,
):
    """
    Create NativeGraphAdapter for knowledge graph operations.

    Args:
        tenant_id: Optional tenant ID for multi-tenant provider resolution

    Returns:
        Configured NativeGraphAdapter instance
    """
    from src.infrastructure.graph import NativeGraphAdapter
    from src.infrastructure.graph.neo4j_client import Neo4jClient
    from src.infrastructure.llm.provider_factory import get_ai_service_factory

    settings = get_settings()

    # Create Neo4j client
    neo4j_client = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    # Initialize Neo4j indices
    await neo4j_client.build_indices()

    # Get LLM client for entity extraction
    llm_client = await create_llm_client(tenant_id)

    # Create embedding service via factory
    factory = get_ai_service_factory()
    # For embedding, we need the provider config first
    # TODO: Pass project_id if available, currently using default
    provider_config = await factory.resolve_provider(
        tenant_id=tenant_id,
        operation_type=OperationType.EMBEDDING,
    )
    embedder = factory.create_embedder(provider_config)
    
    # Wrap in EmbeddingService if needed, but NativeGraphAdapter expects EmbeddingService
    # and LiteLLMEmbedder is likely compatible or wrapped inside EmbeddingService
    # Let's check if LiteLLMEmbedder is an EmbeddingService or needs wrapping.
    # Looking at provider_factory.py, create_embedder returns LiteLLMEmbedder.
    # Looking at old code, it wrapped it: embedding_service = EmbeddingService(embedder=embedder)
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
    embedding_service = EmbeddingService(embedder=embedder)

    # Create NativeGraphAdapter
    adapter = NativeGraphAdapter(
        neo4j_client=neo4j_client,
        llm_client=llm_client,
        embedding_service=embedding_service,
        enable_reflexion=False,  # Temporarily disabled for testing
        reflexion_max_iterations=2,
        auto_clear_embeddings=settings.auto_clear_mismatched_embeddings,
    )

    logger.info("NativeGraphAdapter created successfully")
    return adapter


async def create_llm_client(tenant_id: Optional[str] = None) -> LLMClient:
    """Create a unified LLM client using AIServiceFactory.

    Resolves provider configuration from the database.
    """
    from src.infrastructure.llm.provider_factory import get_ai_service_factory
    
    factory = get_ai_service_factory()
    provider_config = await factory.resolve_provider(tenant_id)
    return factory.create_unified_llm_client(provider_config)


# Deprecated: Use create_llm_client instead
async def create_langchain_llm(tenant_id: Optional[str] = None) -> LLMClient:
    """
    DEPRECATED: Use create_llm_client() instead.

    This function is kept for backward compatibility and will be removed in a future version.
    """
    import warnings

    warnings.warn(
        "create_langchain_llm is deprecated. Use create_llm_client instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return await create_llm_client(tenant_id)
