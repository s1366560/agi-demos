"""Unit tests for auth router endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.application.schemas.auth import APIKeyCreate
from src.infrastructure.adapters.primary.web.routers.auth import create_new_api_key


@pytest.mark.unit
class TestAuthRouter:
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
