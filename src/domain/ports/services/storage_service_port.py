"""Storage Service Port - Abstract interface for file storage operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class UploadResult:
    """Result of a file upload operation."""

    object_key: str
    size_bytes: int
    content_type: str
    etag: Optional[str] = None


class StorageServicePort(ABC):
    """
    Abstract interface for file storage operations.

    Implementations may include S3, MinIO, local filesystem, etc.
    """

    @abstractmethod
    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: Optional[dict] = None,
    ) -> UploadResult:
        """
        Upload a file to storage.

        Args:
            file_content: The file content as bytes
            object_key: The storage path/key for the file
            content_type: MIME type of the file
            metadata: Optional metadata to attach to the file

        Returns:
            UploadResult with the object key and metadata
        """
        pass

    @abstractmethod
    async def generate_presigned_url(
        self,
        object_key: str,
        expiration_seconds: int = 3600,
        content_disposition: Optional[str] = None,
    ) -> str:
        """
        Generate a presigned URL for downloading a file.

        Args:
            object_key: The storage path/key of the file
            expiration_seconds: URL validity period in seconds
            content_disposition: Optional Content-Disposition header value

        Returns:
            A presigned URL string
        """
        pass

    @abstractmethod
    async def delete_file(self, object_key: str) -> bool:
        """
        Delete a file from storage.

        Args:
            object_key: The storage path/key of the file to delete

        Returns:
            True if deleted successfully, False if file didn't exist
        """
        pass

    @abstractmethod
    async def file_exists(self, object_key: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            object_key: The storage path/key to check

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    async def get_file(self, object_key: str) -> Optional[bytes]:
        """
        Retrieve a file's content from storage.

        Args:
            object_key: The storage path/key of the file

        Returns:
            File content as bytes, or None if not found
        """
        pass

    @abstractmethod
    async def list_files(
        self,
        prefix: str,
        max_keys: int = 1000,
    ) -> list[str]:
        """
        List files with a given prefix.

        Args:
            prefix: The prefix to filter files by
            max_keys: Maximum number of files to return

        Returns:
            List of object keys matching the prefix
        """
        pass
