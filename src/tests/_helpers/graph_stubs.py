"""Graph store test stubs.

``NullGraphStoreStub`` provides no-op / empty default implementations of every
``GraphStorePort`` abstract method so unit-test stubs only need to override the
methods they actually exercise. This keeps test doubles tiny and insulates them
from growth of the port surface as new store primitives are added.
"""

from __future__ import annotations

from typing import Any

from src.domain.model.graph.dtos import (
    GraphCommunityDTO,
    GraphEntityDTO,
    GraphExportDTO,
    GraphGraphDataDTO,
    GraphSearchHit,
)
from src.domain.model.memory.episode import Episode
from src.domain.ports.services.graph_store_port import GraphStorePort


class NullGraphStoreStub(GraphStorePort):
    """Minimal ``GraphStorePort`` implementation for unit tests.

    All primitives return empty results. Subclass and override only the methods
    a given test cares about.
    """

    async def add_episode(self, episode: Episode) -> Episode:
        return episode

    async def search(self, query: str, project_id: str | None = None, limit: int = 10) -> list[Any]:
        return []

    async def get_graph_data(self, project_id: str, limit: int = 100) -> dict[str, Any]:
        return {"nodes": [], "edges": []}

    async def delete_episode(self, episode_name: str) -> bool:
        return True

    async def delete_episode_by_memory_id(self, memory_id: str) -> bool:
        return True

    async def remove_episode(self, episode_uuid: str) -> bool:
        return True

    async def initialize_schema(self) -> None:
        return None

    async def vector_search(
        self,
        query_vector: list[float],
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        return []

    async def fulltext_search(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        return []

    async def related_entities(
        self,
        entity_id: str,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[GraphEntityDTO]:
        return []

    async def community_read(
        self,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[GraphCommunityDTO]:
        return []

    async def graph_snapshot(self, project_id: str, limit: int = 100) -> GraphGraphDataDTO:
        return GraphGraphDataDTO()

    async def data_export(
        self,
        tenant_id: str | None = None,
        project_id: str | None = None,
        include_episodes: bool = True,
        include_entities: bool = True,
        include_relationships: bool = True,
        include_communities: bool = True,
    ) -> GraphExportDTO:
        return GraphExportDTO(exported_at="", tenant_id=tenant_id, project_id=project_id)

    async def count_nodes(
        self,
        project_id: str | None = None,
        tenant_id: str | None = None,
        label: str | None = None,
    ) -> int:
        return 0

    async def count_stats(
        self,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, int]:
        return {
            "entities": 0,
            "episodes": 0,
            "communities": 0,
            "relationships": 0,
            "total_nodes": 0,
        }

    async def count_episodes_by_age(
        self,
        cutoff_iso: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        return 0

    async def list_episodes(
        self,
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
        user_id: str | None = None,
        sort_by: str = "created_at",
        sort_desc: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        return {"episodes": [], "total": 0}

    async def get_episode_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        return None

    async def delete_episode_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> int:
        return 0

    async def recall_recent_episodes(
        self,
        *,
        since_iso: str,
        limit: int = 100,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def ensure_episodic_node(
        self,
        *,
        uuid: str,
        name: str,
        content: str,
        source_description: str,
        source: str,
        created_at_iso: str,
        group_id: str | None,
        tenant_id: str | None,
        project_id: str | None,
        user_id: str | None,
        memory_id: str | None,
    ) -> None:
        return None

    async def get_memory_graph_context(
        self,
        memory_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return [], []

    async def count_entities_by_project(self, project_ids: list[str]) -> dict[str, int]:
        return {}

    async def count_active_nodes(
        self,
        project_id: str,
        since_iso: str,
    ) -> int:
        return 0

    async def trending_entities(
        self,
        project_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return []

    async def get_entity_project_id(self, entity_uuid: str) -> str | None:
        return None

    async def get_community_project_id(self, community_uuid: str) -> str | None:
        return None

    async def graph_traversal_search(
        self,
        *,
        start_entity_uuid: str,
        max_depth: int,
        relationship_types: list[str] | None,
        limit: int,
        project_id: str,
    ) -> list[dict[str, Any]]:
        return []

    async def community_search(
        self,
        *,
        community_uuid: str,
        project_id: str,
        include_episodes: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        return []

    async def temporal_search(
        self,
        *,
        query: str | None,
        since_iso: str | None,
        until_iso: str | None,
        limit: int,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def faceted_search(
        self,
        *,
        query: str | None,
        entity_types: list[str] | None,
        tags: list[str] | None,
        since_iso: str | None,
        limit: int,
        offset: int,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def list_entities(
        self,
        *,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        return {"entities": [], "total": 0}

    async def list_communities(
        self,
        *,
        min_members: int | None = None,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        return {"communities": [], "total": 0}

    async def get_entity_types(
        self,
        *,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> list[dict[str, Any]]:
        return []

    async def get_entity(self, entity_uuid: str) -> dict[str, Any] | None:
        return None

    async def get_community(self, community_uuid: str) -> dict[str, Any] | None:
        return None

    async def get_entity_relationships(
        self,
        entity_uuid: str,
        *,
        relationship_type: str | None = None,
        limit: int = 50,
        project_id: str | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        return {"relationships": [], "total": 0}

    async def get_community_members(
        self,
        community_uuid: str,
        *,
        limit: int = 100,
        project_id: str | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        return {"members": [], "total": 0}

    async def get_graph_visualization(
        self,
        *,
        limit: int = 100,
        since: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        return []

    async def get_subgraph(
        self,
        *,
        node_uuids: list[str],
        include_neighbors: bool,
        limit: int,
        project_id: str | None,
        tenant_id: str | None,
        project_ids: list[str] | None,
        is_superuser: bool,
    ) -> list[dict[str, Any]]:
        return []

    async def rebuild_communities(self, project_id: str) -> dict[str, Any]:
        return {"communities_count": 0, "entities_processed": 0}

    async def count_scoped_nodes(
        self,
        label: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        return 0

    async def count_old_episodes(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        return 0

    async def find_duplicate_entities(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return []

    async def find_stale_edges(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, int]:
        return {}

    async def delete_stale_edges(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        return 0

    async def count_missing_embeddings(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        return 0

    async def get_existing_embedding_dimension(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int | None:
        return None

    async def detect_mixed_dimensions(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "has_mixed_dimensions": False,
            "counts": {},
            "dimensions": [],
            "total_embeddings": 0,
        }

    async def validate_embeddings(
        self,
        expected_dim: int,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "valid": True,
            "total_embeddings": 0,
            "dimension_mismatches": 0,
            "zero_vectors": 0,
            "expected_dimension": expected_dim,
        }

    async def rebuild_embeddings(
        self,
        embedder: Any,
        project_id: str,
    ) -> dict[str, int]:
        return {"processed": 0, "updated": 0, "failed": 0}

    async def clear_entity_embeddings(
        self,
        project_id: str | None = None,
    ) -> int:
        return 0

    async def get_vector_index_dimension(
        self, index_name: str = "entity_name_vector"
    ) -> int | None:
        return None

    async def create_vector_index(
        self,
        index_name: str,
        label: str,
        property_name: str,
        dimensions: int,
        similarity_function: str = "cosine",
    ) -> None:
        return None

    async def get_embedding_dimension_distribution(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> tuple[dict[str, int], int]:
        return {}, 0

    async def delete_episodes_by_age(
        self,
        cutoff_iso: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        return 0

    async def delete_entity(self, entity_id: str, project_id: str | None = None) -> bool:
        return True

    async def delete_project(self, project_id: str) -> int:
        return 0

    async def health_probe(self) -> bool:
        return True
