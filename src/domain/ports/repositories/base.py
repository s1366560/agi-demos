"""Base repository port interfaces for CQRS pattern.

Provides ReadRepository and WriteRepository base interfaces to enforce
separation of read and write operations at the interface level.

Usage:
    class UserReadRepository(ReadRepositoryPort[User]):
        async def find_by_email(self, email: str) -> Optional[User]: ...

    class UserWriteRepository(WriteRepositoryPort[User]):
        async def save(self, entity: User) -> None: ...

    class UserRepository(ReadRepositoryPort[User], WriteRepositoryPort[User]):
        # Full CRUD - existing pattern, still valid
        ...
"""

from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


class ReadRepositoryPort(ABC, Generic[T]):
    """Base interface for read-only repository operations.

    Implementations should use read replicas or optimized query paths
    where available for high-traffic read operations.
    """

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> Optional[T]:
        """Find entity by ID."""
        ...

    @abstractmethod
    async def exists(self, entity_id: str) -> bool:
        """Check if entity exists."""
        ...


class WriteRepositoryPort(ABC, Generic[T]):
    """Base interface for write repository operations.

    Implementations should target the primary database for all writes.
    """

    @abstractmethod
    async def save(self, entity: T) -> None:
        """Save (create or update) an entity."""
        ...

    @abstractmethod
    async def delete(self, entity_id: str) -> None:
        """Delete an entity by ID."""
        ...


class ListableReadRepositoryPort(ReadRepositoryPort[T], Generic[T]):
    """Extended read port for entities that support listing/pagination."""

    @abstractmethod
    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[T]:
        """List entities with pagination."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Count total entities."""
        ...
