"""
Pydantic models for graph nodes, edges, and LLM extraction results.

This module defines the data structures used throughout the native graph system:
- Node schemas (Episodic, Entity, Community)
- Edge schemas (EpisodicEdge, EntityEdge)
- LLM extraction results (ExtractedEntity, ExtractedRelationship)
"""

import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class EpisodeType(str, Enum):
    """Type of episode content source."""

    TEXT = "text"
    JSON = "json"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"


class EpisodeStatus(str, Enum):
    """Processing status of an episode."""

    PROCESSING = "Processing"
    SYNCED = "Synced"
    FAILED = "Failed"


# =============================================================================
# Node Schemas
# =============================================================================


class BaseNode(BaseModel):
    """Base class for all graph nodes."""

    uuid: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None

    class Config:
        """Pydantic config."""

        extra = "allow"


class EpisodicNode(BaseNode):
    """
    Episodic node representing an event or interaction.

    Episodic nodes store raw content and metadata about events/interactions.
    They are the entry point for knowledge graph construction.
    """

    name: str
    content: str
    source_description: str = ""
    source: EpisodeType = EpisodeType.TEXT
    valid_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    group_id: str = "global"
    memory_id: str | None = None
    status: EpisodeStatus = EpisodeStatus.PROCESSING
    entity_edges: list[str] = Field(default_factory=list)  # Edge UUIDs

    def get_labels(self) -> list[str]:
        """Get Neo4j labels for this node."""
        return ["Episodic", "Node"]

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible property dict."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "content": self.content,
            "source_description": self.source_description,
            "source": self.source.value,
            "created_at": self.created_at.isoformat(),
            "valid_at": self.valid_at.isoformat(),
            "group_id": self.group_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "memory_id": self.memory_id,
            "status": self.status.value,
            "entity_edges": self.entity_edges,
        }


class EntityNode(BaseNode):
    """
    Entity node representing a real-world object.

    Entity nodes are extracted from episodic content and represent
    people, organizations, locations, concepts, etc.

    Attributes:
        name: The entity's name as it appears in text
        entity_type: Primary type classification (Person, Organization, etc.)
        labels: Additional Neo4j labels for custom entity types
        summary: Brief description of the entity
        name_embedding: Vector embedding for semantic search
        attributes: Flexible dict for type-specific attributes
    """

    name: str
    entity_type: str  # e.g., "Person", "Organization", "Location", "Concept"
    labels: list[str] = Field(default_factory=list)  # Additional Neo4j labels
    summary: str = ""
    name_embedding: list[float] | None = None
    embedding_dim: int | None = None  # Dimension of the embedding vector
    attributes: dict[str, Any] = Field(default_factory=dict)

    def get_labels(self) -> list[str]:
        """Get Neo4j labels for this node including custom labels."""
        base_labels = ["Entity", "Node"]
        # Add custom labels (ensure uniqueness)
        all_labels = base_labels + [lbl for lbl in self.labels if lbl not in base_labels]
        return all_labels

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible property dict."""
        props = {
            "uuid": self.uuid,
            "name": self.name,
            "entity_type": self.entity_type,
            "labels": self.labels,  # Store labels as property too for querying
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            # Serialize attributes dict to JSON string (Neo4j doesn't accept Map values)
            "attributes": json.dumps(self.attributes) if self.attributes else "{}",
        }
        if self.name_embedding:
            props["name_embedding"] = self.name_embedding
            props["embedding_dim"] = len(self.name_embedding)
        return props


class CommunityNode(BaseNode):
    """
    Community node representing a cluster of related entities.

    Communities are automatically detected using graph clustering algorithms
    and provide high-level summaries of entity groups.
    """

    name: str
    summary: str = ""
    member_count: int = 0

    def get_labels(self) -> list[str]:
        """Get Neo4j labels for this node."""
        return ["Community"]

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible property dict."""
        return {
            "uuid": self.uuid,
            "name": self.name,
            "summary": self.summary,
            "member_count": self.member_count,
            "created_at": self.created_at.isoformat(),
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
        }


# =============================================================================
# Edge Schemas
# =============================================================================


class BaseEdge(BaseModel):
    """Base class for all graph edges."""

    uuid: str = Field(default_factory=lambda: str(uuid4()))
    source_uuid: str
    target_uuid: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Config:
        """Pydantic config."""

        extra = "allow"


