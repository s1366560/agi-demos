"""
Unit tests for authentication module.
"""

from datetime import datetime, timezone

import pytest

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    create_api_key,
    create_user,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey, User


def test_generate_api_key():
    """Test API key generation."""
    key = generate_api_key()

    assert key.startswith("ms_sk_")
    assert len(key) > 20


def test_hash_api_key():
    """Test API key hashing."""
    key = "ms_sk_test123"
    hashed = hash_api_key(key)

    assert hashed != key
    assert len(hashed) == 64  # SHA256 hex digest length


def test_verify_api_key():
    """Test API key verification."""
    key = "ms_sk_test123"
    hashed = hash_api_key(key)

    assert verify_api_key(key, hashed) is True
    assert verify_api_key("wrong_key", hashed) is False


@pytest.mark.asyncio
async def test_create_user(test_db):
    """Test user creation."""
    user = await create_user(
        test_db,
        email="test@example.com",
        name="Test User",
        password="testpassword",
    )

    assert isinstance(user, User)
    assert user.email == "test@example.com"
    assert user.full_name == "Test User"  # Fixed: DBUser has full_name, not name
    assert user.is_active is True


@pytest.mark.asyncio
async def test_create_api_key(test_db):
    """Test API key creation."""
    user = await create_user(
        test_db,
        email="test@example.com",
        name="Test User",
        password="testpassword",
    )

    plain_key, api_key_obj = await create_api_key(
        test_db,
        user_id=user.id,
        name="Test Key",
        permissions=["read", "write"],
        expires_in_days=30,
    )

    assert plain_key.startswith("ms_sk_")
    assert isinstance(api_key_obj, APIKey)
    assert api_key_obj.name == "Test Key"
    assert api_key_obj.user_id == user.id
    assert api_key_obj.permissions == ["read", "write"]
    assert api_key_obj.is_active is True
    assert api_key_obj.expires_at is not None


@pytest.mark.asyncio
async def test_api_key_expiration(test_db):
    """Test API key expiration logic."""
    user = await create_user(
        test_db, email="test@example.com", name="Test", password="testpassword"
    )

    # Create expired key
    _, api_key_obj = await create_api_key(
        test_db,
        user_id=user.id,
        name="Expired Key",
        permissions=["read"],
        expires_in_days=-1,  # Expired yesterday
    )

    # Check if expired
    # Note: SQLite doesn't preserve timezone info, so expires_at is naive UTC
    assert api_key_obj.expires_at < datetime.now(timezone.utc)
