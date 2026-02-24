"""
Artifact Extractor - Extract and upload artifacts from tool results.

This module provides centralized artifact extraction logic, extracted from
SessionProcessor to support the Single Responsibility Principle.

Handles:
- Extracting image/resource content from MCP-style results
- Processing export_artifact tool outputs
- Uploading artifacts to storage via ArtifactService
- Generating artifact events for frontend display

Reference: Extracted from processor.py::_process_tool_artifacts() (lines 1258-1459)
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from src.domain.events.agent_events import AgentArtifactCreatedEvent

logger = logging.getLogger(__name__)


# ============================================================
# Data Classes
# ============================================================


@dataclass
class ExtractionContext:
    """
    Context information required for artifact extraction.

    Attributes:
        project_id: Project identifier for storage
        tenant_id: Tenant identifier for multi-tenancy
        conversation_id: Optional conversation identifier
        sandbox_id: Optional sandbox identifier
    """

    project_id: str
    tenant_id: str
    conversation_id: str | None = None
    sandbox_id: str | None = None

    @property
    def is_valid(self) -> bool:
        """Check if context has required fields."""
        return bool(self.project_id and self.tenant_id)


@dataclass
class ArtifactData:
    """
    Extracted artifact data ready for upload.

    Attributes:
        content: Binary content of the artifact
        filename: Name for the artifact file
        mime_type: MIME type of the content
        category: Category classification (image, document, etc.)
        size_bytes: Size of content in bytes
        source_tool: Name of tool that produced this artifact
        source_path: Original path if applicable
        metadata: Additional metadata
    """

    content: bytes
    filename: str
    mime_type: str
    category: str = "other"
    size_bytes: int = 0
    source_tool: str = ""
    source_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Calculate size if not provided."""
        if self.size_bytes == 0 and self.content:
            self.size_bytes = len(self.content)


@dataclass
class ArtifactExtractionResult:
    """
    Result of artifact extraction from a tool result.

    Attributes:
        artifacts: List of extracted ArtifactData objects
        errors: List of error messages encountered
        has_artifacts: Whether any artifacts were extracted
    """

    artifacts: list[ArtifactData] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_artifacts(self) -> bool:
        """Check if any artifacts were extracted."""
        return len(self.artifacts) > 0


# ============================================================
# Protocols for Dependencies
# ============================================================


