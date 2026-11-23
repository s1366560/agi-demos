"""Import file tool for MCP server.

Provides functionality to import files (typically from user uploads)
into the sandbox workspace for processing by other tools.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)

# Default input directory for imported files
DEFAULT_INPUT_DIR = "/workspace/input"


def _resolve_and_validate_path(
    filename: str,
    destination: str,
    workspace_dir: str = "/workspace",
) -> Path:
    """
    Resolve and validate the target path for file import.

    Ensures the path is safe (no path traversal) and within workspace.

    Args:
        filename: Name of the file to create
        destination: Destination directory
        workspace_dir: Workspace root directory

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If path is invalid or escapes workspace
    """
    workspace = Path(workspace_dir).resolve()

    # Resolve destination directory
    if os.path.isabs(destination):
        dest_dir = Path(destination).resolve()
    else:
        dest_dir = (workspace / destination).resolve()

    # Security check: destination must be within workspace
    try:
        dest_dir.relative_to(workspace)
    except ValueError:
        raise ValueError(f"Destination '{destination}' is outside workspace directory")

    # Construct file path
    file_path = dest_dir / filename

    # Security check: final path must be within destination
    # (prevents path traversal via filename like "../../../etc/passwd")
    try:
        file_path.resolve().relative_to(dest_dir)
    except ValueError:
        raise ValueError(f"Invalid filename: path traversal detected in '{filename}'")

    return file_path.resolve()


async def import_file(
    filename: str,
    content_base64: str,
    destination: str = DEFAULT_INPUT_DIR,
    overwrite: bool = True,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Import a file into the sandbox workspace.

    This tool is used to import files uploaded by users into the sandbox
    for processing by other tools (code execution, data analysis, etc.).

    The file content is provided as base64-encoded data and written to
    the specified destination directory.

    Args:
        filename: Name of the file to create
        content_base64: Base64-encoded file content
        destination: Destination directory (default: /workspace/input)
        overwrite: Whether to overwrite existing file (default: True)
        _workspace_dir: Workspace root (injected by server)

    Returns:
        Dict with:
        - success: Whether import succeeded
        - path: Absolute path where file was written
        - size_bytes: Size of the written file
        - message: Human-readable status message
        - error: Error message (if failed)

    Example:
        >>> # Import a CSV file for data analysis
        >>> result = await import_file(
        ...     filename="data.csv",
        ...     content_base64="Y29sLGRhdGEKMSwx",
        ...     destination="/workspace/input"
        ... )
        >>> # result: {"success": True, "path": "/workspace/input/data.csv", ...}
    """
    try:
        # Validate inputs
        if not filename:
            return {
                "success": False,
                "error": "Filename cannot be empty",
            }

        if not content_base64:
            return {
                "success": False,
                "error": "Content cannot be empty",
            }

        # Resolve and validate path
        try:
            file_path = _resolve_and_validate_path(filename, destination, _workspace_dir)
        except ValueError as e:
            return {
                "success": False,
                "error": str(e),
            }

        # Check if file exists and overwrite is disabled
        if file_path.exists() and not overwrite:
            return {
                "success": False,
                "error": f"File already exists: {file_path}",
                "path": str(file_path),
            }

        # Decode base64 content
        try:
            content = base64.b64decode(content_base64)
        except Exception as e:
            return {
                "success": False,
                "error": f"Invalid base64 content: {e}",
            }

        # Log content info for debugging
        import hashlib

        content_md5 = hashlib.md5(content).hexdigest()
        logger.info(
            f"[import_file] Decoded content: size={len(content)}, "
            f"md5={content_md5}, header={content[:16].hex() if len(content) >= 16 else content.hex()}"
        )

        # Create destination directory if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        file_path.write_bytes(content)

        # Verify written file
        written_content = file_path.read_bytes()
        written_md5 = hashlib.md5(written_content).hexdigest()

        if written_md5 != content_md5:
            logger.error(
                f"[import_file] File integrity check FAILED! "
                f"Expected MD5={content_md5}, Got MD5={written_md5}"
            )
            return {
                "success": False,
                "error": "File integrity check failed after write",
                "expected_md5": content_md5,
                "actual_md5": written_md5,
            }

        logger.info(
            f"[import_file] Successfully imported: {file_path} "
            f"({len(content)} bytes, md5={content_md5})"
        )

        return {
            "success": True,
            "path": str(file_path),
            "size_bytes": len(content),
            "md5": content_md5,
            "message": f"File imported successfully to {file_path}",
        }

    except Exception as e:
        logger.error(f"Failed to import file '{filename}': {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Failed to import file: {e}",
        }


