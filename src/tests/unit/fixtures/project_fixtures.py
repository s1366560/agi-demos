"""
Test data builders for Project entities.

Provides builder pattern for creating test Project instances with sensible defaults
and the ability to customize specific fields.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from src.domain.model.project import Project


class ProjectTestDataBuilder:
    """Builder for creating Project test data with customizable fields."""

    def __init__(
        self,
        tenant_id: str = "test-tenant-123",
        name: str = "Test Project",
        owner_id: str = "test-user-123",
    ):
        """Initialize builder with default values."""
        self._tenant_id = tenant_id
        self._name = name
        self._owner_id = owner_id
        self._description = None
        self._member_ids = []
        self._memory_rules = {}
        self._graph_config = {}
        self._is_public = False

    def with_tenant(self, tenant_id: str) -> "ProjectTestDataBuilder":
        """Set custom tenant ID."""
        self._tenant_id = tenant_id
        return self

    def with_name(self, name: str) -> "ProjectTestDataBuilder":
        """Set custom project name."""
        self._name = name
        return self

    def with_owner(self, owner_id: str) -> "ProjectTestDataBuilder":
        """Set custom owner ID."""
        self._owner_id = owner_id
        return self

    def with_description(self, description: str) -> "ProjectTestDataBuilder":
        """Set custom description."""
        self._description = description
        return self

    def with_members(self, member_ids: List[str]) -> "ProjectTestDataBuilder":
        """Set custom member IDs."""
        self._member_ids = member_ids
        return self

    def add_member(self, user_id: str) -> "ProjectTestDataBuilder":
        """Add a single member."""
        self._member_ids.append(user_id)
        return self

    def with_memory_rules(self, rules: Dict[str, Any]) -> "ProjectTestDataBuilder":
        """Set custom memory rules."""
        self._memory_rules = rules
        return self

    def add_memory_rule(self, key: str, value: Any) -> "ProjectTestDataBuilder":
        """Add a single memory rule."""
        self._memory_rules[key] = value
        return self

    def with_graph_config(self, config: Dict[str, Any]) -> "ProjectTestDataBuilder":
        """Set custom graph configuration."""
        self._graph_config = config
        return self

    def add_graph_config(self, key: str, value: Any) -> "ProjectTestDataBuilder":
        """Add a single graph config setting."""
        self._graph_config[key] = value
        return self

    def as_public(self) -> "ProjectTestDataBuilder":
        """Mark project as public."""
        self._is_public = True
        return self

    def build(self) -> Project:
        """Build and return a Project entity with the configured values."""
        return Project(
            id=str(uuid4()),
            tenant_id=self._tenant_id,
            name=self._name,
            owner_id=self._owner_id,
            description=self._description,
            member_ids=self._member_ids.copy(),
            memory_rules=self._memory_rules.copy(),
            graph_config=self._graph_config.copy(),
            is_public=self._is_public,
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )


# Convenience function for quick test data creation
def create_test_project(
    name: str = "Test Project",
    tenant_id: str = "test-tenant-123",
    owner_id: str = "test-user-123",
    **kwargs,
) -> Project:
    """
    Create a test Project with sensible defaults.

    Args:
        name: Project name
        tenant_id: Tenant ID
        owner_id: Owner user ID
        **kwargs: Additional fields to override

    Returns:
        Project entity with test data
    """
    builder = ProjectTestDataBuilder(
        tenant_id=tenant_id,
        name=name,
        owner_id=owner_id,
    )

    # Apply any additional kwargs
    for key, value in kwargs.items():
        if hasattr(builder, f"with_{key}"):
            builder = getattr(builder, f"with_{key}")(value)
        elif key == "as_public" and value:
            builder = builder.as_public()
        elif key == "add_member":
            builder = builder.add_member(value)
        elif key == "add_memory_rule":
            key, val = value  # Expect tuple (key, value)
            builder = builder.add_memory_rule(key, val)
        elif key == "add_graph_config":
            key, val = value  # Expect tuple (key, value)
            builder = builder.add_graph_config(key, val)

    return builder.build()
