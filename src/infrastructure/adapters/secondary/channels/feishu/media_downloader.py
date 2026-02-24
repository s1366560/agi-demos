"""Feishu media downloader for downloading images, files, audio, video, and stickers."""

import asyncio
import logging
import mimetypes
import re
import time
from types import TracebackType
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class FeishuMediaDownloadError(Exception):
    """Exception raised when media download fails."""



class FeishuMediaDownloader:
    """Download media files from Feishu/Lark server.

    This class handles downloading various media types (image, file, audio, video, sticker)
    from Feishu's API with retry logic and proper authentication.
    """

    _MAX_RETRIES = 3
    _RETRY_DELAY_SECONDS = 1.0
    _TIMEOUT_SECONDS = 30
    _MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB limit

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        domain: str = "feishu",
    ) -> None:
        """Initialize the media downloader.

        Args:
            app_id: Feishu app ID
            app_secret: Feishu app secret
            domain: API domain ("feishu" or "lark")
        """
        self._app_id = app_id
        self._app_secret = app_secret
        self._domain = domain
        self._tenant_access_token: str | None = None
        self._token_expires_at: float = 0
        self._session: aiohttp.ClientSession | None = None
        self._token_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the HTTP session and cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "FeishuMediaDownloader":
        """Context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        await self.close()

    async def _get_tenant_access_token(self) -> str:
        """Get tenant access token from Feishu API.

        Returns:
            Tenant access token

        Raises:
            FeishuMediaDownloadError: If token acquisition fails
        """
        async with self._token_lock:
            # Check if token is still valid (with 5 minute buffer)
            if self._tenant_access_token and time.time() < self._token_expires_at - 300:
                return self._tenant_access_token

            # Determine API base URL based on domain
            base_url = (
                "https://open.larksuite.com" if self._domain == "lark" else "https://open.feishu.cn"
            )

            # Request new token
            url = f"{base_url}/open-apis/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self._app_id,
                "app_secret": self._app_secret,
            }

            try:
                session = await self._get_session()
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status != 200:
                        raise FeishuMediaDownloadError(
                            f"Failed to get tenant access token: HTTP {response.status}"
                        )

                    data = await response.json()
                    if data.get("code") != 0:
                        raise FeishuMediaDownloadError(
                            f"Feishu API error: {data.get('msg', 'Unknown error')}"
                        )

                    self._tenant_access_token = data["tenant_access_token"]
                    self._token_expires_at = time.time() + data.get("expire", 7200)
                    return self._tenant_access_token

            except TimeoutError:
                raise FeishuMediaDownloadError("Timeout getting tenant access token") from None
            except Exception as e:
                raise FeishuMediaDownloadError(f"Error getting tenant access token: {e}") from e

    def _get_api_base_url(self) -> str:
        """Get API base URL based on domain configuration."""
        return "https://open.larksuite.com" if self._domain == "lark" else "https://open.feishu.cn"

    async def download_image(
        self,
        image_key: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Download an image from Feishu.

        Args:
            image_key: Feishu image key

        Returns:
            Tuple of (image_bytes, metadata_dict)

        Raises:
            FeishuMediaDownloadError: If download fails
        """
        base_url = self._get_api_base_url()
        url = f"{base_url}/open-apis/im/v1/images/{image_key}/download"

        return await self._download_with_retry(url, f"image_{image_key}")

    async def download_file(
        self,
        file_key: str,
        message_id: str,
        file_name: str | None = None,
        media_type: str = "file",
    ) -> tuple[bytes, dict[str, Any]]:
        """Download a file from Feishu IM message resources.

        Uses the correct API endpoint for downloading files from chat messages:
        GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}?type={type}

        Args:
            file_key: Feishu file key
            message_id: Feishu message ID (required for file/audio/video download)
            file_name: Original file name (for metadata)
            media_type: Media type ("file", "audio", "video")

        Returns:
            Tuple of (file_bytes, metadata_dict)

        Raises:
            FeishuMediaDownloadError: If download fails
        """
        base_url = self._get_api_base_url()
        url = f"{base_url}/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type={media_type}"

        filename = file_name or f"file_{file_key}"
        return await self._download_with_retry(url, filename)

    async def download_media(
        self,
        file_key: str,
        media_type: str,
        message_id: str | None = None,
        file_name: str | None = None,
    ) -> tuple[bytes, dict[str, Any]]:
        """Download media file from Feishu based on type.

        This is a unified method that routes to the appropriate download method
        based on media type.

        Args:
            file_key: Feishu file/image key
            media_type: Media type ("image", "file", "audio", "video", "sticker")
            message_id: Feishu message ID (required for file/audio/video download)
            file_name: Original file name (optional, for files)

        Returns:
            Tuple of (media_bytes, metadata_dict)

        Raises:
            FeishuMediaDownloadError: If download fails or type is unsupported
        """
        if media_type == "image" or media_type == "sticker":
            # For images in chat messages, use the message resources API
            if message_id:
                return await self.download_file(file_key, message_id, file_name, "image")
            else:
                # Fallback to direct image download (for standalone images)
                return await self.download_image(file_key)
        elif media_type in ("file", "audio", "video"):
            if not message_id:
                raise FeishuMediaDownloadError(f"message_id is required for {media_type} download")
            return await self.download_file(file_key, message_id, file_name, media_type)
        else:
            raise FeishuMediaDownloadError(f"Unsupported media type: {media_type}")

    async def _download_with_retry(
        self,
        url: str,
        default_filename: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Download file with retry logic.

        Args:
            url: Download URL
            default_filename: Default filename if not provided in response

        Returns:
            Tuple of (content_bytes, metadata_dict)

        Raises:
            FeishuMediaDownloadError: If all retries fail
        """
        last_error: Exception | None = None

        for attempt in range(self._MAX_RETRIES):
            try:
                return await self._download_once(url, default_filename)
            except Exception as e:
                last_error = e
                logger.warning(f"Download attempt {attempt + 1}/{self._MAX_RETRIES} failed: {e}")
                if attempt < self._MAX_RETRIES - 1:
                    await asyncio.sleep(self._RETRY_DELAY_SECONDS * (2**attempt))

        raise FeishuMediaDownloadError(f"Failed after {self._MAX_RETRIES} retries: {last_error}")

    async def _download_once(
        self,
        url: str,
        default_filename: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Download file once (single attempt).

        Args:
            url: Download URL
            default_filename: Default filename if not provided in response

        Returns:
            Tuple of (content_bytes, metadata_dict)

        Raises:
            FeishuMediaDownloadError: If download fails
        """
        # Get authentication token
        token = await self._get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
        }

        try:
            session = await self._get_session()
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self._TIMEOUT_SECONDS),
            ) as response:
                if response.status == 404:
                    raise FeishuMediaDownloadError(f"Media not found: HTTP {response.status}")
                elif response.status != 200:
                    text = await response.text()
                    raise FeishuMediaDownloadError(
                        f"Download failed: HTTP {response.status}, {text}"
                    )

                # Check content length
                content_length = response.content_length
                if content_length and content_length > self._MAX_FILE_SIZE_BYTES:
                    raise FeishuMediaDownloadError(
                        f"File too large: {content_length} bytes (max: {self._MAX_FILE_SIZE_BYTES})"
                    )

                # Read content
                content = await response.read()

                # Check actual size
                if len(content) > self._MAX_FILE_SIZE_BYTES:
                    raise FeishuMediaDownloadError(
                        f"File too large: {len(content)} bytes (max: {self._MAX_FILE_SIZE_BYTES})"
                    )

                # Extract metadata
                content_type = response.headers.get("Content-Type", "")
                content_disposition = response.headers.get("Content-Disposition", "")

                # Try to extract filename from Content-Disposition
                filename = default_filename
                if "filename=" in content_disposition:
                    match = re.search(r'filename[*]?=["\']?([^"\';\s]+)', content_disposition)
                    if match:
                        filename = match.group(1)

                # Detect MIME type and extension
                mime_type = content_type.split(";")[0].strip() if content_type else None
                if not mime_type:
                    mime_type, _ = mimetypes.guess_type(filename)

                # Build metadata
                metadata = {
                    "filename": filename,
                    "size_bytes": len(content),
                    "mime_type": mime_type,
                    "content_type": content_type,
                }

                logger.info(
                    f"Successfully downloaded media: {filename}, {len(content)} bytes, {mime_type}"
                )

                return content, metadata

        except TimeoutError:
            raise FeishuMediaDownloadError(
                f"Download timeout after {self._TIMEOUT_SECONDS}s"
            ) from None
        except aiohttp.ClientError as e:
            raise FeishuMediaDownloadError(f"HTTP client error: {e}") from e
        except Exception as e:
            if isinstance(e, FeishuMediaDownloadError):
                raise
            raise FeishuMediaDownloadError(f"Unexpected error: {e}") from e
