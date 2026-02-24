"""Attachment Repository Port - Interface for attachment persistence."""

from abc import ABC, abstractmethod

from src.domain.model.agent.attachment import Attachment, AttachmentStatus


class AttachmentRepositoryPort(ABC):
    """
    Repository interface for Attachment entities.

    Defines operations for persisting and retrieving file attachments
    associated with conversations.
    """

    @abstractmethod
    async def save(self, attachment: Attachment) -> None:
        """
        Save an attachment to the repository.

        Creates a new record if the attachment doesn't exist,
        or updates an existing record.

        Args:
            attachment: The attachment entity to save
        """
        pass

    @abstractmethod
    async def get(self, attachment_id: str) -> Attachment | None:
        """
        Get an attachment by ID.

        Args:
            attachment_id: The unique identifier of the attachment

        Returns:
            The attachment if found, None otherwise
        """
        pass

    @abstractmethod
    async def get_by_conversation(
        self,
        conversation_id: str,
        status: AttachmentStatus | None = None,
    ) -> list[Attachment]:
        """
        Get all attachments for a conversation.

        Args:
            conversation_id: The conversation ID to filter by
            status: Optional status filter

        Returns:
            List of attachments for the conversation
        """
        pass

    @abstractmethod
    async def get_by_ids(self, attachment_ids: list[str]) -> list[Attachment]:
        """
        Get multiple attachments by their IDs.

        Args:
            attachment_ids: List of attachment IDs

        Returns:
            List of found attachments (may be fewer than requested if some not found)
        """
        pass

    @abstractmethod
    async def delete(self, attachment_id: str) -> bool:
        """
        Delete an attachment.

        Args:
            attachment_id: The attachment ID to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def delete_expired(self) -> int:
        """
        Delete all expired attachments.

        Returns:
            Number of attachments deleted
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        attachment_id: str,
        status: AttachmentStatus,
        error_message: str | None = None,
    ) -> bool:
        """
        Update the status of an attachment.

        Args:
            attachment_id: The attachment ID to update
            status: The new status
            error_message: Optional error message (for FAILED status)

        Returns:
            True if updated, False if not found
        """
        pass

    @abstractmethod
    async def update_upload_progress(
        self,
        attachment_id: str,
        uploaded_parts: int,
    ) -> bool:
        """
        Update the multipart upload progress.

        Args:
            attachment_id: The attachment ID to update
            uploaded_parts: Number of parts uploaded so far

        Returns:
            True if updated, False if not found
        """
        pass

    @abstractmethod
    async def update_sandbox_path(
        self,
        attachment_id: str,
        sandbox_path: str,
    ) -> bool:
        """
        Update the sandbox path after import.

        Args:
            attachment_id: The attachment ID to update
            sandbox_path: The path in sandbox where file was imported

        Returns:
            True if updated, False if not found
        """
        pass