class EpisodicEdge(BaseEdge):
    """
    Edge from Episodic node to Entity node (MENTIONS relationship).

    This edge indicates that an entity was mentioned in an episode.
    """

    relationship_type: str = "MENTIONS"

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible property dict."""
        return {
            "created_at": self.created_at.isoformat(),
        }


class EntityEdge(BaseEdge):
    """
    Edge between Entity nodes (RELATES_TO relationship).

    This edge represents a semantic relationship between two entities,
    such as "works at", "lives in", "knows about", etc.

    Attributes:
        relationship_type: Type of relationship in SCREAMING_SNAKE_CASE
        fact: Natural language description of the fact/relationship
        summary: Brief summary (deprecated, use fact instead)
        weight: Relationship strength (0-1)
        episodes: List of supporting episode UUIDs
        valid_at: When the fact became true
        invalid_at: When the fact stopped being true
        expired_at: When this edge was invalidated/superseded
        attributes: Flexible dict for relationship-specific attributes
        relationship_embedding: Vector embedding of the fact for semantic search
    """

    relationship_type: str  # e.g., "WORKS_AT", "LIVES_IN", "KNOWS"
    fact: str = ""  # Natural language fact description
    summary: str = ""  # Deprecated, kept for backwards compatibility
    weight: float = 0.5  # Relationship strength (0-1)
    episodes: list[str] = Field(default_factory=list)  # Supporting episode UUIDs
    valid_at: datetime | None = None  # When fact became true
    invalid_at: datetime | None = None  # When fact stopped being true
    expired_at: datetime | None = None  # When edge was invalidated
    attributes: dict[str, Any] = Field(default_factory=dict)  # Additional attributes
    relationship_embedding: list[float] | None = None  # Fact embedding

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, v: float) -> float:
        """Ensure weight is between 0 and 1."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Weight must be between 0 and 1, got {v}")
        return v

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible property dict."""
        props = {
            "uuid": self.uuid,
            "relationship_type": self.relationship_type,
            "fact": self.fact or self.summary,  # Use fact, fallback to summary
            "summary": self.summary,  # Keep for backwards compatibility
            "weight": self.weight,
            "episodes": self.episodes,
            "created_at": self.created_at.isoformat(),
            "attributes": json.dumps(self.attributes) if self.attributes else "{}",
        }
        if self.valid_at:
            props["valid_at"] = self.valid_at.isoformat()
        if self.invalid_at:
            props["invalid_at"] = self.invalid_at.isoformat()
        if self.expired_at:
            props["expired_at"] = self.expired_at.isoformat()
        if self.relationship_embedding:
            props["relationship_embedding"] = self.relationship_embedding
        return props


class CommunityEdge(BaseEdge):
    """
    Edge from Entity to Community (BELONGS_TO relationship).

    This edge indicates that an entity belongs to a community.
    """

    relationship_type: str = "BELONGS_TO"

    def to_neo4j_properties(self) -> dict[str, Any]:
        """Convert to Neo4j-compatible property dict."""
        return {
            "created_at": self.created_at.isoformat(),
        }


# =============================================================================
# LLM Extraction Results
# =============================================================================


class ExtractedEntity(BaseModel):
    """
    Entity extracted by LLM from text content.

    This is the intermediate representation before converting to EntityNode.
    """

    name: str = Field(description="Entity name as it appears in the text")
    entity_type: str = Field(description="Type of entity (Person, Organization, etc.)")
    entity_type_id: int | None = Field(
        default=None, description="ID of the classified entity type from provided types"
    )
    labels: list[str] = Field(
        default_factory=list, description="Additional labels for custom entity types"
    )
    summary: str = Field(default="", description="Brief description of the entity")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Additional attributes extracted"
    )


class ExtractedRelationship(BaseModel):
    """
    Relationship extracted by LLM from text content.

    This is the intermediate representation before converting to EntityEdge.
    """

    from_entity: str = Field(description="Name of the source entity")
    to_entity: str = Field(description="Name of the target entity")
    relationship_type: str = Field(description="Type of relationship in SCREAMING_SNAKE_CASE")
    fact: str = Field(default="", description="Natural language fact describing the relationship")
    summary: str = Field(default="", description="Deprecated: use fact instead")
    weight: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Confidence/strength of the relationship"
    )
    valid_at: str | None = Field(
        default=None, description="ISO 8601 datetime when the fact became true"
    )
    invalid_at: str | None = Field(
        default=None, description="ISO 8601 datetime when the fact stopped being true"
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Additional relationship attributes"
    )


class EntityExtractionResult(BaseModel):
    """Result of entity extraction from LLM."""

    entities: list[ExtractedEntity] = Field(default_factory=list)


class RelationshipExtractionResult(BaseModel):
    """Result of relationship extraction from LLM."""

    relationships: list[ExtractedRelationship] = Field(default_factory=list)


class ReflexionResult(BaseModel):
    """Result of reflexion check for missed entities."""

    missed_entities: list[ExtractedEntity] = Field(default_factory=list)
    explanation: str = Field(default="", description="Explanation of missed entities")


# =============================================================================
# Search Results
# =============================================================================


class SearchResultItem(BaseModel):
    """Individual search result item."""

    type: str  # "episode" or "entity"
    uuid: str
    name: str | None = None
    content: str | None = None
    summary: str | None = None
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class HybridSearchResult(BaseModel):
    """Result of hybrid search combining vector and keyword search."""

    items: list[SearchResultItem] = Field(default_factory=list)
    total_results: int = 0
    vector_results_count: int = 0
    keyword_results_count: int = 0


# =============================================================================
# Episode Processing Results
# =============================================================================


class AddEpisodeResult(BaseModel):
    """Result of adding an episode to the knowledge graph."""

    episode: EpisodicNode
    nodes: list[EntityNode] = Field(default_factory=list)
    edges: list[EntityEdge] = Field(default_factory=list)
    episodic_edges: list[EpisodicEdge] = Field(default_factory=list)
    communities: list[CommunityNode] = Field(default_factory=list)
    community_edges: list[CommunityEdge] = Field(default_factory=list)
