"""Repository interface for InstanceMember entity."""

from abc import ABC, abstractmethod

from src.domain.model.instance.instance import InstanceMember


class InstanceMemberRepository(ABC):
    """Repository interface for InstanceMember entity."""

    @abstractmethod
    async def save(self, domain_entity: InstanceMember) -> InstanceMember:
        """Save a member (create or update). Returns the saved member."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> InstanceMember | None:
        """Find a member by ID."""

    @abstractmethod
    async def find_by_instance(self, instance_id: str) -> list[InstanceMember]:
        """List all members of an instance."""

    @abstractmethod
    async def find_by_user_and_instance(
        self, user_id: str, instance_id: str
    ) -> InstanceMember | None:
        """Find a member by user ID and instance ID."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete a member. Returns True if deleted, False if not found."""
