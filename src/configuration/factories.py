"""
Factory functions for creating LLM clients and NativeGraphAdapter.

This module provides factory functions that create LLM clients using native SDKs
for each provider, and the NativeGraphAdapter for knowledge graph operations.
"""

import logging

from typing import cast

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
    tenant_id: str | None = None,
) -> None:
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

    # Determine embedding dimension: use config override or auto-detect
    auto_detected_dim = embedding_service.embedding_dim
    embedding_dim = settings.embedding_dimension or auto_detected_dim

    if settings.embedding_dimension:
        logger.info(f"Using configured embedding dimension: {embedding_dim}D")
    else:
        logger.info(f"Auto-detected embedding dimension: {embedding_dim}D")

    # Create vector index for entity name embeddings
    # Use dimension-specific index name to support multiple embedding models
    index_name = f"entity_name_vector_{embedding_dim}D"
    await neo4j_client.create_vector_index(
        index_name=index_name,
        label="Entity",
        property_name="name_embedding",
        dimensions=embedding_dim,
        similarity_function="cosine",
    )
    logger.info(f"Created vector index {index_name} with dimensions={embedding_dim}")

    # Also ensure the default index exists for backward compatibility
    # This allows searches using the default index name to work
    if index_name != "entity_name_vector":
        try:
            await neo4j_client.create_vector_index(
                index_name="entity_name_vector",
                label="Entity",
                property_name="name_embedding",
                dimensions=embedding_dim,
                similarity_function="cosine",
            )
            logger.info(f"Created default entity_name_vector index with dimensions={embedding_dim}")
        except Exception as e:
            # Log warning but don't fail - the dimension-specific index is the primary one
            logger.warning(f"Could not create default index: {e}")

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


async def create_llm_client(tenant_id: str | None = None) -> LLMClient:
    """Create a unified LLM client using AIServiceFactory.

    Resolves provider configuration from the database.
    """
    from src.infrastructure.llm.provider_factory import get_ai_service_factory

    factory = get_ai_service_factory()
    provider_config = await factory.resolve_provider(tenant_id)
    return cast(LLMClient, factory.create_unified_llm_client(provider_config))


# Deprecated: Use create_llm_client instead
async def create_langchain_llm(tenant_id: str | None = None) -> LLMClient:
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