class ArtifactServiceLike(Protocol):
    """Protocol for artifact service to avoid circular imports."""

    async def create_artifact(
        self,
        file_content: bytes,
        filename: str,
        project_id: str,
        tenant_id: str,
        sandbox_id: str | None = None,
        tool_execution_id: str | None = None,
        conversation_id: str | None = None,
        source_tool: str | None = None,
        source_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactLike:
        """Create and store an artifact."""
        ...


class ArtifactLike(Protocol):
    """Protocol for artifact objects returned by ArtifactService."""

    @property
    def id(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def mime_type(self) -> str: ...

    @property
    def category(self) -> str: ...

    @property
    def size_bytes(self) -> int: ...

    @property
    def url(self) -> str | None: ...

    @property
    def preview_url(self) -> str | None: ...


# ============================================================
# Artifact Extractor
# ============================================================


class ArtifactExtractor:
    """
    Extracts and uploads artifacts from tool execution results.

    Handles different artifact formats including:
    - MCP-style content arrays with images/resources
    - export_artifact tool special format
    - Direct file content

    Usage:
        extractor = ArtifactExtractor(artifact_service)

        context = ExtractionContext(
            project_id="proj-123",
            tenant_id="tenant-456"
        )

        async for event in extractor.process(
            tool_name="screenshot",
            result={"content": [{"type": "image", "data": "..."}]},
            context=context,
            tool_execution_id="exec-789"
        ):
            yield event  # AgentArtifactCreatedEvent
    """

    # MIME type to extension mapping
    MIME_TO_EXT: ClassVar[dict[str, str]] = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/html": ".html",
        "application/json": ".json",
    }

    def __init__(
        self,
        artifact_service: ArtifactServiceLike | None = None,
        debug_logging: bool = False,
    ) -> None:
        """
        Initialize the artifact extractor.

        Args:
            artifact_service: Service for storing artifacts
            debug_logging: Whether to enable debug logging
        """
        self._artifact_service = artifact_service
        self._debug_logging = debug_logging

    def set_artifact_service(self, service: ArtifactServiceLike) -> None:
        """Set or update the artifact service."""
        self._artifact_service = service

    async def process(
        self,
        tool_name: str,
        result: Any,
        context: ExtractionContext,
        tool_execution_id: str | None = None,
    ) -> AsyncIterator[AgentArtifactCreatedEvent]:
        """
        Process tool result and extract/upload any artifacts.

        Args:
            tool_name: Name of the tool that produced the result
            result: Tool execution result (may contain images/resources)
            context: Extraction context with project/tenant info
            tool_execution_id: ID of the tool execution

        Yields:
            AgentArtifactCreatedEvent for each artifact created
        """
        if self._debug_logging:
            logger.info(
                f"[ArtifactExtractor] Processing tool_name={tool_name}, "
                f"has_service={self._artifact_service is not None}, "
                f"result_type={type(result).__name__}"
            )

        # Validate prerequisites
        if not self._artifact_service:
            logger.warning("[ArtifactExtractor] No artifact_service configured, skipping")
            return

        if not context.is_valid:
            logger.warning(
                f"[ArtifactExtractor] Missing context: project_id={context.project_id}, "
                f"tenant_id={context.tenant_id}"
            )
            return

        if not isinstance(result, dict):
            if self._debug_logging:
                logger.info(
                    f"[ArtifactExtractor] Result is not dict, type={type(result)}, skipping"
                )
            return

        # Extract artifacts from result
        extraction_result = self._extract_from_result(result, tool_name)

        if not extraction_result.has_artifacts:
            return

        # Upload each artifact and emit events
        for artifact_data in extraction_result.artifacts:
            try:
                artifact = await self._upload_artifact(artifact_data, context, tool_execution_id)

                if artifact:
                    logger.info(
                        f"[ArtifactExtractor] Created artifact {artifact.id}: "
                        f"{artifact.filename} ({artifact.category.value}, {artifact.size_bytes} bytes)"  # type: ignore[attr-defined]
                    )

                    yield AgentArtifactCreatedEvent(
                        artifact_id=artifact.id,
                        filename=artifact.filename,
                        mime_type=artifact.mime_type,
                        category=artifact.category.value,  # type: ignore[attr-defined]
                        size_bytes=artifact.size_bytes,
                        url=artifact.url,
                        preview_url=artifact.preview_url,
                        tool_execution_id=tool_execution_id,
                        source_tool=tool_name,
                    )

            except Exception as e:
                logger.error(f"[ArtifactExtractor] Failed to create artifact from {tool_name}: {e}")

    def _extract_from_result(
        self, result: dict[str, Any], tool_name: str
    ) -> ArtifactExtractionResult:
        """
        Extract artifact data from tool result.

        Args:
            result: Tool execution result dict
            tool_name: Name of the tool

        Returns:
            ArtifactExtractionResult with extracted artifacts
        """
        extraction = ArtifactExtractionResult()

        # Check for export_artifact special format
        if result.get("artifact"):
            artifact_data = self._extract_from_export_artifact(result, tool_name, extraction)
            if artifact_data:
                extraction.artifacts.append(artifact_data)
                return extraction  # export_artifact is exclusive

        # Check for MCP content array
        content = result.get("content", [])
        if not content:
            return extraction

        # Check for rich content types
        has_rich_content = any(
            item.get("type") in ("image", "resource") for item in content if isinstance(item, dict)
        )

        if not has_rich_content:
            return extraction

        # Extract from MCP content
        self._extract_from_mcp_content(content, tool_name, extraction)

        return extraction

    def _extract_from_export_artifact(
        self,
        result: dict[str, Any],
        tool_name: str,
        extraction: ArtifactExtractionResult,
    ) -> ArtifactData | None:
        """
        Extract artifact from export_artifact tool format.

        Args:
            result: Result containing 'artifact' field
            tool_name: Tool name
            extraction: Extraction result to add errors to

        Returns:
            ArtifactData if extraction successful, None otherwise
        """
        artifact_info = result["artifact"]

        try:
            encoding = artifact_info.get("encoding", "utf-8")

            if encoding == "base64":
                # Binary file
                data = artifact_info.get("data")
                if not data:
                    # Check for image content
                    for item in result.get("content", []):
                        if item.get("type") == "image":
                            data = item.get("data")
                            break

                if not data:
                    extraction.errors.append("export_artifact has base64 encoding but no data")
                    return None

                file_content = base64.b64decode(data)

            else:
                # Text file
                content = result.get("content", [])
                if not content:
                    extraction.errors.append("export_artifact returned no content")
                    return None

                first_item = content[0] if content else {}
                text = (
                    first_item.get("text", "") if isinstance(first_item, dict) else str(first_item)
                )

                if not text:
                    extraction.errors.append("export_artifact returned empty text content")
                    return None

                file_content = text.encode("utf-8")

            return ArtifactData(
                content=file_content,
                filename=artifact_info.get("filename", "exported_file"),
                mime_type=artifact_info.get("mime_type", "application/octet-stream"),
                category=artifact_info.get("category", "other"),
                source_tool=tool_name,
                source_path=artifact_info.get("path"),
                metadata={
                    "extracted_from": "export_artifact",
                    "is_binary": artifact_info.get("is_binary"),
                },
            )

        except Exception as e:
            extraction.errors.append(f"Failed to process export_artifact: {e}")
            logger.error(
                f"[ArtifactExtractor] Failed to process export_artifact: {e}\n"
                f"Artifact info: {artifact_info}"
            )
            return None

    def _extract_from_mcp_content(
        self,
        content: list[dict[str, Any]],
        tool_name: str,
        extraction: ArtifactExtractionResult,
    ) -> None:
        """
        Extract artifacts from MCP content array.

        Args:
            content: MCP content array
            tool_name: Tool name
            extraction: Extraction result to populate
        """
        counter = 0

        for item in content:
            if not isinstance(item, dict):
                continue  # type: ignore[unreachable]

            item_type = item.get("type", "")

            if item_type == "image":
                artifact = self._extract_image_content(item, tool_name, counter)
                if artifact:
                    extraction.artifacts.append(artifact)
                    counter += 1

            elif item_type == "resource":
                artifact = self._extract_resource_content(item, tool_name, counter)
                if artifact:
                    extraction.artifacts.append(artifact)
                    counter += 1

    def _extract_image_content(
        self,
        item: dict[str, Any],
        tool_name: str,
        counter: int,
    ) -> ArtifactData | None:
        """
        Extract artifact from MCP image content.

        Args:
            item: MCP content item with type="image"
            tool_name: Tool name
            counter: Counter for unique filenames

        Returns:
            ArtifactData if extraction successful
        """
        base64_data = item.get("data", "")
        mime_type = item.get("mimeType", "image/png")

        if not base64_data:
            return None

        try:
            content = base64.b64decode(base64_data)
            ext = self.MIME_TO_EXT.get(mime_type, ".bin")

            return ArtifactData(
                content=content,
                filename=f"{tool_name}_output_{counter}{ext}",
                mime_type=mime_type,
                category=self._get_category_from_mime(mime_type),
                source_tool=tool_name,
                metadata={"extracted_from": "mcp_image"},
            )

        except Exception as e:
            logger.warning(f"[ArtifactExtractor] Failed to decode MCP image: {e}")
            return None

    def _extract_resource_content(
        self,
        item: dict[str, Any],
        tool_name: str,
        counter: int,
    ) -> ArtifactData | None:
        """
        Extract artifact from MCP resource content.

        Args:
            item: MCP content item with type="resource"
            tool_name: Tool name
            counter: Counter for unique filenames

        Returns:
            ArtifactData if extraction successful
        """
        uri = item.get("uri", "")
        blob = item.get("blob")
        text = item.get("text")
        mime_type = item.get("mimeType", "application/octet-stream")

        if blob:
            try:
                content = base64.b64decode(blob)
            except Exception as e:
                logger.warning(f"[ArtifactExtractor] Failed to decode resource blob: {e}")
                return None
        elif text:
            content = text.encode("utf-8")
        else:
            return None

        # Extract filename from URI or generate one
        filename = uri.rsplit("/", 1)[-1] if uri else f"{tool_name}_resource_{counter}"
        if not filename or filename == uri:
            ext = self.MIME_TO_EXT.get(mime_type, "")
            filename = f"{tool_name}_resource_{counter}{ext}"

        return ArtifactData(
            content=content,
            filename=filename,
            mime_type=mime_type,
            category=self._get_category_from_mime(mime_type),
            source_tool=tool_name,
            source_path=uri,
            metadata={"extracted_from": "mcp_resource"},
        )

    def _get_category_from_mime(self, mime_type: str) -> str:
        """
        Determine artifact category from MIME type.

        Args:
            mime_type: MIME type string

        Returns:
            Category string
        """
        if mime_type.startswith("image/"):
            return "image"
        elif mime_type.startswith("video/"):
            return "video"
        elif mime_type.startswith("audio/"):
            return "audio"
        elif mime_type in ("application/pdf", "text/plain", "text/html", "text/markdown"):
            return "document"
        elif mime_type.startswith("text/"):
            return "code"
        else:
            return "other"

    async def _upload_artifact(
        self,
        artifact_data: ArtifactData,
        context: ExtractionContext,
        tool_execution_id: str | None,
    ) -> ArtifactLike | None:
        """
        Upload artifact to storage service.

        Args:
            artifact_data: Extracted artifact data
            context: Extraction context
            tool_execution_id: Tool execution ID

        Returns:
            Created artifact object or None on failure
        """
        if not self._artifact_service:
            return None

        return await self._artifact_service.create_artifact(
            file_content=artifact_data.content,
            filename=artifact_data.filename,
            project_id=context.project_id,
            tenant_id=context.tenant_id,
            sandbox_id=context.sandbox_id,
            tool_execution_id=tool_execution_id,
            conversation_id=context.conversation_id,
            source_tool=artifact_data.source_tool,
            source_path=artifact_data.source_path,
            metadata=artifact_data.metadata,
        )

    def extract_only(self, result: Any, tool_name: str) -> ArtifactExtractionResult:
        """
        Extract artifacts without uploading (for testing or preview).

        Args:
            result: Tool execution result
            tool_name: Tool name

        Returns:
            ArtifactExtractionResult with extracted data
        """
        if not isinstance(result, dict):
            return ArtifactExtractionResult()

        return self._extract_from_result(result, tool_name)


# ============================================================
# Module-level Singleton
# ============================================================

_default_extractor: ArtifactExtractor | None = None


def get_artifact_extractor() -> ArtifactExtractor:
    """Get the default artifact extractor singleton."""
    global _default_extractor
    if _default_extractor is None:
        _default_extractor = ArtifactExtractor()
    return _default_extractor


def set_artifact_extractor(extractor: ArtifactExtractor) -> None:
    """Set the default artifact extractor singleton."""
    global _default_extractor
    _default_extractor = extractor
