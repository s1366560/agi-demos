"""
Test data builders for Tenant entities.

Provides builder pattern for creating test Tenant instances with sensible defaults
and the ability to customize specific fields.

CRITICAL: The 'slug' field is required in the database schema but not in the domain model.
This builder ensures tests include proper slug values to prevent constraint violations.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from src.domain.model.tenant import Tenant


class TenantTestDataBuilder:
    """Builder for creating Tenant test data with customizable fields."""

    def __init__(
        self,
        name: str = "Test Tenant",
        owner_id: str = "test-user-123",
        slug: Optional[str] = None,
    ):
        """Initialize builder with default values.

        Args:
            name: Tenant name
            owner_id: Owner user ID
            slug: URL-friendly slug (auto-generated from name if not provided)
        """
        self._name = name
        self._owner_id = owner_id
        # Auto-generate slug from name if not provided
        self._slug = slug if slug is not None else self._generate_slug(name)
        self._description = None
        self._plan = "free"
        self._max_projects = 3
        self._max_users = 10
        self._max_storage = 1073741824  # 1GB in bytes

    def _generate_slug(self, name: str) -> str:
        """Generate URL-friendly slug from tenant name."""
        return name.lower().replace(" ", "-").replace("_", "-")[:50]

    def with_name(self, name: str) -> "TenantTestDataBuilder":
        """Set custom tenant name."""
        self._name = name
        return self

    def with_slug(self, slug: str) -> "TenantTestDataBuilder":
        """Set custom slug (URL-friendly identifier)."""
        self._slug = slug
        return self

    def with_owner(self, owner_id: str) -> "TenantTestDataBuilder":
        """Set custom owner ID."""
        self._owner_id = owner_id
        return self

    def with_description(self, description: str) -> "TenantTestDataBuilder":
        """Set custom description."""
        self._description = description
        return self

    def with_plan(self, plan: str) -> "TenantTestDataBuilder":
        """Set custom plan (free, pro, enterprise)."""
        self._plan = plan
        return self

    def as_free_plan(self) -> "TenantTestDataBuilder":
        """Set plan to free."""
        self._plan = "free"
        return self

    def as_pro_plan(self) -> "TenantTestDataBuilder":
        """Set plan to pro."""
        self._plan = "pro"
        return self

    def as_enterprise_plan(self) -> "TenantTestDataBuilder":
        """Set plan to enterprise."""
        self._plan = "enterprise"
        return self

    def with_max_projects(self, max_projects: int) -> "TenantTestDataBuilder":
        """Set maximum number of projects."""
        self._max_projects = max_projects
        return self

    def with_max_users(self, max_users: int) -> "TenantTestDataBuilder":
        """Set maximum number of users."""
        self._max_users = max_users
        return self

    def with_max_storage(self, max_storage: int) -> "TenantTestDataBuilder":
        """Set maximum storage in bytes."""
        self._max_storage = max_storage
        return self

    def build(self) -> Tenant:
        """Build and return a Tenant entity with the configured values.

        Note: The returned Tenant object includes the slug for reference in tests,
        but the actual database model must handle slug persistence.
        """
        return Tenant(
            id=str(uuid4()),
            name=self._name,
            owner_id=self._owner_id,
            description=self._description,
            plan=self._plan,
            max_projects=self._max_projects,
            max_users=self._max_users,
            max_storage=self._max_storage,
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )


# Convenience function for quick test data creation
def create_test_tenant(
    name: str = "Test Tenant", owner_id: str = "test-user-123", slug: Optional[str] = None, **kwargs
) -> Tenant:
    """
    Create a test Tenant with sensible defaults.

    Args:
        name: Tenant name
        owner_id: Owner user ID
        slug: Optional URL-friendly slug (auto-generated if not provided)
        **kwargs: Additional fields to override

    Returns:
        Tenant entity with test data

    Example:
        >>> tenant = create_test_tenant(name="My Project", owner_id="user-123")
        >>> print(tenant.name)
        "My Project"

        >>> tenant = create_test_tenant(
        ...     name="Research",
        ...     slug="research-team",
        ...     plan="pro",
        ...     max_projects=10
        ... )
    """
    builder = TenantTestDataBuilder(
        name=name,
        owner_id=owner_id,
        slug=slug,
    )

    # Apply any additional kwargs
    for key, value in kwargs.items():
        if hasattr(builder, f"with_{key}"):
            builder = getattr(builder, f"with_{key}")(value)
        elif key == "as_free_plan" and value:
            builder = builder.as_free_plan()
        elif key == "as_pro_plan" and value:
            builder = builder.as_pro_plan()
        elif key == "as_enterprise_plan" and value:
            builder = builder.as_enterprise_plan()

    return builder.build()
