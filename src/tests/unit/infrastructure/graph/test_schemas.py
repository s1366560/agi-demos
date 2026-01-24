"""Unit tests for graph schemas."""

from datetime import datetime
from uuid import uuid4

import pytest

from src.infrastructure.graph.schemas import (
    AddEpisodeResult,
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodeStatus,
    EpisodeType,
    EpisodicNode,
    ExtractedEntity,
    ExtractedRelationship,
    HybridSearchResult,
    SearchResultItem,
)


@pytest.mark.unit
class TestEpisodicNode:
    """Tests for EpisodicNode schema."""

    def test_create_episodic_node_minimal(self):
        """Test creating episodic node with minimal fields."""
        node = EpisodicNode(
            name="test-episode",
            content="This is test content.",
        )

        assert node.name == "test-episode"
        assert node.content == "This is test content."
        assert node.uuid is not None
        assert node.status == EpisodeStatus.PROCESSING
        assert node.source == EpisodeType.TEXT
        assert node.group_id == "global"

    def test_create_episodic_node_full(self):
        """Test creating episodic node with all fields."""
        uuid = str(uuid4())
        now = datetime.utcnow()

        node = EpisodicNode(
            uuid=uuid,
            name="full-episode",
            content="Full content here.",
            source_description="user input",
            source=EpisodeType.DOCUMENT,
            valid_at=now,
            group_id="project-123",
            tenant_id="tenant-1",
            project_id="project-1",
            user_id="user-1",
            memory_id="memory-1",
            status=EpisodeStatus.SYNCED,
            entity_edges=["edge-1", "edge-2"],
        )

        assert node.uuid == uuid
        assert node.source == EpisodeType.DOCUMENT
        assert node.status == EpisodeStatus.SYNCED
        assert len(node.entity_edges) == 2

    def test_episodic_node_labels(self):
        """Test getting Neo4j labels."""
        node = EpisodicNode(name="test", content="test")
        labels = node.get_labels()

        assert "Episodic" in labels
        assert "Node" in labels

    def test_episodic_node_to_neo4j_properties(self):
        """Test converting to Neo4j properties."""
        node = EpisodicNode(
            name="test",
            content="test content",
            project_id="proj-1",
        )

        props = node.to_neo4j_properties()

        assert props["name"] == "test"
        assert props["content"] == "test content"
        assert props["project_id"] == "proj-1"
        assert props["status"] == "Processing"
        assert "uuid" in props
        assert "created_at" in props


@pytest.mark.unit
class TestEntityNode:
    """Tests for EntityNode schema."""

    def test_create_entity_node_minimal(self):
        """Test creating entity node with minimal fields."""
        node = EntityNode(
            name="John Doe",
            entity_type="Person",
        )

        assert node.name == "John Doe"
        assert node.entity_type == "Person"
        assert node.summary == ""
        assert node.name_embedding is None

    def test_create_entity_node_with_embedding(self):
        """Test creating entity node with embedding."""
        embedding = [0.1] * 768

        node = EntityNode(
            name="Acme Corp",
            entity_type="Organization",
            summary="A technology company",
            name_embedding=embedding,
        )

        assert node.name_embedding is not None
        assert len(node.name_embedding) == 768

    def test_entity_node_labels(self):
        """Test getting Neo4j labels."""
        node = EntityNode(name="test", entity_type="Concept")
        labels = node.get_labels()

        assert "Entity" in labels
        assert "Node" in labels

    def test_entity_node_to_neo4j_properties(self):
        """Test converting to Neo4j properties."""
        node = EntityNode(
            name="Test Entity",
            entity_type="Person",
            summary="A test person",
            attributes={"age": 30},
        )

        props = node.to_neo4j_properties()

        assert props["name"] == "Test Entity"
        assert props["entity_type"] == "Person"
        assert props["summary"] == "A test person"
        # attributes are JSON-serialized for Neo4j compatibility
        assert props["attributes"] == '{"age": 30}'


@pytest.mark.unit
class TestCommunityNode:
    """Tests for CommunityNode schema."""

    def test_create_community_node(self):
        """Test creating community node."""
        node = CommunityNode(
            name="Tech Community",
            summary="A community of tech entities",
            member_count=5,
        )

        assert node.name == "Tech Community"
        assert node.member_count == 5

    def test_community_node_labels(self):
        """Test getting Neo4j labels."""
        node = CommunityNode(name="test")
        labels = node.get_labels()

        assert "Community" in labels


