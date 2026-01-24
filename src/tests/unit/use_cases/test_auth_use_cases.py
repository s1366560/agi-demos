"""
Unit tests for Auth use cases.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.use_cases.auth import CreateAPIKeyCommand, CreateAPIKeyUseCase
from src.application.use_cases.auth.create_api_key import DeleteAPIKeyCommand, DeleteAPIKeyUseCase
from src.application.use_cases.auth.delete_api_key import ListAPIKeysQuery, ListAPIKeysUseCase
from src.domain.model.auth.api_key import APIKey


@pytest.mark.unit
class TestCreateAPIKeyUseCase:
    """Test cases for CreateAPIKeyUseCase"""

    @pytest.mark.asyncio
    async def test_create_api_key_success(self):
        """Test creating an API key successfully"""
        # Arrange
        mock_repo = Mock()
        mock_repo.save = AsyncMock()

        generate_key_func = Mock(return_value="ms_sk_test_key_123")
        hash_key_func = Mock(return_value="hashed_key_123")

        use_case = CreateAPIKeyUseCase(mock_repo, generate_key_func, hash_key_func)
        command = CreateAPIKeyCommand(
            user_id="user_123", name="Test Key", permissions=["read", "write"]
        )

        # Act
        plain_key, api_key = await use_case.execute(command)

        # Assert
        assert plain_key == "ms_sk_test_key_123"
        assert api_key.user_id == "user_123"
        assert api_key.name == "Test Key"
        assert api_key.permissions == ["read", "write"]
        assert api_key.key_hash == "hashed_key_123"
        assert api_key.expires_at is None
        assert api_key.id is not None
        assert isinstance(api_key.created_at, datetime)
        generate_key_func.assert_called_once()
        hash_key_func.assert_called_once_with("ms_sk_test_key_123")
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_api_key_with_expiration(self):
        """Test creating an API key with expiration date"""
        # Arrange
        mock_repo = Mock()
        mock_repo.save = AsyncMock()

        generate_key_func = Mock(return_value="ms_sk_test_key_123")
        hash_key_func = Mock(return_value="hashed_key_123")

        use_case = CreateAPIKeyUseCase(mock_repo, generate_key_func, hash_key_func)
        command = CreateAPIKeyCommand(
            user_id="user_123", name="Temporary Key", permissions=["read"], expires_in_days=30
        )

        # Act
        plain_key, api_key = await use_case.execute(command)

        # Assert
        assert plain_key == "ms_sk_test_key_123"
        assert api_key.expires_at is not None
        # Check expiration is approximately 30 days from now
        expected_expiration = datetime.now(timezone.utc) + timedelta(days=30)
        assert (
            abs((api_key.expires_at - expected_expiration).total_seconds()) < 5
        )  # 5 seconds tolerance
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_api_key_custom_functions(self):
        """Test creating an API key with custom key generation and hashing"""
        # Arrange
        mock_repo = Mock()
        mock_repo.save = AsyncMock()

        def custom_generate():
            return "custom_key_abc"

        def custom_hash(key):
            return f"hashed_{key}"

        use_case = CreateAPIKeyUseCase(mock_repo, custom_generate, custom_hash)
        command = CreateAPIKeyCommand(user_id="user_123", name="Custom Key", permissions=["admin"])

        # Act
        plain_key, api_key = await use_case.execute(command)

        # Assert
        assert plain_key == "custom_key_abc"
        assert api_key.key_hash == "hashed_custom_key_abc"
        mock_repo.save.assert_called_once()


@pytest.mark.unit
class TestListAPIKeysUseCase:
    """Test cases for ListAPIKeysUseCase"""

    @pytest.mark.asyncio
    async def test_list_api_keys_default_pagination(self):
        """Test listing API keys with default pagination"""
        # Arrange
        api_keys = [
            APIKey(
                id="key_1",
                user_id="user_123",
                key_hash="hash_1",
                name="Key 1",
                permissions=["read"],
            ),
            APIKey(
                id="key_2",
                user_id="user_123",
                key_hash="hash_2",
                name="Key 2",
                permissions=["write"],
            ),
        ]

        mock_repo = Mock()
        mock_repo.find_by_user = AsyncMock(return_value=api_keys)

        use_case = ListAPIKeysUseCase(mock_repo)
        query = ListAPIKeysQuery(user_id="user_123")

        # Act
        result = await use_case.execute(query)

        # Assert
        assert len(result) == 2
        assert result[0].id == "key_1"
        assert result[1].id == "key_2"
        mock_repo.find_by_user.assert_called_once_with("user_123", limit=50, offset=0)

    @pytest.mark.asyncio
    async def test_list_api_keys_with_pagination(self):
        """Test listing API keys with custom pagination"""
        # Arrange
        api_keys = [
            APIKey(
                id="key_1",
                user_id="user_123",
                key_hash="hash_1",
                name="Key 1",
                permissions=["read"],
            ),
        ]

        mock_repo = Mock()
        mock_repo.find_by_user = AsyncMock(return_value=api_keys)

        use_case = ListAPIKeysUseCase(mock_repo)
        query = ListAPIKeysQuery(user_id="user_123", limit=10, offset=20)

        # Act
        result = await use_case.execute(query)

        # Assert
        assert len(result) == 1
        mock_repo.find_by_user.assert_called_once_with("user_123", limit=10, offset=20)

    @pytest.mark.asyncio
    async def test_list_api_keys_empty_result(self):
        """Test listing API keys when user has no keys"""
        # Arrange
        mock_repo = Mock()
        mock_repo.find_by_user = AsyncMock(return_value=[])

        use_case = ListAPIKeysUseCase(mock_repo)
        query = ListAPIKeysQuery(user_id="user_123")

        # Act
        result = await use_case.execute(query)

        # Assert
        assert result == []
        mock_repo.find_by_user.assert_called_once()


@pytest.mark.unit
class TestDeleteAPIKeyUseCase:
    """Test cases for DeleteAPIKeyUseCase"""

    @pytest.mark.asyncio
    async def test_delete_api_key_success(self):
        """Test deleting an API key successfully"""
        # Arrange
        api_key = APIKey(
            id="key_123",
            user_id="user_123",
            key_hash="hash_123",
            name="Test Key",
            permissions=["read"],
        )

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=api_key)
        mock_repo.delete = AsyncMock()

        use_case = DeleteAPIKeyUseCase(mock_repo)
        command = DeleteAPIKeyCommand(key_id="key_123", user_id="user_123")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result is True
        mock_repo.find_by_id.assert_called_once_with("key_123")
        mock_repo.delete.assert_called_once_with("key_123")

    @pytest.mark.asyncio
    async def test_delete_api_key_not_found(self):
        """Test deleting a non-existent API key"""
        # Arrange
        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=None)

        use_case = DeleteAPIKeyUseCase(mock_repo)
        command = DeleteAPIKeyCommand(key_id="nonexistent", user_id="user_123")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result is False
        mock_repo.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_api_key_unauthorized(self):
        """Test deleting an API key owned by another user"""
        # Arrange
        api_key = APIKey(
            id="key_123",
            user_id="user_456",  # Different user
            key_hash="hash_123",
            name="Other User Key",
            permissions=["read"],
        )

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=api_key)

        use_case = DeleteAPIKeyUseCase(mock_repo)
        command = DeleteAPIKeyCommand(
            key_id="key_123",
            user_id="user_123",  # Different user
        )

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result is False
        mock_repo.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_api_key_multiple_keys_same_user(self):
        """Test deleting one of multiple API keys owned by the same user"""
        # Arrange
        api_key1 = APIKey(
            id="key_1", user_id="user_123", key_hash="hash_1", name="Key 1", permissions=["read"]
        )
        APIKey(
            id="key_2", user_id="user_123", key_hash="hash_2", name="Key 2", permissions=["write"]
        )

        mock_repo = Mock()
        # First call returns api_key1, second would return api_key2 (not tested here)
        mock_repo.find_by_id = AsyncMock(return_value=api_key1)
        mock_repo.delete = AsyncMock()

        use_case = DeleteAPIKeyUseCase(mock_repo)
        command = DeleteAPIKeyCommand(key_id="key_1", user_id="user_123")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result is True
        mock_repo.find_by_id.assert_called_once_with("key_1")
        mock_repo.delete.assert_called_once_with("key_1")
