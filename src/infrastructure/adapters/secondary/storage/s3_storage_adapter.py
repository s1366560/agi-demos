"""S3 Storage Adapter - Implementation of StorageServicePort for S3/MinIO."""

import logging
from typing import List, Optional

import aioboto3
from botocore.exceptions import ClientError

from src.domain.ports.services.storage_service_port import (
    MultipartUploadResult,
    PartUploadResult,
    StorageServicePort,
    UploadResult,
)

logger = logging.getLogger(__name__)


class S3StorageAdapter(StorageServicePort):
    """
    S3/MinIO storage adapter implementation.

    Supports both AWS S3 and MinIO (via endpoint_url configuration).
    """

    def __init__(
        self,
        bucket_name: str,
        region: str,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        """
        Initialize S3 storage adapter.

        Args:
            bucket_name: S3 bucket name
            region: AWS region
            access_key_id: AWS access key ID (optional, can use IAM role)
            secret_access_key: AWS secret access key (optional, can use IAM role)
            endpoint_url: Custom endpoint URL for MinIO or S3-compatible services
        """
        self._bucket = bucket_name
        self._region = region
        self._endpoint_url = endpoint_url

        # Create session with credentials if provided
        session_kwargs = {"region_name": region}
        if access_key_id and secret_access_key:
            session_kwargs["aws_access_key_id"] = access_key_id
            session_kwargs["aws_secret_access_key"] = secret_access_key

        self._session = aioboto3.Session(**session_kwargs)

        logger.info(
            f"S3StorageAdapter initialized: bucket={bucket_name}, "
            f"region={region}, endpoint={endpoint_url or 'AWS S3'}"
        )

    async def _get_client(self):
        """Get an S3 client context manager."""
        return self._session.client("s3", endpoint_url=self._endpoint_url)

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: Optional[dict] = None,
    ) -> UploadResult:
        """Upload a file to S3."""
        async with await self._get_client() as s3:
            try:
                put_kwargs = {
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "Body": file_content,
                    "ContentType": content_type,
                }
                if metadata:
                    # S3 metadata can only contain ASCII characters
                    # URL-encode non-ASCII values to comply with this requirement
                    from urllib.parse import quote

                    encoded_metadata = {}
                    for k, v in metadata.items():
                        str_v = str(v)
                        # Check if value contains non-ASCII characters
                        try:
                            str_v.encode("ascii")
                            encoded_metadata[k] = str_v
                        except UnicodeEncodeError:
                            # URL-encode non-ASCII values
                            encoded_metadata[k] = quote(str_v, safe="")
                    put_kwargs["Metadata"] = encoded_metadata

                response = await s3.put_object(**put_kwargs)

                logger.info(f"Uploaded file to S3: {object_key} ({len(file_content)} bytes)")

                return UploadResult(
                    object_key=object_key,
                    size_bytes=len(file_content),
                    content_type=content_type,
                    etag=response.get("ETag", "").strip('"'),
                )

            except ClientError as e:
                logger.error(f"Failed to upload file to S3: {object_key}, error: {e}")
                raise

    async def generate_presigned_url(
        self,
        object_key: str,
        expiration_seconds: int = 3600,
        content_disposition: Optional[str] = None,
    ) -> str:
        """Generate a presigned URL for downloading a file."""
        async with await self._get_client() as s3:
            try:
                params = {
                    "Bucket": self._bucket,
                    "Key": object_key,
                }
                if content_disposition:
                    params["ResponseContentDisposition"] = content_disposition

                url = await s3.generate_presigned_url(
                    "get_object",
                    Params=params,
                    ExpiresIn=expiration_seconds,
                )

                logger.debug(
                    f"Generated presigned URL for: {object_key} (expires in {expiration_seconds}s)"
                )
                return url

            except ClientError as e:
                logger.error(f"Failed to generate presigned URL: {object_key}, error: {e}")
                raise

    async def delete_file(self, object_key: str) -> bool:
        """Delete a file from S3."""
        async with await self._get_client() as s3:
            try:
                # Check if file exists first
                if not await self.file_exists(object_key):
                    logger.warning(f"File not found for deletion: {object_key}")
                    return False

                await s3.delete_object(
                    Bucket=self._bucket,
                    Key=object_key,
                )

                logger.info(f"Deleted file from S3: {object_key}")
                return True

            except ClientError as e:
                logger.error(f"Failed to delete file from S3: {object_key}, error: {e}")
                raise

    async def file_exists(self, object_key: str) -> bool:
        """Check if a file exists in S3."""
        async with await self._get_client() as s3:
            try:
                await s3.head_object(
                    Bucket=self._bucket,
                    Key=object_key,
                )
                return True

            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "404":
                    return False
                logger.error(f"Error checking file existence: {object_key}, error: {e}")
                raise

    async def get_file(self, object_key: str) -> Optional[bytes]:
        """Retrieve a file's content from S3."""
        async with await self._get_client() as s3:
            try:
                response = await s3.get_object(
                    Bucket=self._bucket,
                    Key=object_key,
                )
                content = await response["Body"].read()
                logger.debug(f"Retrieved file from S3: {object_key} ({len(content)} bytes)")
                return content

            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "NoSuchKey":
                    logger.warning(f"File not found: {object_key}")
                    return None
                logger.error(f"Failed to get file from S3: {object_key}, error: {e}")
                raise

    async def list_files(
        self,
        prefix: str,
        max_keys: int = 1000,
    ) -> list[str]:
        """List files with a given prefix."""
        async with await self._get_client() as s3:
            try:
                response = await s3.list_objects_v2(
                    Bucket=self._bucket,
                    Prefix=prefix,
                    MaxKeys=max_keys,
                )

                files = []
                for obj in response.get("Contents", []):
                    files.append(obj["Key"])

                logger.debug(f"Listed {len(files)} files with prefix: {prefix}")
                return files

            except ClientError as e:
                logger.error(f"Failed to list files with prefix: {prefix}, error: {e}")
                raise

    async def ensure_bucket_exists(self) -> bool:
        """
        Ensure the bucket exists, creating it if necessary.

        Returns:
            True if bucket exists or was created, False on error
        """
        async with await self._get_client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
                logger.debug(f"Bucket exists: {self._bucket}")
                return True

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code")
                if error_code == "404":
                    # Bucket doesn't exist, create it
                    try:
                        create_kwargs = {"Bucket": self._bucket}
                        # LocationConstraint is required for regions other than us-east-1
                        if self._region != "us-east-1":
                            create_kwargs["CreateBucketConfiguration"] = {
                                "LocationConstraint": self._region
                            }
                        await s3.create_bucket(**create_kwargs)
                        logger.info(f"Created bucket: {self._bucket}")
                        return True
                    except ClientError as create_error:
                        logger.error(
                            f"Failed to create bucket: {self._bucket}, error: {create_error}"
                        )
                        return False
                else:
                    logger.error(f"Error checking bucket: {self._bucket}, error: {e}")
                    return False

    # ==================== Multipart Upload Methods ====================

    async def create_multipart_upload(
        self,
        object_key: str,
        content_type: str,
        metadata: Optional[dict] = None,
    ) -> MultipartUploadResult:
        """Initialize a multipart upload in S3."""
        async with await self._get_client() as s3:
            try:
                kwargs = {
                    "Bucket": self._bucket,
                    "Key": object_key,
                    "ContentType": content_type,
                }
                if metadata:
                    # S3 metadata can only contain ASCII characters
                    # URL-encode non-ASCII values to comply with this requirement
                    from urllib.parse import quote

                    encoded_metadata = {}
                    for k, v in metadata.items():
                        str_v = str(v)
                        try:
                            str_v.encode("ascii")
                            encoded_metadata[k] = str_v
                        except UnicodeEncodeError:
                            encoded_metadata[k] = quote(str_v, safe="")
                    kwargs["Metadata"] = encoded_metadata

                response = await s3.create_multipart_upload(**kwargs)

                logger.info(
                    f"Created multipart upload: {object_key}, upload_id={response['UploadId']}"
                )

                return MultipartUploadResult(
                    upload_id=response["UploadId"],
                    object_key=object_key,
                )

            except ClientError as e:
                logger.error(f"Failed to create multipart upload: {object_key}, error: {e}")
                raise

    async def upload_part(
        self,
        object_key: str,
        upload_id: str,
        part_number: int,
        data: bytes,
    ) -> PartUploadResult:
        """Upload a single part in a multipart upload to S3."""
        async with await self._get_client() as s3:
            try:
                response = await s3.upload_part(
                    Bucket=self._bucket,
                    Key=object_key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=data,
                )

                logger.debug(f"Uploaded part {part_number} for {object_key} ({len(data)} bytes)")

                return PartUploadResult(
                    part_number=part_number,
                    etag=response["ETag"].strip('"'),
                )

            except ClientError as e:
                logger.error(f"Failed to upload part {part_number} for {object_key}, error: {e}")
                raise

    async def complete_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
        parts: List[PartUploadResult],
    ) -> UploadResult:
        """Complete a multipart upload in S3."""
        async with await self._get_client() as s3:
            try:
                # Build parts list for S3 API
                s3_parts = [
                    {"PartNumber": p.part_number, "ETag": f'"{p.etag}"'}
                    for p in sorted(parts, key=lambda x: x.part_number)
                ]

                response = await s3.complete_multipart_upload(
                    Bucket=self._bucket,
                    Key=object_key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": s3_parts},
                )

                # Get file info after completion
                head = await s3.head_object(Bucket=self._bucket, Key=object_key)

                logger.info(
                    f"Completed multipart upload: {object_key} ({head['ContentLength']} bytes)"
                )

                return UploadResult(
                    object_key=object_key,
                    size_bytes=head["ContentLength"],
                    content_type=head.get("ContentType", "application/octet-stream"),
                    etag=response.get("ETag", "").strip('"'),
                )

            except ClientError as e:
                logger.error(f"Failed to complete multipart upload: {object_key}, error: {e}")
                raise

    async def abort_multipart_upload(
        self,
        object_key: str,
        upload_id: str,
    ) -> bool:
        """Abort a multipart upload and clean up uploaded parts."""
        async with await self._get_client() as s3:
            try:
                await s3.abort_multipart_upload(
                    Bucket=self._bucket,
                    Key=object_key,
                    UploadId=upload_id,
                )

                logger.info(f"Aborted multipart upload: {object_key}, upload_id={upload_id}")
                return True

            except ClientError as e:
                logger.error(f"Failed to abort multipart upload: {object_key}, error: {e}")
                raise

    async def generate_presigned_upload_url(
        self,
        object_key: str,
        content_type: str,
        expiration_seconds: int = 3600,
    ) -> str:
        """Generate a presigned URL for uploading a file directly."""
        async with await self._get_client() as s3:
            try:
                url = await s3.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": self._bucket,
                        "Key": object_key,
                        "ContentType": content_type,
                    },
                    ExpiresIn=expiration_seconds,
                )

                logger.debug(
                    f"Generated presigned upload URL for: {object_key} "
                    f"(expires in {expiration_seconds}s)"
                )
                return url

            except ClientError as e:
                logger.error(f"Failed to generate presigned upload URL: {object_key}, error: {e}")
                raise
