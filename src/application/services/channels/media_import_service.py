"""Media import service for downloading and importing channel media to workspace."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.channels.message import Message, MessageType
from src.infrastructure.adapters.secondary.channels.feishu.media_downloader import (
    FeishuMediaDownloader,
    FeishuMediaDownloadError,
)

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService
    from src.domain.model.artifact.artifact import Artifact
    from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

logger = logging.getLogger(__name__)


class MediaImportError(Exception):
    """Exception raised when media import fails."""

    pass


class MediaImportService:
    """Service for importing channel media files to workspace.

    This service orchestrates the flow:
    1. Download media from channel (e.g., Feishu)
    2. Import to sandbox workspace (/workspace/input/)
    3. Create Artifact record (optional)

    The service follows functional design - no state is held, all dependencies
    are passed as parameters to each method call.
    """

    def __init__(self, feishu_downloader: FeishuMediaDownloader) -> None:
        """Initialize the media import service.

        Args:
            feishu_downloader: Feishu media downloader instance
        """
        self._feishu_downloader = feishu_downloader

    async def import_media_to_workspace(
        self,
        message: Message,
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        mcp_adapter: MCPSandboxAdapter,  # MCPSandboxAdapter - avoid circular import
        artifact_service: ArtifactService,  # ArtifactService - avoid circular import
        db_session: AsyncSession,
    ) -> str | None:
        """Import media from channel message to workspace.

        This method:
        1. Downloads media from Feishu
        2. Imports to sandbox at /workspace/input/
        3. Creates Artifact record
        4. Updates message.content with sandbox_path and artifact_id

        Args:
            message: Channel message containing media
            project_id: Project ID (required)
            tenant_id: Tenant ID (can be empty string)
            conversation_id: Conversation ID
            mcp_adapter: MCP sandbox adapter for file import
            artifact_service: Artifact service for creating artifacts
            db_session: Database session for transaction management

        Returns:
            Sandbox path if successful, None otherwise

        Raises:
            MediaImportError: If import fails critically
        """
        if not message.content.has_media_to_import():
            logger.debug(f"Message {message.id} has no media to import, skipping")
            return None

        if not project_id:
            logger.warning(f"Cannot import media: missing project_id for message {message.id}")
            return None

        try:
            # Step 1: Determine media type, file key, and message_id
            media_type, file_key, message_id = self._extract_media_info(message)
            if not file_key:
                logger.warning(f"No file_key found in message {message.id}")
                return None

            # Check if message_id is required for this media type
            if media_type in ("file", "audio", "video") and not message_id:
                logger.warning(
                    f"message_id is required for {media_type} download but was not found - "
                    f"message_id={message_id}, message_id will be None"
                )

            # Step 2: Download from Feishu
            logger.info(
                f"Downloading {media_type} from Feishu: file_key={file_key}, "
                f"message_id={message_id}"
            )

            content, metadata = await self._feishu_downloader.download_media(
                file_key=file_key,
                media_type=media_type,
                message_id=message_id,
                file_name=message.content.file_name,
            )

            # Step 3: Generate filename with proper extension
            filename = self._generate_filename(
                media_type=media_type,
                file_key=file_key,
                original_filename=metadata.get("filename"),
                mime_type=metadata.get("mime_type"),
            )

            # Step 4: Import to sandbox
            sandbox_path = await self._import_to_sandbox(
                content=content,
                filename=filename,
                project_id=project_id,
                mcp_adapter=mcp_adapter,
                db_session=db_session,
            )

            # Step 5: Create artifact
            artifact = await self._create_artifact(
                content=content,
                filename=filename,
                metadata=metadata,
                project_id=project_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                sandbox_path=sandbox_path,
                artifact_service=artifact_service,
            )

            logger.info(
                f"Successfully imported media to workspace: "
                f"sandbox_path={sandbox_path}, artifact_id={artifact.id if artifact else None}"
            )

            return sandbox_path

        except FeishuMediaDownloadError as e:
            logger.error(f"Failed to download media from Feishu: {e}")
            # Graceful degradation - return None instead of raising
            return None
        except Exception as e:
            logger.error(f"Unexpected error importing media: {e}", exc_info=True)
            # Graceful degradation - return None instead of raising
            return None

    def _extract_media_info(self, message: Message) -> tuple[str, str | None, str | None]:
        """Extract media type, file key, and message_id from message.

        Args:
            message: Channel message

        Returns:
            Tuple of (media_type, file_key, message_id)
        """
        content = message.content
        media_type = content.type.value

        message_id: str | None = None
        if message.raw_data:
            event = message.raw_data.get("event")
            if isinstance(event, dict):
                msg_data = event.get("message")
                if isinstance(msg_data, dict):
                    message_id = msg_data.get("message_id")

        logger.info(
            f"[MediaImportService] Extracting media info - "
            f"media_type={media_type}, "
            f"file_key={content.file_key}, "
            f"image_key={content.image_key}, "
            f"message_id={message_id}, "
            f"raw_data_keys={list(message.raw_data.keys()) if message.raw_data else None}"
        )

        if content.type == MessageType.IMAGE:
            return media_type, content.image_key, message_id
        elif content.type == MessageType.STICKER:
            return "image", content.file_key, message_id
        elif content.type in (MessageType.FILE, MessageType.AUDIO, MessageType.VIDEO):
            return media_type, content.file_key, message_id
        elif content.type == MessageType.POST and content.image_key:
            # Post message with embedded image
            return "image", content.image_key, message_id
        else:
            return media_type, None, message_id

    def _generate_filename(
        self,
        media_type: str,
        file_key: str,
        original_filename: str | None,
        mime_type: str | None = None,
    ) -> str:
        """Generate filename for imported file.

        Pattern: feishu_{type}_{key}.{ext} or original filename if available

        Args:
            media_type: Media type (image, file, audio, video, sticker)
            file_key: Feishu file key
            original_filename: Original filename from Feishu
            mime_type: MIME type from download response

        Returns:
            Generated filename
        """
        if original_filename:
            # Check if original filename has extension
            _, orig_ext = os.path.splitext(original_filename)
            if orig_ext:
                # Has extension, sanitize and use it
                safe_name = os.path.basename(original_filename)
                safe_name = re.sub(r"[^\w\-_\.]", "_", safe_name)
                if len(safe_name) > 200:
                    name, ext = os.path.splitext(safe_name)
                    safe_name = name[: 200 - len(ext)] + ext
                return f"feishu_{safe_name}"

        # Generate from type and key
        # Use first 8 chars of file_key for uniqueness
        short_key = file_key[:8] if len(file_key) >= 8 else file_key
        # Add UUID suffix to prevent collisions
        unique_suffix = uuid.uuid4().hex[:8]

        # Determine extension from MIME type or default map
        if mime_type:
            mime_to_ext = {
                "image/png": "png",
                "image/jpeg": "jpg",
                "image/jpg": "jpg",
                "image/gif": "gif",
                "image/webp": "webp",
                "image/bmp": "bmp",
                "image/svg+xml": "svg",
                "audio/mpeg": "mp3",
                "audio/mp3": "mp3",
                "audio/wav": "wav",
                "audio/ogg": "ogg",
                "video/mp4": "mp4",
                "video/webm": "webm",
                "video/quicktime": "mov",
                "application/pdf": "pdf",
                "application/zip": "zip",
                "text/plain": "txt",
                "text/html": "html",
                "text/css": "css",
                "text/javascript": "js",
                "application/json": "json",
                "application/xml": "xml",
            }
            ext = mime_to_ext.get(mime_type.lower(), None)
            if ext:
                return f"feishu_{media_type}_{short_key}_{unique_suffix}.{ext}"

        # Fallback to default extension map
        extension_map = {
            "image": "png",
            "audio": "mp3",
            "video": "mp4",
            "sticker": "png",
            "file": "bin",
        }
        ext = extension_map.get(media_type, "bin")

        return f"feishu_{media_type}_{short_key}_{unique_suffix}.{ext}"

    async def _import_to_sandbox(
        self,
        content: bytes,
        filename: str,
        project_id: str,
        mcp_adapter: MCPSandboxAdapter,
        db_session: AsyncSession,
    ) -> str:
        """Import file to sandbox workspace.

        Args:
            content: File content in bytes
            filename: Target filename
            project_id: Project ID
            mcp_adapter: MCP sandbox adapter
            db_session: Database session

        Returns:
            Sandbox path (e.g., /workspace/input/filename)

        Raises:
            MediaImportError: If sandbox import fails
        """
        try:
            # 1. Get or create sandbox for project
            sandbox = await mcp_adapter.get_or_create_sandbox(
                project_id=project_id,
                db_session=db_session,
            )

            if not sandbox:
                raise MediaImportError(f"No sandbox available for project {project_id}")

            # 2. Convert to base64
            content_base64 = base64.b64encode(content).decode("utf-8")

            # 3. Call MCP tool: import_file
            result = await mcp_adapter.call_tool(
                sandbox_id=sandbox.id,
                tool_name="import_file",
                arguments={
                    "filename": filename,
                    "content_base64": content_base64,
                    "destination": "/workspace/input",
                    "overwrite": True,
                },
            )

            # Extract sandbox path from result
            logger.info(f"[MediaImportService] Import result: {result}")

            # MCP tool returns result in format:
            # {"content": [{"type": "text", "text": "{\"success\": true, ...}"}], "is_error": False}
            is_error = result.get("is_error", True)
            if is_error:
                error_msg = result.get("error", "Unknown error")
                raise MediaImportError(f"Sandbox import failed: {error_msg}")

            # Parse nested JSON from content[0].text
            try:
                content_list = result.get("content", [])
                if content_list and isinstance(content_list[0], dict):
                    text_content = content_list[0].get("text", "{}")
                    import_result = json.loads(text_content)
                else:
                    import_result = result
            except (json.JSONDecodeError, TypeError):
                import_result = result

            if import_result.get("success"):
                sandbox_path = import_result.get("path", "")
                if not sandbox_path:
                    # Fallback to expected path
                    sandbox_path = f"/workspace/input/{filename}"
                logger.info(f"[MediaImportService] Import success: {sandbox_path}")
                return sandbox_path
            else:
                error_msg = import_result.get(
                    "error", import_result.get("message", "Unknown error")
                )
                raise MediaImportError(f"Sandbox import failed: {error_msg}")

        except Exception as e:
            if isinstance(e, MediaImportError):
                raise
            raise MediaImportError(f"Failed to import to sandbox: {e}") from e

    async def _create_artifact(
        self,
        content: bytes,
        filename: str,
        metadata: dict[str, Any],
        project_id: str,
        tenant_id: str,
        conversation_id: str,
        sandbox_path: str,
        artifact_service: ArtifactService,
    ) -> Artifact | None:
        """Create Artifact record for imported media.

        Args:
            content: File content in bytes
            filename: Filename
            metadata: Media metadata from downloader
            project_id: Project ID
            tenant_id: Tenant ID
            conversation_id: Conversation ID
            sandbox_path: Path in sandbox
            artifact_service: Artifact service for creating artifacts

        Returns:
            Created Artifact entity, or None if creation fails
        """
        try:
            artifact = await artifact_service.create_artifact(
                file_content=content,
                filename=filename,
                project_id=project_id,
                tenant_id=tenant_id,
                mime_type=metadata.get("mime_type"),
                sandbox_path=sandbox_path,
                conversation_id=conversation_id,
                metadata={
                    "source": "feishu",
                    "size_bytes": metadata.get("size_bytes"),
                    "original_mime_type": metadata.get("mime_type"),
                },
            )

            logger.info(f"Created artifact {artifact.id} for {filename}")
            return artifact

        except Exception as e:
            # Non-critical error - log and continue
            logger.error(f"Failed to create artifact for {filename}: {e}", exc_info=True)
            return None
