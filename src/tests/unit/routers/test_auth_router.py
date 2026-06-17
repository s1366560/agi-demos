"""Unit tests for auth router endpoints."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.application.schemas.auth import APIKeyCreate, UserUpdate
from src.infrastructure.adapters.primary.web.routers.auth import (
    create_new_api_key,
    list_api_keys,
    read_users_me,
    update_user_me,
)


@pytest.mark.unit
class TestAuthRouter:
    async def test_read_users_me_returns_persisted_profile(self) -> None:
        created_at = datetime.now(UTC)
        current_user = Mock()
        current_user.id = "user-1"
        current_user.email = "user@example.com"
        current_user.full_name = "Profile User"
        current_user.is_active = True
        current_user.created_at = created_at
        current_user.profile = {"job_title": "Staff Engineer", "location": "Remote"}
        current_user.preferred_language = "en-US"

        user_with_roles = SimpleNamespace(
            roles=[SimpleNamespace(role=SimpleNamespace(name="user"))]
        )
        result = Mock()
        result.scalar_one_or_none.return_value = user_with_roles
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        response = await read_users_me(current_user=current_user, db=db)

        assert response.profile == {"job_title": "Staff Engineer", "location": "Remote"}
        assert response.roles == ["user"]
        assert response.preferred_language == "en-US"

    async def test_update_user_me_merges_and_persists_profile(self) -> None:
        created_at = datetime.now(UTC)
        current_user = Mock()
        current_user.id = "user-1"
        current_user.email = "user@example.com"
        current_user.full_name = "Original Name"
        current_user.is_active = True
        current_user.created_at = created_at
        current_user.profile = {"department": "Engineering", "location": "Remote"}
        current_user.preferred_language = "en-US"

        user_with_roles = SimpleNamespace(
            roles=[SimpleNamespace(role=SimpleNamespace(name="admin"))]
        )
        result = Mock()
        result.scalar_one_or_none.return_value = user_with_roles
        db = AsyncMock()
        db.add = Mock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        response = await update_user_me(
            UserUpdate(
                name="Updated Name",
                profile={"job_title": "Staff Engineer", "phone": "+1 555 0100"},
            ),
            current_user=current_user,
            db=db,
        )

        assert current_user.full_name == "Updated Name"
        assert current_user.profile == {
            "department": "Engineering",
            "location": "Remote",
            "job_title": "Staff Engineer",
            "phone": "+1 555 0100",
        }
        db.add.assert_called_once_with(current_user)
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(current_user)
        assert response.profile == current_user.profile
        assert response.roles == ["admin"]

    async def test_create_new_api_key_commits_transaction(self) -> None:
        current_user = Mock()
        current_user.id = "user-1"

        db = AsyncMock()
        db.commit = AsyncMock()

        created_at = datetime.now(UTC)
        api_key = Mock()
        api_key.id = "key-1"
        api_key.name = "Trace Verify"
        api_key.created_at = created_at
        api_key.expires_at = None
        api_key.permissions = ["read", "write"]

        key_data = APIKeyCreate(name="Trace Verify", permissions=["read", "write"])

        with patch(
            "src.infrastructure.adapters.primary.web.routers.auth.create_api_key",
            new=AsyncMock(return_value=("ms_sk_test_key", api_key)),
        ) as create_api_key_mock:
            response = await create_new_api_key(
                key_data,
                current_user=current_user,
                db=db,
            )

        create_api_key_mock.assert_awaited_once_with(
            db,
            user_id="user-1",
            name="Trace Verify",
            permissions=["read", "write"],
            expires_in_days=None,
        )
        db.commit.assert_awaited_once()
        assert response.key == "ms_sk_test_key"
        assert response.key_id == "key-1"

    async def test_list_api_keys_applies_limit_and_offset(self) -> None:
        current_user = Mock()
        current_user.id = "user-1"

        created_at = datetime.now(UTC)
        api_key = SimpleNamespace(
            id="key-1",
            key="masked",
            name="Paged Key",
            created_at=created_at,
            expires_at=None,
            permissions=["read"],
        )
        result = Mock()
        result.scalars.return_value.all.return_value = [api_key]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        response = await list_api_keys(limit=2, offset=3, current_user=current_user, db=db)

        statement = db.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "LIMIT 2" in compiled
        assert "OFFSET 3" in compiled
        assert response[0].key_id == "key-1"
        assert response[0].key == "*****************"
