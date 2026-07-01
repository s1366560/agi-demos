"""Graph store DTOs.

Read-only data-transfer objects returned by ``GraphStorePort`` primitives. These
freeze the result shapes of the graph backend (today Neo4j) so that any pluggable
backend implementation (Neo4j, ArcadeDB, AGE, ...) produces structurally
identical results at the port boundary.

These are value objects (immutable snapshots of query results), distinct from the
``src.domain.model.memory`` domain entities which model long-lived business
identity (Episode / Entity / Community). Store DTOs are what routers and
application services consume from the store layer.
"""

from src.domain.model.graph.dtos import (
    GraphCommunityDTO,
    GraphEntityDTO,
    GraphExportDTO,
    GraphGraphDataDTO,
    GraphNodeDTO,
    GraphRelationshipDTO,
    GraphSearchHit,
    GraphSnapshotDTO,
)

__all__ = [
    "GraphCommunityDTO",
    "GraphEntityDTO",
    "GraphExportDTO",
    "GraphGraphDataDTO",
    "GraphNodeDTO",
    "GraphRelationshipDTO",
    "GraphSearchHit",
    "GraphSnapshotDTO",
]
