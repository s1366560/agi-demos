"""
Native Graph Module - Self-developed knowledge graph processing system.

This module replaces the vendor/graphiti dependency with a native implementation
that directly interfaces with Neo4j and uses LiteLLM for entity extraction.

Modules:
    - neo4j_client: Neo4j driver wrapper with connection pooling
    - schemas: Pydantic models for graph nodes and relationships
    - extraction: Entity and relationship extraction using LLM
    - embedding: Vector embedding service wrapper
    - search: Hybrid search (vector + keyword + RRF)
    - community: Community detection and summarization
    - native_graph_adapter: Main adapter implementing GraphServicePort
"""

from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.graph.neo4j_client import Neo4jClient
from src.infrastructure.graph.schemas import (
    AddEpisodeResult,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicEdge,
    EpisodicNode,
    ExtractedEntity,
    ExtractedRelationship,
    HybridSearchResult,
    SearchResultItem,
)

__all__ = [
    "NativeGraphAdapter",
    "Neo4jClient",
    "EpisodicNode",
    "EntityNode",
    "CommunityNode",
    "EpisodicEdge",
    "EntityEdge",
    "ExtractedEntity",
    "ExtractedRelationship",
    "AddEpisodeResult",
    "HybridSearchResult",
    "SearchResultItem",
]
