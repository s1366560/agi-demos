"""Sandbox Artifact Integration - Detects and uploads artifacts from sandbox tool executions.

This module provides integration between the MCP sandbox and the artifact system,
automatically detecting new files produced by tool executions and uploading them.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any, ClassVar, cast

from src.application.services.artifact_service import ArtifactService
from src.domain.model.artifact.artifact import get_category_from_mime

logger = logging.getLogger(__name__)


# Output directories to monitor in sandbox
DEFAULT_OUTPUT_DIRS = [
    "/workspace/output",
    "/workspace/outputs",
    "/tmp/output",
    "/home/user/output",
    "/output",
]

# File patterns to ignore
IGNORED_PATTERNS = [
    "__pycache__",
    ".git",
    ".pyc",
    ".pyo",
    "node_modules",
    ".DS_Store",
    "Thumbs.db",
    ".pytest_cache",
    ".venv",
    ".env",
]

# Maximum file size to auto-upload (50MB)
MAX_AUTO_UPLOAD_SIZE = 50 * 1024 * 1024


class SandboxArtifactIntegration:
    """Integrates sandbox tool executions with artifact management.

    Tracks files in sandbox output directories and automatically uploads
    new files as artifacts when they are created.
    """

    def __init__(
        self,
        artifact_service: ArtifactService,
        output_dirs: list[str] | None = None,
        max_file_size: int = MAX_AUTO_UPLOAD_SIZE,
    ) -> None:
        """
        Initialize integration.

        Args:
            artifact_service: ArtifactService for creating artifacts
            output_dirs: Directories to monitor for outputs
            max_file_size: Maximum file size to auto-upload
        """
        self._artifact_service = artifact_service
        self._output_dirs = output_dirs or DEFAULT_OUTPUT_DIRS
        self._max_file_size = max_file_size

        # Track known files per sandbox to detect new ones
        # sandbox_id -> set of known file paths
        self._known_files: dict[str, set[str]] = {}

    def _should_ignore(self, path: str) -> bool:
        """Check if a file path should be ignored."""
        for pattern in IGNORED_PATTERNS:
            if pattern in path:
                return True
        return False

    def _is_in_output_dir(self, path: str) -> bool:
        """Check if a path is in a monitored output directory."""
        return any(path.startswith(d) for d in self._output_dirs)

    async def scan_for_new_artifacts(
        self,
        sandbox_id: str,
        list_files_fn: Callable[[str], list[str]],
        read_file_fn: Callable[[str], bytes | None],
        project_id: str,
        tenant_id: str,
        tool_execution_id: str | None = None,
        conversation_id: str | None = None,
        source_tool: str | None = None,
    ) -> list[str]:
        """
        Scan sandbox for new files and upload them as artifacts.

        Args:
            sandbox_id: Sandbox ID
            list_files_fn: Async function to list files in sandbox (dir -> List[path])
            read_file_fn: Async function to read file content (path -> bytes)
            project_id: Project ID
            tenant_id: Tenant ID
            tool_execution_id: Tool execution ID
            conversation_id: Conversation ID
            source_tool: Name of the tool that ran

        Returns:
            List of artifact IDs created
        """
        artifact_ids = []

        # Get known files for this sandbox
        known = self._known_files.get(sandbox_id, set())

        # Scan each output directory
        new_files: list[str] = []
        for output_dir in self._output_dirs:
            try:
                files = await asyncio.get_event_loop().run_in_executor(
                    None, list_files_fn, output_dir
                )
                for file_path in files:
                    full_path = (
                        f"{output_dir}/{file_path}" if not file_path.startswith("/") else file_path
                    )
                    if full_path not in known and not self._should_ignore(full_path):
                        new_files.append(full_path)
            except Exception as e:
                # Directory might not exist
                logger.debug(f"Could not scan {output_dir}: {e}")

        if not new_files:
            return artifact_ids

        # Upload new files as artifacts
        for file_path in new_files:
            try:
                # Read file content
                content = await asyncio.get_event_loop().run_in_executor(
                    None, read_file_fn, file_path
                )

                if content is None:
                    continue

                # Check file size
                if len(content) > self._max_file_size:
                    logger.warning(
                        f"Skipping large file {file_path} ({len(content)} bytes > {self._max_file_size})"
                    )
                    continue

                # Extract filename from path
                filename = file_path.split("/")[-1]

                # Create artifact
                artifact = await self._artifact_service.create_artifact(
                    file_content=content,
                    filename=filename,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    sandbox_id=sandbox_id,
                    tool_execution_id=tool_execution_id,
                    conversation_id=conversation_id,
                    source_tool=source_tool,
                    source_path=file_path,
                )

                artifact_ids.append(artifact.id)

                # Mark as known
                known.add(file_path)

                logger.info(
                    f"Created artifact {artifact.id} for {file_path} "
                    f"({artifact.category.value}, {len(content)} bytes)"
                )

            except Exception as e:
                logger.error(f"Failed to create artifact for {file_path}: {e}")

        # Update known files
        self._known_files[sandbox_id] = known

        return artifact_ids

    # Tools that commonly produce output files
    _OUTPUT_PRODUCING_TOOLS: ClassVar[set[str]] = {
        "bash",
        "python",
        "execute",
        "run",
        "screenshot",
        "render",
        "export",
        "save",
        "write",
        "generate",
    }

    @staticmethod
    async def _read_text_fallback(
        call_tool_fn: Callable[..., Any],
        sandbox_id: str,
        path: str,
    ) -> bytes | None:
        """Fallback: read file as text when export_artifact fails."""
        result = await call_tool_fn(sandbox_id, "read", {"file_path": path})
        if result.get("is_error") or result.get("isError"):
            return None
        content = result.get("content", [])
        if not content:
            return None
        text = content[0].get("text", "")
        return cast(bytes | None, text.encode("utf-8"))

    @staticmethod
    def _extract_base64_content(result: dict[str, Any]) -> bytes | None:
        """Extract base64-encoded content from export_artifact result."""
        import base64

        artifact_info = result.get("artifact", {})
        data = artifact_info.get("data")
        if data:
            return base64.b64decode(data)
        # Also check for image content
        for item in result.get("content", []):
            if item.get("type") == "image":
                return base64.b64decode(item.get("data", ""))
        return None

    @staticmethod
    def _extract_text_content(result: dict[str, Any]) -> bytes | None:
        """Extract text content from tool result."""
        content = result.get("content", [])
        if content:
            text = content[0].get("text", "")
            return cast(bytes | None, text.encode("utf-8"))
        return None

    async def _read_sandbox_file(
        self,
        call_tool_fn: Callable[..., Any],
        sandbox_id: str,
        path: str,
    ) -> bytes | None:
        """Read file from sandbox using export_artifact with text fallback."""
        try:
            result = await call_tool_fn(
                sandbox_id,
                "export_artifact",
                {"file_path": path, "encoding": "auto"},
            )
            if result.get("is_error") or result.get("isError"):
                return await self._read_text_fallback(call_tool_fn, sandbox_id, path)
                # Check for base64 encoded data
            encoding = result.get("artifact", {}).get("encoding", "utf-8")
            if encoding == "base64":
                return self._extract_base64_content(result)

            return self._extract_text_content(result)
        except Exception as e:
            logger.debug(f"Failed to read file {path}: {e}")
            return None

    async def _list_sandbox_files(
        self,
        call_tool_fn: Callable[..., Any],
        sandbox_id: str,
        directory: str,
    ) -> list[str]:
        """List files in a sandbox directory via MCP glob tool."""
        try:
            result = await call_tool_fn(
                sandbox_id,
                "glob",
                {"pattern": "**/*", "path": directory},
            )
            if result.get("is_error"):
                return []
            content = result.get("content", [])
            if not content:
                return []
            files_text = content[0].get("text", "")
            return [f.strip() for f in files_text.split("\n") if f.strip()]
        except Exception:
            return []

    async def process_tool_result(
        self,
        sandbox_id: str,
        tool_name: str,
        tool_result: dict[str, Any],
        call_tool_fn: Callable[..., Any],
        project_id: str,
        tenant_id: str,
        tool_execution_id: str | None = None,
        conversation_id: str | None = None,
    ) -> list[str]:
        """
        Process a tool result and extract any artifacts.
        1. Checks if the tool might have produced output files
        2. Scans output directories for new files
        3. Uploads new files as artifacts
        Args:
            sandbox_id: Sandbox ID
            tool_name: Name of the tool that was called
            tool_result: Result from the tool call
            call_tool_fn: Function to call MCP tools (for glob/read)
            project_id: Project ID
            tenant_id: Tenant ID
            tool_execution_id: Tool execution ID
            conversation_id: Conversation ID
            List of artifact IDs created
        """
        # Check if this tool might produce outputs
        tool_base = tool_name.split("_")[-1] if "_" in tool_name else tool_name
        if tool_base.lower() not in self._OUTPUT_PRODUCING_TOOLS:
            return []

        # Build closures bound to this call
        async def list_files(directory: str) -> list[str]:
            return await self._list_sandbox_files(call_tool_fn, sandbox_id, directory)

        async def read_file(path: str) -> bytes | None:
            return await self._read_sandbox_file(call_tool_fn, sandbox_id, path)

        # Scan for new artifacts
        return await self.scan_for_new_artifacts(
            sandbox_id=sandbox_id,
            list_files_fn=list_files,
            read_file_fn=read_file,
            project_id=project_id,
            tenant_id=tenant_id,
            tool_execution_id=tool_execution_id,
            conversation_id=conversation_id,
            source_tool=tool_name,
        )

    def reset_sandbox(self, sandbox_id: str) -> None:
        """Reset file tracking for a sandbox (call when sandbox is terminated)."""
        if sandbox_id in self._known_files:
            del self._known_files[sandbox_id]

    def get_known_files(self, sandbox_id: str) -> set[str]:
        """Get the set of known files for a sandbox."""
        return self._known_files.get(sandbox_id, set()).copy()


async def extract_artifacts_from_text(
    text: str,
    project_id: str,
    tenant_id: str,
    tool_execution_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extract embedded artifacts from tool output text.

    Some tools return base64-encoded images or other data inline.
    This function detects and extracts them.

    Args:
        text: Tool output text
        project_id: Project ID
        tenant_id: Tenant ID
        tool_execution_id: Tool execution ID

    Returns:
        List of detected embedded artifacts (not yet uploaded)
    """
    import base64
    import re

    artifacts = []

    # Pattern for base64 data URLs (e.g., data:image/png;base64,...)
    data_url_pattern = r"data:([a-zA-Z0-9]+/[a-zA-Z0-9\-+.]+);base64,([A-Za-z0-9+/=]+)"

    for match in re.finditer(data_url_pattern, text):
        mime_type = match.group(1)
        base64_data = match.group(2)

        try:
            content = base64.b64decode(base64_data)
            category = get_category_from_mime(mime_type)

            # Generate filename based on mime type
            ext_map = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/svg+xml": ".svg",
            }
            ext = ext_map.get(mime_type, "")

            artifacts.append(
                {
                    "content": content,
                    "mime_type": mime_type,
                    "category": category.value,
                    "filename": f"embedded_{len(artifacts)}{ext}",
                    "size_bytes": len(content),
                    "source": "embedded_data_url",
                }
            )

        except Exception as e:
            logger.warning(f"Failed to decode embedded data: {e}")

    return artifacts