@pytest.mark.unit
class TestEntityEdge:
    """Tests for EntityEdge schema."""

    def test_create_entity_edge(self):
        """Test creating entity edge."""
        edge = EntityEdge(
            source_uuid="entity-1",
            target_uuid="entity-2",
            relationship_type="WORKS_AT",
            summary="Employee relationship",
            weight=0.8,
        )

        assert edge.source_uuid == "entity-1"
        assert edge.target_uuid == "entity-2"
        assert edge.relationship_type == "WORKS_AT"
        assert edge.weight == 0.8

    def test_entity_edge_default_weight(self):
        """Test default weight value."""
        edge = EntityEdge(
            source_uuid="e1",
            target_uuid="e2",
            relationship_type="KNOWS",
        )

        assert edge.weight == 0.5

    def test_entity_edge_to_neo4j_properties(self):
        """Test converting to Neo4j properties."""
        edge = EntityEdge(
            source_uuid="e1",
            target_uuid="e2",
            relationship_type="RELATED_TO",
            episodes=["ep-1", "ep-2"],
        )

        props = edge.to_neo4j_properties()

        assert props["relationship_type"] == "RELATED_TO"
        assert props["episodes"] == ["ep-1", "ep-2"]
        assert "uuid" in props

    def test_entity_edge_weight_validation_too_low(self):
        """Test that weight below 0 raises validation error."""
        import pydantic

        with pytest.raises(pydantic.ValidationError) as exc_info:
            EntityEdge(
                source_uuid="e1",
                target_uuid="e2",
                relationship_type="KNOWS",
                weight=-0.1,
            )

        assert "Weight must be between 0 and 1" in str(exc_info.value)

    def test_entity_edge_weight_validation_too_high(self):
        """Test that weight above 1 raises validation error."""
        import pydantic

        with pytest.raises(pydantic.ValidationError) as exc_info:
            EntityEdge(
                source_uuid="e1",
                target_uuid="e2",
                relationship_type="KNOWS",
                weight=1.5,
            )

        assert "Weight must be between 0 and 1" in str(exc_info.value)

    def test_entity_edge_weight_validation_boundary_values(self):
        """Test that weight at boundaries (0 and 1) are valid."""
        edge_min = EntityEdge(
            source_uuid="e1",
            target_uuid="e2",
            relationship_type="KNOWS",
            weight=0.0,
        )
        assert edge_min.weight == 0.0

        edge_max = EntityEdge(
            source_uuid="e1",
            target_uuid="e2",
            relationship_type="KNOWS",
            weight=1.0,
        )
        assert edge_max.weight == 1.0


@pytest.mark.unit
class TestExtractedEntity:
    """Tests for ExtractedEntity schema."""

    def test_create_extracted_entity(self):
        """Test creating extracted entity."""
        entity = ExtractedEntity(
            name="Machine Learning",
            entity_type="Concept",
            summary="A field of AI",
            attributes={"domain": "AI"},
        )

        assert entity.name == "Machine Learning"
        assert entity.entity_type == "Concept"
        assert entity.attributes["domain"] == "AI"


@pytest.mark.unit
class TestExtractedRelationship:
    """Tests for ExtractedRelationship schema."""

    def test_create_extracted_relationship(self):
        """Test creating extracted relationship."""
        rel = ExtractedRelationship(
            from_entity="John",
            to_entity="Acme",
            relationship_type="WORKS_AT",
            summary="John is an employee",
            weight=0.9,
        )

        assert rel.from_entity == "John"
        assert rel.to_entity == "Acme"
        assert rel.relationship_type == "WORKS_AT"

    def test_weight_bounds(self):
        """Test weight value bounds."""
        # Valid weight
        rel = ExtractedRelationship(
            from_entity="A",
            to_entity="B",
            relationship_type="KNOWS",
            weight=0.5,
        )
        assert 0.0 <= rel.weight <= 1.0


@pytest.mark.unit
class TestSearchResults:
    """Tests for search result schemas."""

    def test_search_result_item(self):
        """Test SearchResultItem."""
        item = SearchResultItem(
            type="entity",
            uuid="entity-123",
            name="Test Entity",
            score=0.95,
        )

        assert item.type == "entity"
        assert item.score == 0.95

    def test_hybrid_search_result(self):
        """Test HybridSearchResult."""
        items = [
            SearchResultItem(type="entity", uuid="e1", score=0.9),
            SearchResultItem(type="episode", uuid="ep1", score=0.8),
        ]

        result = HybridSearchResult(
            items=items,
            total_results=2,
            vector_results_count=1,
            keyword_results_count=1,
        )

        assert len(result.items) == 2
        assert result.total_results == 2


@pytest.mark.unit
class TestAddEpisodeResult:
    """Tests for AddEpisodeResult schema."""

    def test_create_add_episode_result(self):
        """Test creating AddEpisodeResult."""
        episode = EpisodicNode(name="test", content="content")
        entities = [EntityNode(name="Entity1", entity_type="Person")]
        edges = [
            EntityEdge(
                source_uuid="e1",
                target_uuid="e2",
                relationship_type="KNOWS",
            )
        ]

        result = AddEpisodeResult(
            episode=episode,
            nodes=entities,
            edges=edges,
        )

        assert result.episode.name == "test"
        assert len(result.nodes) == 1
        assert len(result.edges) == 1
        assert len(result.communities) == 0
