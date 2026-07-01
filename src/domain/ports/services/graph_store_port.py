"""GraphStorePort - the pluggable graph backend contract.

This port replaces ``GraphServicePort``. It models the graph *store* (not just
orchestration): every operation the application/routers need to perform against
a graph backend is declared here as a semantic primitive, so that any backend
implementation (Neo4j today, ArcadeDB / Apache AGE tomorrow) can be swapped
behind a single interface.

Result shapes are defined by the typed DTOs in ``src.domain.model.graph`` and
are frozen by the integration contract tests
(``src/tests/integration/graph/test_graph_store_contract.py``).

The first six methods (add_episode, search, get_graph_data, delete_episode,
delete_episode_by_memory_id, remove_episode) are carried over verbatim from the
former ``GraphServicePort`` so existing callers keep working during the
migration. The remaining methods are the new semantic store primitives that
collapse the raw-Cypher bypasses previously scattered across routers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.domain.model.graph.dtos import (
    GraphCommunityDTO,
    GraphEntityDTO,
    GraphExportDTO,
    GraphGraphDataDTO,
    GraphSearchHit,
)
from src.domain.model.memory.episode import Episode


class GraphStorePort(ABC):
    """Pluggable graph backend port."""

    # ------------------------------------------------------------------
    # Carried-over GraphServicePort operations (coarse-grained)
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_episode(self, episode: Episode) -> Episode:
        """Persist an episode and queue it for entity extraction."""

    @abstractmethod
    async def search(self, query: str, project_id: str | None = None, limit: int = 10) -> list[Any]:
        """Hybrid (vector + keyword) search returning episode/entity dicts."""

    @abstractmethod
    async def get_graph_data(self, project_id: str, limit: int = 100) -> dict[str, Any]:
        """Return {'nodes': [...], 'edges': [...]} for visualization."""

    @abstractmethod
    async def delete_episode(self, episode_name: str) -> bool:
        """Delete an episode by name."""

    @abstractmethod
    async def delete_episode_by_memory_id(self, memory_id: str) -> bool:
        """Delete an episode by its associated memory_id."""

    @abstractmethod
    async def remove_episode(self, episode_uuid: str) -> bool:
        """Remove an episode and clean up orphaned entities/edges."""

    # ------------------------------------------------------------------
    # Episode lifecycle helpers (used by routers/services)
    # ------------------------------------------------------------------

    async def remove_episode_by_memory_id(self, memory_id: str) -> bool:  # pragma: no cover
        """Remove an episode by memory_id with orphan cleanup.

        Optional override; default delegates to ``delete_episode_by_memory_id``.
        """
        return await self.delete_episode_by_memory_id(memory_id)

    async def search_memories(  # pragma: no cover
        self,
        query: str,
        project_id: str | None = None,
        limit: int = 10,
        **kwargs: Any,  # noqa: ANN401
    ) -> list[Any]:
        """Memory-oriented search. Optional override; default delegates to ``search``."""
        return await self.search(query=query, project_id=project_id, limit=limit)

    # ------------------------------------------------------------------
    # New semantic store primitives
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize_schema(self) -> None:
        """Create indices/constraints/vector indexes required by this backend."""

    @abstractmethod
    async def vector_search(
        self,
        query_vector: list[float],
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        """Vector similarity search over entity embeddings."""

    @abstractmethod
    async def fulltext_search(
        self,
        query: str,
        limit: int = 10,
        project_id: str | None = None,
        index_name: str | None = None,
    ) -> list[GraphSearchHit]:
        """Fulltext search over nodes (entities / episodes)."""

    @abstractmethod
    async def related_entities(
        self,
        entity_id: str,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[GraphEntityDTO]:
        """Return entities related to ``entity_id`` within the project scope."""

    @abstractmethod
    async def community_read(
        self,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[GraphCommunityDTO]:
        """Read communities for a project (or tenant-wide when project_id is None)."""

    @abstractmethod
    async def graph_snapshot(self, project_id: str, limit: int = 100) -> GraphGraphDataDTO:
        """Return a typed nodes/edges snapshot for a project (graph visualization)."""

    @abstractmethod
    async def data_export(
        self,
        tenant_id: str | None = None,
        project_id: str | None = None,
        include_episodes: bool = True,
        include_entities: bool = True,
        include_relationships: bool = True,
        include_communities: bool = True,
    ) -> GraphExportDTO:
        """Export graph data as a typed envelope."""

    @abstractmethod
    async def count_nodes(
        self,
        project_id: str | None = None,
        tenant_id: str | None = None,
        label: str | None = None,
    ) -> int:
        """Count nodes (optionally by label and/or scope)."""

    @abstractmethod
    async def count_stats(
        self,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, int]:
        """Return per-type node + relationship counts (entities/episodes/
        communities/relationships/total_nodes)."""

    @abstractmethod
    async def count_episodes_by_age(
        self,
        cutoff_iso: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Count episodes older than an ISO cutoff datetime, scoped by project/tenant."""

    @abstractmethod
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
        """List episodes with filtering/sorting/pagination; return {'episodes', 'total'}."""

    @abstractmethod
    async def get_episode_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Return a single episode's properties by name, or None if not found."""

    @abstractmethod
    async def delete_episode_by_name(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> int:
        """Delete an episode by name (DETACH DELETE); return count deleted."""

    @abstractmethod
    async def recall_recent_episodes(
        self,
        *,
        since_iso: str,
        limit: int = 100,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return episodes created at/after an ISO datetime, newest first."""

    @abstractmethod
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
        """Pre-create an Episodic node (MERGE) to avoid write races."""

    @abstractmethod
    async def get_memory_graph_context(
        self,
        memory_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Load entities + relationships connected to a memory's episode."""

    @abstractmethod
    async def count_entities_by_project(self, project_ids: list[str]) -> dict[str, int]:
        """Bulk entity counts per project_id; return {project_id: count}."""

    @abstractmethod
    async def count_active_nodes(
        self,
        project_id: str,
        since_iso: str,
    ) -> int:
        """Count nodes valid at/after an ISO datetime within a project."""

    @abstractmethod
    async def trending_entities(
        self,
        project_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return top entities by relationship count for a project."""

    @abstractmethod
    async def get_entity_project_id(self, entity_uuid: str) -> str | None:
        """Return the project_id of an Entity node, or None if absent."""

    @abstractmethod
    async def get_community_project_id(self, community_uuid: str) -> str | None:
        """Return the project_id of a Community node, or None if absent."""

    @abstractmethod
    async def graph_traversal_search(
        self,
        *,
        start_entity_uuid: str,
        max_depth: int,
        relationship_types: list[str] | None,
        limit: int,
        project_id: str,
    ) -> list[dict[str, Any]]:
        """Traverse the graph from a starting entity; return related nodes."""

    @abstractmethod
    async def community_search(
        self,
        *,
        community_uuid: str,
        project_id: str,
        include_episodes: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return entities (and optionally episodes) within a community."""

    @abstractmethod
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
        """Search Episodic nodes within a time window + scope."""

    @abstractmethod
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
        """Search Entity nodes with faceted filters + scope."""

    @abstractmethod
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
        """List entities with filters + pagination; return {'entities', 'total'}."""

    @abstractmethod
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
        """List communities with filters + pagination; return {'communities', 'total'}."""

    @abstractmethod
    async def get_entity_types(
        self,
        *,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> list[dict[str, Any]]:
        """Return distinct entity types with counts, scoped."""

    @abstractmethod
    async def get_entity(self, entity_uuid: str) -> dict[str, Any] | None:
        """Return an entity's props + labels by uuid, or None if absent."""

    @abstractmethod
    async def get_community(self, community_uuid: str) -> dict[str, Any] | None:
        """Return a community's props by uuid, or None if absent."""

    @abstractmethod
    async def get_entity_relationships(
        self,
        entity_uuid: str,
        *,
        relationship_type: str | None = None,
        limit: int = 50,
        project_id: str | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """Return relationships (out+in) for an entity; {'relationships', 'total'}."""

    @abstractmethod
    async def get_community_members(
        self,
        community_uuid: str,
        *,
        limit: int = 100,
        project_id: str | None = None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """Return member entities of a community; {'members', 'total'}."""

    @abstractmethod
    async def get_graph_visualization(
        self,
        *,
        limit: int = 100,
        since: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        project_ids: list[str] | None = None,
        is_superuser: bool = False,
    ) -> list[dict[str, Any]]:
        """Return graph visualization rows (source/target/edge props+labels)."""

    @abstractmethod
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
        """Return subgraph rows for the given node uuids."""

    @abstractmethod
    async def rebuild_communities(self, project_id: str) -> dict[str, Any]:
        """Rebuild communities for a project; return {'communities_count', 'entities_processed'}."""

    # ------------------------------------------------------------------
    # maintenance.py router primitives
    # ------------------------------------------------------------------

    @abstractmethod
    async def count_scoped_nodes(
        self,
        label: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Count nodes of a label within the maintenance project scope."""

    @abstractmethod
    async def count_old_episodes(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Count episodes older than a cutoff within the maintenance scope."""

    @abstractmethod
    async def find_duplicate_entities(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Find entity groups sharing an exact name within the scope."""

    @abstractmethod
    async def find_stale_edges(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, int]:
        """Return {rel_type: count} of edges older than a cutoff within scope."""

    @abstractmethod
    async def delete_stale_edges(
        self,
        cutoff_iso: str,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Delete edges older than a cutoff within scope; return count deleted."""

    @abstractmethod
    async def count_missing_embeddings(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int:
        """Count Entity nodes missing name_embedding within the scope."""

    @abstractmethod
    async def get_existing_embedding_dimension(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> int | None:
        """Detect the existing embedding dimension in the database, or None."""

    @abstractmethod
    async def detect_mixed_dimensions(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Detect mixed embedding dimensions within the scope."""

    @abstractmethod
    async def validate_embeddings(
        self,
        expected_dim: int,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Validate embeddings (dimension mismatches + zero vectors) in scope."""

    @abstractmethod
    async def rebuild_embeddings(
        self,
        embedder: Any,  # noqa: ANN401
        project_id: str,
    ) -> dict[str, int]:
        """Regenerate all entity embeddings for a project using ``embedder``."""

    @abstractmethod
    async def clear_entity_embeddings(
        self,
        project_id: str | None = None,
    ) -> int:
        """Clear entity embeddings (optionally project-scoped); return count cleared."""

    @abstractmethod
    async def get_vector_index_dimension(
        self, index_name: str = "entity_name_vector"
    ) -> int | None:
        """Return the dimension of an existing vector index, or None if absent."""

    @abstractmethod
    async def create_vector_index(
        self,
        index_name: str,
        label: str,
        property_name: str,
        dimensions: int,
        similarity_function: str = "cosine",
    ) -> None:
        """Create a vector index."""

    @abstractmethod
    async def get_embedding_dimension_distribution(
        self,
        project_id: str | None = None,
        is_superuser: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> tuple[dict[str, int], int]:
        """Return ({dim: count}, total) of embeddings within the maintenance scope."""

    @abstractmethod
    async def delete_episodes_by_age(
        self,
        cutoff_iso: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> int:
        """Delete episodes older than an ISO cutoff datetime; return count deleted."""

    @abstractmethod
    async def delete_entity(self, entity_id: str, project_id: str | None = None) -> bool:
        """Delete an entity node by uuid within the project scope."""

    @abstractmethod
    async def delete_project(self, project_id: str) -> int:
        """Delete all graph data for a project; return number of nodes removed."""

    @abstractmethod
    async def health_probe(self) -> bool:
        """Return True iff the backend is reachable and responsive."""