def extract_artifacts_from_mcp_result(
    result: dict[str, Any],
    tool_name: str,
) -> list[dict[str, Any]]:
    """
    Extract artifacts from MCP tool result content.

    MCP tools can return multiple content types including images.
    This function extracts image and other rich content as artifacts.

    Args:
        result: MCP tool result with 'content' array
        tool_name: Name of the tool that produced the result

    Returns:
        List of artifact data dicts with keys:
            - content: bytes
            - mime_type: str
            - category: str
            - filename: str
            - size_bytes: int
            - source: str (tool name)
    """
    import base64

    artifacts = []
    content_items = result.get("content", [])

    if not content_items:
        return artifacts

    counter = 0
    for item in content_items:
        item_type = item.get("type", "")

        if item_type == "image":
            # MCP image content: {"type": "image", "data": "base64...", "mimeType": "image/png"}
            base64_data = item.get("data", "")
            mime_type = item.get("mimeType", "image/png")

            if base64_data:
                try:
                    content = base64.b64decode(base64_data)
                    category = get_category_from_mime(mime_type)

                    # Generate filename based on mime type
                    ext_map = {
                        "image/png": ".png",
                        "image/jpeg": ".jpg",
                        "image/gif": ".gif",
                        "image/webp": ".webp",
                        "image/svg+xml": ".svg",
                        "image/bmp": ".bmp",
                    }
                    ext = ext_map.get(mime_type, ".bin")

                    artifacts.append(
                        {
                            "content": content,
                            "mime_type": mime_type,
                            "category": category.value,
                            "filename": f"{tool_name}_output_{counter}{ext}",
                            "size_bytes": len(content),
                            "source": tool_name,
                        }
                    )
                    counter += 1

                except Exception as e:
                    logger.warning(f"Failed to decode MCP image content: {e}")

        elif item_type == "resource":
            # MCP resource content (file references)
            uri = item.get("uri", "")
            mime_type = item.get("mimeType", "application/octet-stream")
            blob = item.get("blob")  # Optional base64 blob

            if blob:
                try:
                    content = base64.b64decode(blob)
                    category = get_category_from_mime(mime_type)

                    # Extract filename from URI
                    filename = uri.split("/")[-1] if uri else f"{tool_name}_resource_{counter}"

                    artifacts.append(
                        {
                            "content": content,
                            "mime_type": mime_type,
                            "category": category.value,
                            "filename": filename,
                            "size_bytes": len(content),
                            "source": tool_name,
                            "source_path": uri,
                        }
                    )
                    counter += 1

                except Exception as e:
                    logger.warning(f"Failed to decode MCP resource blob: {e}")

    return artifacts
