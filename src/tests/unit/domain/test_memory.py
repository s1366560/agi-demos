"""
Unit tests for Memory domain model.
"""

from src.domain.model.enums import ProcessingStatus
from src.domain.model.memory.memory import Memory


class TestMemory:
    """Test suite for Memory domain model"""

    def test_create_memory(self):
        """Test creating a new memory"""
        memory = Memory(
            id="test-memory-id",
            project_id="project-123",
            title="Test Memory",
            content="This is test content",
            author_id="user-456",
            content_type="text",
            tags=["test", "sample"],
            is_public=False,
            status="ENABLED",
            processing_status=ProcessingStatus.PENDING.value,
        )

        assert memory.id == "test-memory-id"
        assert memory.project_id == "project-123"
        assert memory.title == "Test Memory"
        assert memory.content == "This is test content"
        assert memory.author_id == "user-456"
        assert memory.content_type == "text"
        assert memory.tags == ["test", "sample"]
        assert memory.is_public is False
        assert memory.status == "ENABLED"
        assert memory.processing_status == ProcessingStatus.PENDING.value
        assert memory.created_at is not None
        assert memory.updated_at is None

    def test_memory_generate_id(self):
        """Test that memory ID generation creates unique IDs"""
        memory1 = Memory.create_id()
        memory2 = Memory.create_id()

        assert memory1 != memory2
        assert isinstance(memory1, str)
        assert isinstance(memory2, str)

    def test_memory_with_collaborators(self):
        """Test memory with collaborators"""
        collaborators = ["user-1", "user-2", "user-3"]
        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Shared Memory",
            content="Content to share",
            author_id="user-owner",
            collaborators=collaborators,
        )

        assert memory.collaborators == collaborators
        assert len(memory.collaborators) == 3

    def test_memory_with_entities(self):
        """Test memory with extracted entities"""
        entities = [
            {"name": "Person", "type": "PERSON", "confidence": 0.95},
            {"name": "Organization", "type": "ORG", "confidence": 0.88},
        ]

        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Entity Test",
            content="Content with entities",
            author_id="user-123",
            entities=entities,
        )

        assert memory.entities == entities
        assert len(memory.entities) == 2

    def test_memory_with_relationships(self):
        """Test memory with entity relationships"""
        relationships = [
            {"source": "Person1", "target": "Organization1", "type": "WORKS_AT"},
            {"source": "Person1", "target": "Person2", "type": "KNOWS"},
        ]

        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Relationship Test",
            content="Content with relationships",
            author_id="user-123",
            relationships=relationships,
        )

        assert memory.relationships == relationships
        assert len(memory.relationships) == 2

    def test_memory_status_transitions(self):
        """Test memory processing status transitions"""
        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Status Test",
            content="Content",
            author_id="user-123",
            processing_status=ProcessingStatus.PENDING.value,
        )

        # PENDING -> PROCESSING
        memory.processing_status = ProcessingStatus.PROCESSING.value
        assert memory.processing_status == ProcessingStatus.PROCESSING.value

        # PROCESSING -> COMPLETED
        memory.processing_status = ProcessingStatus.COMPLETED.value
        assert memory.processing_status == ProcessingStatus.COMPLETED.value

        # Can also transition to FAILED
        memory.processing_status = ProcessingStatus.FAILED.value
        assert memory.processing_status == ProcessingStatus.FAILED.value

    def test_memory_metadata(self):
        """Test memory with custom metadata"""
        metadata = {"source": "email", "importance": "high", "custom_field": "custom_value"}

        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Metadata Test",
            content="Content",
            author_id="user-123",
            metadata=metadata,
        )

        assert memory.metadata == metadata
        assert memory.metadata["source"] == "email"
        assert memory.metadata["importance"] == "high"

    def test_memory_version_tracking(self):
        """Test memory version tracking"""
        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Version Test",
            content="Original content",
            author_id="user-123",
            version=1,
        )

        assert memory.version == 1

        # Update version
        memory.version = 2
        assert memory.version == 2

    def test_memory_is_public_flag(self):
        """Test memory public visibility flag"""
        private_memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Private",
            content="Content",
            author_id="user-123",
            is_public=False,
        )

        public_memory = Memory(
            id="memory-id-2",
            project_id="project-123",
            title="Public",
            content="Content",
            author_id="user-123",
            is_public=True,
        )

        assert private_memory.is_public is False
        assert public_memory.is_public is True

    def test_memory_defaults(self):
        """Test memory default values"""
        memory = Memory(
            id="memory-id",
            project_id="project-123",
            title="Defaults Test",
            content="Content",
            author_id="user-123",
        )

        # Check defaults
        assert memory.content_type == "text"
        assert memory.tags == []
        assert memory.entities == []
        assert memory.relationships == []
        assert memory.version == 1
        assert memory.collaborators == []
        assert memory.is_public is False
        assert memory.status == "ENABLED"
        assert memory.processing_status == ProcessingStatus.PENDING.value
        assert memory.metadata == {}
        assert memory.created_at is not None
        assert memory.updated_at is None
