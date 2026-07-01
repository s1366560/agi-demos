"""Graph store DTO definitions (see package docstring)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GraphSearchHit:
    """A single vector/fulltext search result.

    Attributes:
        node: the matched node's properties as a dict.
        score: relevance/similarity score (higher = better).
    """

    node: dict[str, Any]
    score: float


@dataclass(frozen=True)
class GraphNodeDTO:
    """A node in a graph snapshot / visualization payload.

    Mirrors the shape produced by ``NativeGraphAdapter.get_graph_data``: every
    node carries at least id/label/type/uuid.
    """

    id: str
    label: str
    type: str
    uuid: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as the dict shape callers expect (extra merged in)."""
        out: dict[str, Any] = {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "uuid": self.uuid,
        }
        out.update(self.extra)
        return out


@dataclass(frozen=True)
class GraphRelationshipDTO:
    """An edge in a graph snapshot / visualization payload.

    Mirrors the edge shape produced by ``get_graph_data``: id/source/target/label.
    """

    id: str
    source: str
    target: str
    label: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as the dict shape callers expect (extra merged in)."""
        out: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "label": self.label,
        }
        out.update(self.extra)
        return out


@dataclass(frozen=True)
class GraphGraphDataDTO:
    """Visualization payload for a project subgraph (nodes + edges)."""

    nodes: list[GraphNodeDTO] = field(default_factory=list)
    edges: list[GraphRelationshipDTO] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Render as {'nodes': [...], 'edges': [...]} (frozen snapshot shape)."""
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }


# Alias kept for clarity at the port surface (graph_snapshot -> GraphSnapshotDTO).
GraphSnapshotDTO = GraphGraphDataDTO


@dataclass(frozen=True)
class GraphEntityDTO:
    """A typed entity record as read from the store (graph router list/detail)."""

    uuid: str
    name: str
    entity_type: str
    summary: str = ""
    project_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a dict, merging extra metadata."""
        out: dict[str, Any] = {
            "uuid": self.uuid,
            "name": self.name,
            "entity_type": self.entity_type,
            "summary": self.summary,
            "project_id": self.project_id,
        }
        out.update(self.extra)
        return out


@dataclass(frozen=True)
class GraphCommunityDTO:
    """A community record as read from the store."""

    uuid: str
    name: str
    summary: str = ""
    member_count: int = 0
    project_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Render as a dict, merging extra metadata."""
        out: dict[str, Any] = {
            "uuid": self.uuid,
            "name": self.name,
            "summary": self.summary,
            "member_count": self.member_count,
            "project_id": self.project_id,
        }
        out.update(self.extra)
        return out


@dataclass(frozen=True)
class GraphExportDTO:
    """Envelope returned by the data-export operation.

    Mirrors the shape produced by the ``data_export`` router: exported_at,
    tenant_id, project_id, and episodes/entities/relationships/communities lists.
    """

    exported_at: str
    tenant_id: str | None
    project_id: str | None
    episodes: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    communities: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Render as the export envelope dict (frozen snapshot shape)."""
        return {
            "exported_at": self.exported_at,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "episodes": list(self.episodes),
            "entities": list(self.entities),
            "relationships": list(self.relationships),
            "communities": list(self.communities),
        }
