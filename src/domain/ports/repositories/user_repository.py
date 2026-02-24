from abc import ABC, abstractmethod

from src.domain.model.auth.user import User


class UserRepository(ABC):
    """Repository interface for User entity"""

    @abstractmethod
    async def save(self, user: User) -> User:
        """Save a user (create or update). Returns the saved user."""
        pass

    @abstractmethod
    async def find_by_id(self, user_id: str) -> User | None:
        """Find a user by ID"""
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> User | None:
        """Find a user by email address"""
        pass

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[User]:
        """List all users with pagination"""
        pass

    @abstractmethod
    async def delete(self, user_id: str) -> bool:
        """Delete a user. Returns True if deleted, False if not found."""
        pass
