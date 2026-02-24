"""
Test data builders for User entities.

Provides builder pattern for creating test User instances with sensible defaults
and the ability to customize specific fields.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.domain.model.auth import User


class UserTestDataBuilder:
    """Builder for creating User test data with customizable fields."""

    def __init__(
        self,
        email: str = "test@example.com",
        name: str = "Test User",
        password_hash: str = "hashed_password_123",
    ) -> None:
        """Initialize builder with default values."""
        self._email = email
        self._name = name
        self._password_hash = password_hash
        self._is_active = True
        self._profile = {}

    def with_email(self, email: str) -> "UserTestDataBuilder":
        """Set custom email."""
        self._email = email
        return self

    def with_name(self, name: str) -> "UserTestDataBuilder":
        """Set custom name."""
        self._name = name
        return self

    def with_password_hash(self, password_hash: str) -> "UserTestDataBuilder":
        """Set custom password hash."""
        self._password_hash = password_hash
        return self

    def as_active(self) -> "UserTestDataBuilder":
        """Mark user as active (default)."""
        self._is_active = True
        return self

    def as_inactive(self) -> "UserTestDataBuilder":
        """Mark user as inactive."""
        self._is_active = False
        return self

    def with_profile(self, profile: dict[str, Any]) -> "UserTestDataBuilder":
        """Set custom profile data."""
        self._profile = profile
        return self

    def add_profile_field(self, key: str, value: Any) -> "UserTestDataBuilder":
        """Add a single profile field."""
        self._profile[key] = value
        return self

    def build(self) -> User:
        """Build and return a User entity with the configured values."""
        return User(
            id=str(uuid4()),
            email=self._email,
            name=self._name,
            password_hash=self._password_hash,
            is_active=self._is_active,
            profile=self._profile.copy(),
            created_at=datetime.now(UTC),
        )


# Convenience function for quick test data creation
def create_test_user(
    email: str = "test@example.com",
    name: str = "Test User",
    password_hash: str = "hashed_password_123",
    **kwargs,
) -> User:
    """
    Create a test User with sensible defaults.

    Args:
        email: User email
        name: User display name
        password_hash: Hashed password
        **kwargs: Additional fields to override

    Returns:
        User entity with test data
    """
    builder = UserTestDataBuilder(
        email=email,
        name=name,
        password_hash=password_hash,
    )

    # Apply any additional kwargs
    for key, value in kwargs.items():
        if hasattr(builder, f"with_{key}"):
            builder = getattr(builder, f"with_{key}")(value)
        elif key == "as_inactive" and value:
            builder = builder.as_inactive()
        elif key == "as_active":
            builder = builder.as_active()
        elif key == "add_profile_field":
            key, val = value  # Expect tuple (key, value)
            builder = builder.add_profile_field(key, val)

    return builder.build()
