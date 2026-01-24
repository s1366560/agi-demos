from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import APIKey

app = create_app()


@pytest.fixture
def mock_api_key_dependency(test_user):
    return APIKey(
        id=str(uuid4()),
        key_hash="hash",
        name="test-key",
        user_id=test_user.id,
        permissions=["read", "write"],
    )


@pytest.mark.asyncio
async def test_create_tenant_invalid_data(mock_api_key_dependency, test_db, test_user):
    # Mock user retrieval
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = test_user
    # mock_db_session.execute.return_value = mock_result # Use real DB instead

    app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    app.dependency_overrides[get_db] = lambda: test_db

    # Create test user in DB if not exists
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.models import User

    result = await test_db.execute(select(User).where(User.id == test_user.id))
    if not result.scalar_one_or_none():
        test_db.add(test_user)
        await test_db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/tenants/", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    app.dependency_overrides = {}
