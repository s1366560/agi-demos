"""Artifact Service - Manages artifact lifecycle, storage, and events.

This service handles:
- Detecting artifacts from sandbox tool executions
- Uploading artifacts to MinIO/S3 storage
- Generating presigned URLs for access
- Publishing artifact events
- Managing artifact lifecycle
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.domain.events.agent_events import (
    AgentArtifactCreatedEvent,
    AgentArtifactErrorEvent,
    AgentArtifactReadyEvent,
    AgentArtifactsBatchEvent,
    ArtifactInfo,
)
from src.domain.model.artifact.artifact import (
    Artifact,
    ArtifactCategory,
    ArtifactStatus,
    detect_mime_type,
    get_category_from_mime,
)
from src.domain.ports.services.storage_service_port import StorageServicePort

logger = logging.getLogger(__name__)


# Common output patterns in sandbox
SANDBOX_OUTPUT_DIRS = [
    "/workspace/output",
    "/workspace/outputs",
    "/tmp/output",
    "/home/user/output",
]

# File patterns that should be ignored
IGNORED_PATTERNS = [
    ".git",
    ".gitignore",
    "__pycache__",
    ".pyc",
    ".pyo",
    "node_modules",
    ".DS_Store",
    "Thumbs.db",
]


class ArtifactService:
    """Service for managing artifacts from tool executions."""

    def __init__(
        self,
        storage_service: StorageServicePort,
        event_publisher: Optional[Callable] = None,
        bucket_prefix: str = "artifacts",
        url_expiration_seconds: int = 7 * 24 * 3600,  # 7 days default
    ):
        """
        Initialize ArtifactService.

        Args:
            storage_service: Storage backend (MinIO/S3)
            event_publisher: Optional async function to publish events
            bucket_prefix: Prefix for artifact storage paths
            url_expiration_seconds: How long presigned URLs remain valid
        """
        self._storage = storage_service
        self._event_publisher = event_publisher
        self._bucket_prefix = bucket_prefix
        self._url_expiration = url_expiration_seconds

        # In-memory artifact tracking (would be DB in production)
        self._artifacts: Dict[str, Artifact] = {}

    def _generate_object_key(
        self,
        tenant_id: str,
        project_id: str,
        filename: str,
        tool_execution_id: Optional[str] = None,
    ) -> str:
        """Generate a unique storage object key for an artifact.

        Format: artifacts/{tenant_id}/{project_id}/{date}/{execution_id}/{uuid}_{filename}
        """
        date_part = datetime.utcnow().strftime("%Y/%m/%d")
        unique_id = uuid.uuid4().hex[:8]

        if tool_execution_id:
            return f"{self._bucket_prefix}/{tenant_id}/{project_id}/{date_part}/{tool_execution_id}/{unique_id}_{filename}"
        else:
            return (
                f"{self._bucket_prefix}/{tenant_id}/{project_id}/{date_part}/{unique_id}_{filename}"
            )

    async def create_artifact(
        self,
        file_content: bytes,
        filename: str,
        project_id: str,
        tenant_id: str,
        sandbox_id: Optional[str] = None,
        tool_execution_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        source_tool: Optional[str] = None,
        source_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Artifact:
        """
        Create and upload a new artifact.

        Args:
            file_content: The file content as bytes
            filename: Original filename
            project_id: Project ID for scoping
            tenant_id: Tenant ID for multi-tenancy
            sandbox_id: The sandbox that produced this artifact
            tool_execution_id: The tool execution that created it
            conversation_id: The conversation context
            source_tool: Name of the tool that created this
            source_path: Original path in sandbox
            metadata: Additional metadata

        Returns:
            Created Artifact entity
        """
        logger.warning(
            f"[ArtifactUpload] create_artifact: filename={filename}, "
            f"size={len(file_content)}, project_id={project_id}"
        )

        # Detect MIME type
        mime_type = detect_mime_type(filename)
        category = get_category_from_mime(mime_type)

        # Generate unique ID and storage key
        artifact_id = str(uuid.uuid4())
        object_key = self._generate_object_key(tenant_id, project_id, filename, tool_execution_id)

        # Create artifact entity
        artifact = Artifact(
            id=artifact_id,
            project_id=project_id,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            tool_execution_id=tool_execution_id,
            conversation_id=conversation_id,
            filename=filename,
            mime_type=mime_type,
            category=category,
            size_bytes=len(file_content),
            object_key=object_key,
            source_tool=source_tool,
            source_path=source_path,
            metadata=metadata or {},
            status=ArtifactStatus.PENDING,
        )

        # Store artifact reference
        self._artifacts[artifact_id] = artifact

        # Emit created event
        await self._publish_artifact_created(artifact, sandbox_id or "")

        try:
            # Mark as uploading
            artifact.mark_uploading()

            # Upload to storage
            logger.warning(
                f"[ArtifactUpload] Starting S3 upload: key={object_key}"
            )
            result = await self._storage.upload_file(
                file_content=file_content,
                object_key=object_key,
                content_type=mime_type,
                metadata={
                    "artifact_id": artifact_id,
                    "project_id": project_id,
                    "tenant_id": tenant_id,
                    "filename": filename,
                    "source_tool": source_tool or "",
                },
            )
            logger.warning(
                f"[ArtifactUpload] S3 upload done: key={object_key}, etag={result.etag}"
            )

            # Generate presigned URL
            logger.warning("[ArtifactUpload] Generating presigned URL...")
            url = await self._storage.generate_presigned_url(
                object_key=object_key,
                expiration_seconds=self._url_expiration,
            )
            logger.warning(f"[ArtifactUpload] Presigned URL generated")

            logger.warning(
                f"[ArtifactUpload] Uploaded {artifact_id}: "
                f"{filename} ({len(file_content)} bytes, etag={result.etag})"
            )

            # Generate preview URL for images (if supported)
            preview_url = None
            if category == ArtifactCategory.IMAGE:
                # For now, use the same URL; could add thumbnail generation later
                preview_url = url

            # Mark as ready
            artifact.mark_ready(url, preview_url)

            # Update metadata with storage info
            artifact.metadata["etag"] = result.etag

            # Emit ready event
            await self._publish_artifact_ready(artifact, sandbox_id or "")

            logger.info(f"Artifact created: {artifact_id} ({filename}, {len(file_content)} bytes)")

            return artifact

        except Exception as e:
            error_msg = str(e)
            artifact.mark_error(error_msg)

            # Emit error event
            await self._publish_artifact_error(artifact, sandbox_id or "", error_msg)

            logger.error(f"Failed to create artifact {artifact_id}: {error_msg}")
            raise

    async def create_artifacts_batch(
        self,
        files: List[Tuple[bytes, str]],  # List of (content, filename)
        project_id: str,
        tenant_id: str,
        sandbox_id: Optional[str] = None,
        tool_execution_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        source_tool: Optional[str] = None,
    ) -> List[Artifact]:
        """
        Create multiple artifacts in batch.

        More efficient than creating one by one as it can emit a batch event.

        Args:
            files: List of (content, filename) tuples
            project_id: Project ID
            tenant_id: Tenant ID
            sandbox_id: Sandbox ID
            tool_execution_id: Tool execution ID
            conversation_id: Conversation ID
            source_tool: Source tool name

        Returns:
            List of created Artifact entities
        """
        artifacts = []

        for content, filename in files:
            try:
                artifact = await self.create_artifact(
                    file_content=content,
                    filename=filename,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    tool_execution_id=tool_execution_id,
                    conversation_id=conversation_id,
                    source_tool=source_tool,
                )
                artifacts.append(artifact)
            except Exception as e:
                logger.error(f"Failed to create artifact for {filename}: {e}")

        # Emit batch event with all successful artifacts
        if artifacts:
            await self._publish_artifacts_batch(
                artifacts, sandbox_id or "", tool_execution_id, source_tool
            )

        return artifacts

    async def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        """Get an artifact by ID."""
        return self._artifacts.get(artifact_id)

    async def get_artifacts_by_tool_execution(self, tool_execution_id: str) -> List[Artifact]:
        """Get all artifacts for a specific tool execution."""
        return [a for a in self._artifacts.values() if a.tool_execution_id == tool_execution_id]

    async def get_artifacts_by_project(
        self,
        project_id: str,
        limit: int = 100,
        category: Optional[ArtifactCategory] = None,
    ) -> List[Artifact]:
        """Get artifacts for a project, optionally filtered by category."""
        artifacts = [
            a
            for a in self._artifacts.values()
            if a.project_id == project_id and a.status == ArtifactStatus.READY
        ]

        if category:
            artifacts = [a for a in artifacts if a.category == category]

        # Sort by creation time, newest first
        artifacts.sort(key=lambda a: a.created_at, reverse=True)

        return artifacts[:limit]

    async def refresh_artifact_url(self, artifact_id: str) -> Optional[str]:
        """Refresh the presigned URL for an artifact."""
        artifact = self._artifacts.get(artifact_id)
        if not artifact or artifact.status != ArtifactStatus.READY:
            return None

        try:
            url = await self._storage.generate_presigned_url(
                object_key=artifact.object_key,
                expiration_seconds=self._url_expiration,
            )
            artifact.url = url
            return url
        except Exception as e:
            logger.error(f"Failed to refresh URL for artifact {artifact_id}: {e}")
            return None

    async def delete_artifact(self, artifact_id: str) -> bool:
        """Delete an artifact from storage."""
        artifact = self._artifacts.get(artifact_id)
        if not artifact:
            return False

        try:
            # Delete from storage
            await self._storage.delete_file(artifact.object_key)

            # Mark as deleted
            artifact.mark_deleted()

            logger.info(f"Deleted artifact: {artifact_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete artifact {artifact_id}: {e}")
            return False

    # === Event Publishing ===

    async def _publish_artifact_created(self, artifact: Artifact, sandbox_id: str) -> None:
        """Publish artifact_created event."""
        if not self._event_publisher:
            return

        event = AgentArtifactCreatedEvent(
            artifact_id=artifact.id,
            sandbox_id=sandbox_id,
            tool_execution_id=artifact.tool_execution_id,
            filename=artifact.filename,
            mime_type=artifact.mime_type,
            category=artifact.category.value,
            size_bytes=artifact.size_bytes,
            source_tool=artifact.source_tool,
            source_path=artifact.source_path,
        )

        try:
            await self._event_publisher(artifact.project_id, event)
        except Exception as e:
            logger.error(f"Failed to publish artifact_created event: {e}")

    async def _publish_artifact_ready(self, artifact: Artifact, sandbox_id: str) -> None:
        """Publish artifact_ready event."""
        if not self._event_publisher:
            return

        event = AgentArtifactReadyEvent(
            artifact_id=artifact.id,
            sandbox_id=sandbox_id,
            tool_execution_id=artifact.tool_execution_id,
            filename=artifact.filename,
            mime_type=artifact.mime_type,
            category=artifact.category.value,
            size_bytes=artifact.size_bytes,
            url=artifact.url or "",
            preview_url=artifact.preview_url,
            source_tool=artifact.source_tool,
            metadata=artifact.metadata,
        )

        try:
            await self._event_publisher(artifact.project_id, event)
        except Exception as e:
            logger.error(f"Failed to publish artifact_ready event: {e}")

    async def _publish_artifact_error(
        self, artifact: Artifact, sandbox_id: str, error: str
    ) -> None:
        """Publish artifact_error event."""
        if not self._event_publisher:
            return

        event = AgentArtifactErrorEvent(
            artifact_id=artifact.id,
            sandbox_id=sandbox_id,
            tool_execution_id=artifact.tool_execution_id,
            filename=artifact.filename,
            error=error,
        )

        try:
            await self._event_publisher(artifact.project_id, event)
        except Exception as e:
            logger.error(f"Failed to publish artifact_error event: {e}")

    async def _publish_artifacts_batch(
        self,
        artifacts: List[Artifact],
        sandbox_id: str,
        tool_execution_id: Optional[str],
        source_tool: Optional[str],
    ) -> None:
        """Publish artifacts_batch event."""
        if not self._event_publisher or not artifacts:
            return

        artifact_infos = [
            ArtifactInfo(
                id=a.id,
                filename=a.filename,
                mime_type=a.mime_type,
                category=a.category.value,
                size_bytes=a.size_bytes,
                url=a.url,
                preview_url=a.preview_url,
                source_tool=a.source_tool,
                metadata=a.metadata,
            )
            for a in artifacts
            if a.status == ArtifactStatus.READY
        ]

        if not artifact_infos:
            return

        event = AgentArtifactsBatchEvent(
            sandbox_id=sandbox_id,
            tool_execution_id=tool_execution_id,
            artifacts=artifact_infos,
            source_tool=source_tool,
        )

        try:
            # Use first artifact's project_id
            await self._event_publisher(artifacts[0].project_id, event)
        except Exception as e:
            logger.error(f"Failed to publish artifacts_batch event: {e}")


class SandboxArtifactDetector:
    """Detects artifacts produced by sandbox tool executions.

    This class is used to scan sandbox filesystem and identify new files
    that should be uploaded as artifacts.
    """

    def __init__(
        self,
        artifact_service: ArtifactService,
        output_dirs: Optional[List[str]] = None,
    ):
        """
        Initialize detector.

        Args:
            artifact_service: ArtifactService for creating artifacts
            output_dirs: List of directories to monitor for outputs
        """
        self._artifact_service = artifact_service
        self._output_dirs = output_dirs or SANDBOX_OUTPUT_DIRS
        self._tracked_files: Dict[str, set] = {}  # sandbox_id -> set of known files

    def _should_ignore(self, path: str) -> bool:
        """Check if a file should be ignored."""
        for pattern in IGNORED_PATTERNS:
            if pattern in path:
                return True
        return False

    async def detect_new_artifacts(
        self,
        sandbox_id: str,
        file_list: List[str],
        project_id: str,
        tenant_id: str,
        tool_execution_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        source_tool: Optional[str] = None,
        get_file_content: Optional[Callable[[str], bytes]] = None,
    ) -> List[str]:
        """
        Detect new files and identify which should become artifacts.

        Args:
            sandbox_id: Sandbox ID
            file_list: List of file paths in sandbox
            project_id: Project ID
            tenant_id: Tenant ID
            tool_execution_id: Tool execution ID
            conversation_id: Conversation ID
            source_tool: Source tool name
            get_file_content: Function to retrieve file content

        Returns:
            List of new file paths detected
        """
        # Get known files for this sandbox
        known_files = self._tracked_files.get(sandbox_id, set())

        # Find new files in output directories
        new_files = []
        for file_path in file_list:
            if file_path in known_files:
                continue

            if self._should_ignore(file_path):
                continue

            # Check if file is in an output directory
            is_output = any(file_path.startswith(output_dir) for output_dir in self._output_dirs)

            if is_output:
                new_files.append(file_path)

        # Update tracked files
        self._tracked_files[sandbox_id] = known_files | set(new_files)

        return new_files

    def reset_sandbox(self, sandbox_id: str) -> None:
        """Reset file tracking for a sandbox."""
        if sandbox_id in self._tracked_files:
            del self._tracked_files[sandbox_id]
