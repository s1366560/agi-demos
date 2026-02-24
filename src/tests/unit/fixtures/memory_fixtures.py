"""
Test data builders for Memory entities.

Provides builder pattern for creating test Memory instances with sensible defaults
and the ability to customize specific fields.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from src.domain.model.memory import Memory


class MemoryTestDataBuilder:
    """Builder for creating Memory test data with customizable fields."""

    def __init__(
        self,
        project_id: str = "test-project-123",
        title: str = "Test Memory",
        content: str = "Test memory content",
        author_id: str = "test-user-123",
    ):
        """Initialize builder with default values."""
        self._project_id = project_id
        self._title = title
        self._content = content
        self._author_id = author_id
        self._content_type = "text"
        self._tags = []
        self._entities = []
        self._relationships = []
        self._version = 1
        self._collaborators = []
        self._is_public = False
        self._status = "ENABLED"
        self._processing_status = "PENDING"
        self._metadata = {}

    def with_project(self, project_id: str) -> "MemoryTestDataBuilder":
        """Set custom project ID."""
        self._project_id = project_id
        return self

    def with_title(self, title: str) -> "MemoryTestDataBuilder":
        """Set custom title."""
        self._title = title
        return self

    def with_content(self, content: str) -> "MemoryTestDataBuilder":
        """Set custom content."""
        self._content = content
        return self

    def with_author(self, author_id: str) -> "MemoryTestDataBuilder":
        """Set custom author ID."""
        self._author_id = author_id
        return self

    def with_content_type(self, content_type: str) -> "MemoryTestDataBuilder":
        """Set custom content type."""
        self._content_type = content_type
        return self

    def with_tags(self, tags: List[str]) -> "MemoryTestDataBuilder":
        """Set custom tags."""
        self._tags = tags
        return self

    def add_tag(self, tag: str) -> "MemoryTestDataBuilder":
        """Add a single tag."""
        self._tags.append(tag)
        return self

    def with_entities(self, entities: List[Dict[str, Any]]) -> "MemoryTestDataBuilder":
        """Set custom entities."""
        self._entities = entities
        return self

    def add_entity(self, entity: Dict[str, Any]) -> "MemoryTestDataBuilder":
        """Add a single entity."""
        self._entities.append(entity)
        return self

    def with_relationships(self, relationships: List[Dict[str, Any]]) -> "MemoryTestDataBuilder":
        """Set custom relationships."""
        self._relationships = relationships
        return self

    def with_version(self, version: int) -> "MemoryTestDataBuilder":
        """Set custom version."""
        self._version = version
        return self

    def with_collaborators(self, collaborators: List[str]) -> "MemoryTestDataBuilder":
        """Set custom collaborators."""
        self._collaborators = collaborators
        return self

    def add_collaborator(self, user_id: str) -> "MemoryTestDataBuilder":
        """Add a single collaborator."""
        self._collaborators.append(user_id)
        return self

    def as_public(self) -> "MemoryTestDataBuilder":
        """Mark memory as public."""
        self._is_public = True
        return self

    def with_status(self, status: str) -> "MemoryTestDataBuilder":
        """Set custom status."""
        self._status = status
        return self

    def with_processing_status(self, processing_status: str) -> "MemoryTestDataBuilder":
        """Set custom processing status."""
        self._processing_status = processing_status
        return self

    def with_metadata(self, metadata: Dict[str, Any]) -> "MemoryTestDataBuilder":
        """Set custom metadata."""
        self._metadata = metadata
        return self

    def add_metadata(self, key: str, value: Any) -> "MemoryTestDataBuilder":  # noqa: ANN401
        """Add a single metadata key-value pair."""
        self._metadata[key] = value
        return self

    def build(self) -> Memory:
        """Build and return a Memory entity with the configured values."""
        return Memory(
            id=str(uuid4()),
            project_id=self._project_id,
            title=self._title,
            content=self._content,
            author_id=self._author_id,
            content_type=self._content_type,
            tags=self._tags.copy(),
            entities=self._entities.copy(),
            relationships=self._relationships.copy(),
            version=self._version,
            collaborators=self._collaborators.copy(),
            is_public=self._is_public,
            status=self._status,
            processing_status=self._processing_status,
            metadata=self._metadata.copy(),
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )


# Convenience function for quick test data creation
def create_test_memory(
    content: str = "Test memory content",
    author_id: str = "test-user-123",
    project_id: str = "test-project-123",
    **kwargs,
) -> Memory:
    """
    Create a test Memory with sensible defaults.

    Args:
        content: Memory content
        author_id: Author user ID
        project_id: Project ID
        **kwargs: Additional fields to override

    Returns:
        Memory entity with test data
    """
    builder = MemoryTestDataBuilder(
        project_id=project_id,
        content=content,
        author_id=author_id,
    )

    # Apply any additional kwargs
    for key, value in kwargs.items():
        if hasattr(builder, f"with_{key}"):
            builder = getattr(builder, f"with_{key}")(value)
        elif key == "as_public" and value:
            builder = builder.as_public()
        elif key == "add_tag":
            builder = builder.add_tag(value)
        elif key == "add_entity":
            builder = builder.add_entity(value)
        elif key == "add_collaborator":
            builder = builder.add_collaborator(value)
        elif key == "add_metadata":
            key, val = value  # Expect tuple (key, value)
            builder = builder.add_metadata(key, val)

    return builder.build()
