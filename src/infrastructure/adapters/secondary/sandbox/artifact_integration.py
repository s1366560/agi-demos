"""Sandbox Artifact Integration - Detects and uploads artifacts from sandbox tool executions.

This module provides integration between the MCP sandbox and the artifact system,
automatically detecting new files produced by tool executions and uploading them.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set

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
        output_dirs: Optional[List[str]] = None,
        max_file_size: int = MAX_AUTO_UPLOAD_SIZE,
    ):
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
        self._known_files: Dict[str, Set[str]] = {}

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
        list_files_fn: Callable[[str], List[str]],
        read_file_fn: Callable[[str], bytes],
        project_id: str,
        tenant_id: str,
        tool_execution_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        source_tool: Optional[str] = None,
    ) -> List[str]:
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
        new_files: List[str] = []
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

    async def process_tool_result(
        self,
        sandbox_id: str,
        tool_name: str,
        tool_result: Dict[str, Any],
        call_tool_fn: Callable,
        project_id: str,
        tenant_id: str,
        tool_execution_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> List[str]:
        """
        Process a tool result and extract any artifacts.

        This method:
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

        Returns:
            List of artifact IDs created
        """
        # Tools that commonly produce output files
        output_producing_tools = {
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

        # Check if this tool might produce outputs
        tool_base = tool_name.split("_")[-1] if "_" in tool_name else tool_name
        if tool_base.lower() not in output_producing_tools:
            return []

        # Define functions to interact with sandbox
        async def list_files(directory: str) -> List[str]:
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

        async def read_file(path: str) -> Optional[bytes]:
            try:
                result = await call_tool_fn(
                    sandbox_id,
                    "read",
                    {"file_path": path},
                )
                if result.get("is_error"):
                    return None

                content = result.get("content", [])
                if not content:
                    return None

                text = content[0].get("text", "")
                return text.encode("utf-8")
            except Exception:
                return None

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

    def get_known_files(self, sandbox_id: str) -> Set[str]:
        """Get the set of known files for a sandbox."""
        return self._known_files.get(sandbox_id, set()).copy()


async def extract_artifacts_from_text(
    text: str,
    project_id: str,
    tenant_id: str,
    tool_execution_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
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