async def import_files_batch(
    files: list,
    destination: str = DEFAULT_INPUT_DIR,
    overwrite: bool = True,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Import multiple files into the sandbox workspace.

    More efficient than calling import_file multiple times.

    Args:
        files: List of dicts with 'filename' and 'content_base64'
        destination: Destination directory for all files
        overwrite: Whether to overwrite existing files
        _workspace_dir: Workspace root (injected by server)

    Returns:
        Dict with:
        - success: Whether all imports succeeded
        - imported: List of successfully imported files
        - failed: List of failed imports with error messages
        - total_bytes: Total bytes written

    Example:
        >>> result = await import_files_batch(
        ...     files=[
        ...         {"filename": "data.csv", "content_base64": "..."},
        ...         {"filename": "config.json", "content_base64": "..."},
        ...     ]
        ... )
    """
    imported = []
    failed = []
    total_bytes = 0

    for file_info in files:
        filename = file_info.get("filename")
        content_base64 = file_info.get("content_base64")

        if not filename or not content_base64:
            failed.append(
                {
                    "filename": filename or "unknown",
                    "error": "Missing filename or content",
                }
            )
            continue

        result = await import_file(
            filename=filename,
            content_base64=content_base64,
            destination=destination,
            overwrite=overwrite,
            _workspace_dir=_workspace_dir,
        )

        if result["success"]:
            imported.append(
                {
                    "filename": filename,
                    "path": result["path"],
                    "size_bytes": result["size_bytes"],
                }
            )
            total_bytes += result["size_bytes"]
        else:
            failed.append(
                {
                    "filename": filename,
                    "error": result.get("error", "Unknown error"),
                }
            )

    return {
        "success": len(failed) == 0,
        "imported": imported,
        "failed": failed,
        "total_bytes": total_bytes,
        "message": f"Imported {len(imported)} file(s), {len(failed)} failed",
    }


# =============================================================================
# TOOL CREATORS
# =============================================================================


def create_import_file_tool() -> MCPTool:
    """Create the import_file tool."""
    return MCPTool(
        name="import_file",
        description=(
            "Import a file into the sandbox workspace. "
            "Use this to import files uploaded by the user for processing. "
            "The file content should be provided as base64-encoded data. "
            "Files are written to /workspace/input by default."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the file to create (e.g., 'data.csv')",
                },
                "content_base64": {
                    "type": "string",
                    "description": "Base64-encoded file content",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination directory (default: /workspace/input)",
                    "default": "/workspace/input",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite if file exists (default: true)",
                    "default": True,
                },
            },
            "required": ["filename", "content_base64"],
        },
        handler=import_file,
    )


def create_import_files_batch_tool() -> MCPTool:
    """Create the import_files_batch tool."""
    return MCPTool(
        name="import_files_batch",
        description=(
            "Import multiple files into the sandbox workspace in a single call. "
            "More efficient than calling import_file multiple times."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": "Name of the file",
                            },
                            "content_base64": {
                                "type": "string",
                                "description": "Base64-encoded content",
                            },
                        },
                        "required": ["filename", "content_base64"],
                    },
                    "description": "List of files to import",
                },
                "destination": {
                    "type": "string",
                    "description": "Destination directory for all files",
                    "default": "/workspace/input",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite existing files",
                    "default": True,
                },
            },
            "required": ["files"],
        },
        handler=import_files_batch,
    )
