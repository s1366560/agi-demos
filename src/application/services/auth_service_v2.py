"""
Authentication service using domain ports.

This service handles authentication business logic depending only on domain ports,
following the Dependency Inversion Principle.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt

from src.domain.model.auth.api_key import APIKey
from src.domain.model.auth.user import User
from src.domain.ports.repositories.api_key_repository import APIKeyRepository
from src.domain.ports.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class AuthService:
    """
    Authentication service that depends on domain ports (interfaces),
    not concrete infrastructure implementations.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        api_key_repository: APIKeyRepository,
    ) -> None:
        self._user_repo = user_repository
        self._api_key_repo = api_key_repository

    # === Utility Methods ===

    @staticmethod
    def generate_api_key() -> str:
        """Generate a new API key."""
        random_bytes = secrets.token_bytes(32)
        key = f"ms_sk_{random_bytes.hex()}"
        return key

    @staticmethod
    def hash_api_key(key: str) -> str:
        """Hash an API key for storage."""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def verify_api_key_hash(key: str, hashed_key: str) -> bool:
        """Verify an API key against its hash."""
        return AuthService.hash_api_key(key) == hashed_key

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash."""
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
        except Exception as e:
            logger.debug(f"verify_password failed with error: {e}")
            return False

    @staticmethod
    def get_password_hash(password: str) -> str:
        """Hash a password for storage."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # === API Key Operations ===

    async def verify_api_key(self, api_key: str) -> APIKey | None:
        """
        Verify an API key and return the API key object if valid.

        Args:
            api_key: The plain API key to verify

        Returns:
            APIKey object if valid, None otherwise

        Raises:
            ValueError: If key is invalid, inactive, or expired
        """
        if not api_key.startswith("ms_sk_"):
            raise ValueError("Invalid API key format. API keys should start with 'ms_sk_'")

        hashed_key = self.hash_api_key(api_key)
        stored_key = await self._api_key_repo.find_by_hash(hashed_key)

        if not stored_key:
            raise ValueError("Invalid API key")

        if not stored_key.is_active:
            raise ValueError("API key has been deactivated")

        if stored_key.expires_at and stored_key.expires_at < datetime.now(UTC):
            raise ValueError("API key has expired")

        # NOTE: last_used_at update is intentionally skipped here to avoid
        # row-level lock contention on the api_keys table during high concurrency.
        # If tracking is needed, implement async/background update via Redis or message queue.
        # See: https://github.com/your-repo/issues/XXX for background task implementation

        return stored_key

    async def create_api_key(
        self,
        user_id: str,
        name: str,
        permissions: list[str],
        expires_in_days: int | None = None,
    ) -> tuple[str, APIKey]:
        """
        Create a new API key for a user.

        Args:
            user_id: The user ID to create the key for
            name: Name/description for the key
            permissions: List of permissions granted to this key
            expires_in_days: Optional expiration in days

        Returns:
            Tuple of (plain_key, api_key_object)
        """
        plain_key = self.generate_api_key()
        hashed_key = self.hash_api_key(plain_key)

        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        api_key = APIKey(
            id=str(uuid4()),
            user_id=user_id,
            key_hash=hashed_key,
            name=name,
            permissions=permissions,
            expires_at=expires_at,
            is_active=True,
        )

        await self._api_key_repo.save(api_key)

        return plain_key, api_key

    async def delete_api_key(self, api_key_id: str) -> None:
        """Delete an API key."""
        await self._api_key_repo.delete(api_key_id)

    async def list_user_api_keys(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[APIKey]:
        """List all API keys for a user."""
        return await self._api_key_repo.find_by_user(user_id, limit, offset)

    # === User Operations ===

    async def get_user_by_api_key(self, api_key_str: str) -> User | None:
        """
        Get a user from their API key.

        Args:
            api_key_str: The plain API key

        Returns:
            User object if valid, None otherwise
        """
        try:
            api_key = await self.verify_api_key(api_key_str)
            assert api_key is not None
            user = await self._user_repo.find_by_id(api_key.user_id)

            if not user:
                return None

            if not user.is_active:
                raise ValueError("User account is inactive")

            return user

        except ValueError:
            return None

    async def create_user(self, email: str, name: str, password: str) -> User:
        """
        Create a new user.

        Args:
            email: User email
            name: User name
            password: Plain password

        Returns:
            Created User object
        """
        # Check if user exists
        existing_user = await self._user_repo.find_by_email(email)
        if existing_user:
            return existing_user

        hashed = self.get_password_hash(password)
        logger.debug(f"create_user hashed password for {email}")

        user = User(
            id=str(uuid4()),
            email=email,
            name=name,
            password_hash=hashed,
            is_active=True,
        )

        await self._user_repo.save(user)
        return user

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Get a user by ID."""
        return await self._user_repo.find_by_id(user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        """Get a user by email."""
        return await self._user_repo.find_by_email(email)
