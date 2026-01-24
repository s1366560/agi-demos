"""
Unit tests for S3StorageAdapter.

Tests the S3/MinIO storage adapter for file upload and presigned URL generation.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import S3StorageAdapter


@pytest.mark.unit
class TestS3StorageAdapter:
    """Test cases for S3StorageAdapter."""

    @pytest.fixture
    def mock_s3_client(self):
        """Create a mock S3 client."""
        client = AsyncMock()
        client.put_object = AsyncMock(return_value={"ETag": '"abc123"', "VersionId": "v1"})
        client.delete_object = AsyncMock(return_value={})
        client.head_object = AsyncMock(return_value={"ContentLength": 1024})
        client.get_object = AsyncMock(
            return_value={
                "Body": AsyncMock(read=AsyncMock(return_value=b"test content")),
                "ContentType": "application/pdf",
                "Metadata": {"tenant_id": "tenant-123"},
            }
        )
        client.list_objects_v2 = AsyncMock(
            return_value={
                "Contents": [
                    {"Key": "file1.pdf", "Size": 1024, "LastModified": datetime.now()},
                    {"Key": "file2.pdf", "Size": 2048, "LastModified": datetime.now()},
                ]
            }
        )
        client.generate_presigned_url = AsyncMock(
            return_value="https://s3.example.com/bucket/file.pdf?signature=xyz"
        )
        return client

    @pytest.fixture
    def storage_adapter(self):
        """Create a S3StorageAdapter with test configuration."""
        return S3StorageAdapter(
            bucket_name="test-bucket",
            region="us-east-1",
            access_key_id="test-access-key",
            secret_access_key="test-secret-key",
            endpoint_url="http://localhost:9000",
        )

    async def test_upload_file(self, storage_adapter, mock_s3_client):
        """Test uploading a file to S3."""
        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            result = await storage_adapter.upload_file(
                file_content=b"%PDF-1.4 test content",
                object_key="tenant-123/files/report.pdf",
                content_type="application/pdf",
                metadata={"tenant_id": "tenant-123", "original_filename": "report.pdf"},
            )

            assert result.object_key == "tenant-123/files/report.pdf"
            assert result.etag == "abc123"
            mock_s3_client.put_object.assert_called_once()

    async def test_generate_presigned_url(self, storage_adapter, mock_s3_client):
        """Test generating a presigned URL for download."""
        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            url = await storage_adapter.generate_presigned_url(
                object_key="tenant-123/files/report.pdf",
                expiration_seconds=3600,
            )

            assert "s3.example.com" in url
            assert "signature" in url
            mock_s3_client.generate_presigned_url.assert_called_once()

    async def test_delete_file(self, storage_adapter, mock_s3_client):
        """Test deleting a file from S3."""
        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            result = await storage_adapter.delete_file(object_key="tenant-123/files/old-report.pdf")

            assert result is True
            mock_s3_client.delete_object.assert_called_once()

    async def test_file_exists(self, storage_adapter, mock_s3_client):
        """Test checking if a file exists in S3."""
        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            exists = await storage_adapter.file_exists(object_key="tenant-123/files/report.pdf")

            assert exists is True
            mock_s3_client.head_object.assert_called_once()

    async def test_file_not_exists(self, storage_adapter, mock_s3_client):
        """Test checking if a non-existent file exists."""
        from botocore.exceptions import ClientError

        mock_s3_client.head_object = AsyncMock(
            side_effect=ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
            )
        )

        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            exists = await storage_adapter.file_exists(
                object_key="tenant-123/files/nonexistent.pdf"
            )

            assert exists is False

    async def test_list_files(self, storage_adapter, mock_s3_client):
        """Test listing files in S3."""
        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            files = await storage_adapter.list_files(prefix="tenant-123/files/")

            assert len(files) == 2
            assert files[0] == "file1.pdf"
            mock_s3_client.list_objects_v2.assert_called_once()

    async def test_upload_with_tenant_isolation(self, storage_adapter, mock_s3_client):
        """Test that uploads include tenant metadata for isolation."""
        with patch.object(
            storage_adapter, "_get_client", return_value=AsyncMock()
        ) as mock_get_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_s3_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_context

            await storage_adapter.upload_file(
                file_content=b"test",
                object_key="tenant-abc/outputs/report.pdf",
                content_type="application/pdf",
                metadata={"tenant_id": "tenant-abc"},
            )

            # Verify metadata was passed
            call_kwargs = mock_s3_client.put_object.call_args[1]
            assert call_kwargs["Metadata"]["tenant_id"] == "tenant-abc"
