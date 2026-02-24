"""Storage Service Port - Abstract interface for file storage operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class UploadResult:
    """Result of a file upload operation."""

    object_key: str
    size_bytes: int
    content_type: str
    etag: str | None = None


@dataclass
class MultipartUploadResult:
    """Result of initiating a multipart upload."""

    upload_id: str
    object_key: str


@dataclass
class PartUploadResult:
    """Result of uploading a single part in multipart upload."""

    part_number: int
    etag: str


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
        metadata: dict[str, Any] | None = None,
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

    @abstractmethod
    async def generate_presigned_url(
        self,
        object_key: str,
        expiration_seconds: int = 3600,
        content_disposition: str | None = None,
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

    @abstractmethod
    async def delete_file(self, object_key: str) -> bool:
        """
        Delete a file from storage.

        Args:
            object_key: The storage path/key of the file to delete

        Returns:
            True if deleted successfully, False if file didn't exist
        """

    @abstractmethod
    async def file_exists(self, object_key: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            object_key: The storage path/key to check

        Returns:
            True if file exists, False otherwise
        """

    @abstractmethod
    async def get_file(self, object_key: str) -> bytes | None:
        """
        Retrieve a file's content from storage.

        Args:
            object_key: The storage path/key of the file

        Returns:
            File content as bytes, or None if not found
        """

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

    # ==================== Multipart Upload Methods ====================

    @abstractmethod
    async def create_multipart_upload(
        self,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MultipartUploadResult:
        """
        Initialize a multipart upload.

        Args:
            object_key: The storage path/key for the file
            content_type: MIME type of the file
            metadata: Optional metadata to attach to the file

        Returns:
            MultipartUploadResult with upload_id and object_key
        """

    @abstractmethod
    async def upload_part(
        self,
        object_key: str,
        upload_id: str,
        part_number: int,
        data: bytes,
    ) -> PartUploadResult:
        """
        Upload a single part in a multipart upload.

        Args:
            object_key: The storage path/key for the file
            upload_id: The multipart upload ID
            part_number: The part number (1-indexed)
            data: The part content as bytes

        Returns:
            PartUploadResult with part_number and etag
        """

    @abstractmethod
    async def complete_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
        parts: list[PartUploadResult],
    ) -> UploadResult:
        """
        Complete a multipart upload.

        Args:
            object_key: The storage path/key for the file
            upload_id: The multipart upload ID
            parts: List of PartUploadResult from uploaded parts

        Returns:
            UploadResult with the final file information
        """

    @abstractmethod
    async def abort_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
    ) -> bool:
        """
        Abort a multipart upload and clean up uploaded parts.

        Args:
            object_key: The storage path/key for the file
            upload_id: The multipart upload ID

        Returns:
            True if aborted successfully
        """

    @abstractmethod
    async def generate_presigned_upload_url(
        self,
        object_key: str,
        content_type: str,
        expiration_seconds: int = 3600,
    ) -> str:
        """
        Generate a presigned URL for uploading a file directly.

        Args:
            object_key: The storage path/key for the file
            content_type: MIME type of the file
            expiration_seconds: URL validity period in seconds

        Returns:
            A presigned URL string for PUT operation
        """
