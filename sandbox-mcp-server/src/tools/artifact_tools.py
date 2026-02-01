"""Artifact export tools for MCP server.

Provides tools for reading and exporting files as artifacts with proper
encoding and MIME type detection, supporting both text and binary files.
"""

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)

# Initialize mimetypes with common extensions
mimetypes.init()

# Add custom MIME types not in standard library
CUSTOM_MIME_TYPES = {
    ".md": "text/markdown",
    ".tsx": "text/typescript-jsx",
    ".jsx": "text/javascript-jsx",
    ".vue": "text/vue",
    ".svelte": "text/svelte",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".toml": "application/toml",
    ".rs": "text/rust",
    ".go": "text/go",
    ".kt": "text/kotlin",
    ".swift": "text/swift",
    ".sql": "application/sql",
    ".graphql": "application/graphql",
    ".proto": "text/protobuf",
    ".dockerfile": "text/dockerfile",
    ".env": "text/plain",
    ".gitignore": "text/plain",
    ".editorconfig": "text/plain",
}

# Binary file extensions (always base64 encode)
BINARY_EXTENSIONS = {
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
    ".avif",
    ".raw",
    ".psd",
    ".ai",
    ".eps",
    # Documents
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".rar",
    ".xz",
    ".lz",
    ".lzma",
    # Audio
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".aac",
    ".m4a",
    ".wma",
    ".opus",
    ".mid",
    ".midi",
    # Video
    ".mp4",
    ".webm",
    ".avi",
    ".mkv",
    ".mov",
    ".wmv",
    ".flv",
    ".m4v",
    ".mpeg",
    ".mpg",
    # Database
    ".db",
    ".sqlite",
    ".sqlite3",
    ".mdb",
    ".accdb",
    # Executables & Libraries
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".wasm",
    ".class",
    ".jar",
    ".war",
    # Fonts
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".eot",
    # 3D Models
    ".obj",
    ".stl",
    ".fbx",
    ".gltf",
    ".glb",
    # Other binary
    ".bin",
    ".dat",
    ".pickle",
    ".pkl",
    ".npy",
    ".npz",
    ".h5",
    ".hdf5",
    ".parquet",
    ".feather",
    ".arrow",
}

# Text file extensions (read as text, optionally base64)
TEXT_EXTENSIONS = {
    # Code
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".bat",
    ".cmd",
    ".lua",
    ".r",
    ".R",
    ".jl",
    ".ex",
    ".exs",
    ".erl",
    ".hrl",
    ".clj",
    ".cljs",
    ".hs",
    ".ml",
    ".fs",
    ".v",
    ".sv",
    ".vhdl",
    ".vhd",
    ".asm",
    ".s",
    ".m",
    ".mm",
    # Data
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".conf",
    ".cfg",
    ".properties",
    ".plist",
    # Documents
    ".md",
    ".txt",
    ".rst",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".csv",
    ".tsv",
    ".log",
    ".tex",
    ".bib",
    # Config
    ".gitignore",
    ".dockerignore",
    ".editorconfig",
    ".prettierrc",
    ".eslintrc",
    ".babelrc",
    ".npmrc",
    ".yarnrc",
    # Web
    ".svg",
    ".vue",
    ".svelte",
    ".astro",
}

# Maximum file size for export (100MB)
MAX_EXPORT_SIZE = 100 * 1024 * 1024

# Threshold for auto-base64 encoding text files (files larger than this are always base64)
AUTO_BASE64_THRESHOLD = 1 * 1024 * 1024  # 1MB


def _resolve_path(path: str, workspace_dir: str) -> Path:
    """
    Resolve a path relative to workspace directory.

    Args:
        path: User-provided path
        workspace_dir: Workspace root directory

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If path escapes workspace
    """
    workspace = Path(workspace_dir).resolve()

    # Handle absolute paths
    if os.path.isabs(path):
        resolved = Path(path).resolve()
    else:
        resolved = (workspace / path).resolve()

    # Security check: ensure path is within workspace
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError(f"Path '{path}' is outside workspace directory")

    return resolved


def _get_mime_type(file_path: Path) -> str:
    """
    Get MIME type for a file.

    Args:
        file_path: Path to the file

    Returns:
        MIME type string
    """
    suffix = file_path.suffix.lower()

    # Check custom MIME types first
    if suffix in CUSTOM_MIME_TYPES:
        return CUSTOM_MIME_TYPES[suffix]

    # Use mimetypes library
    mime_type, _ = mimetypes.guess_type(str(file_path))

    if mime_type:
        return mime_type

    # Default based on extension category
    if suffix in BINARY_EXTENSIONS:
        return "application/octet-stream"

    return "text/plain"


def _is_binary_file(file_path: Path) -> bool:
    """
    Determine if a file should be treated as binary.

    Args:
        file_path: Path to the file

    Returns:
        True if file should be treated as binary
    """
    suffix = file_path.suffix.lower()

    # Check explicit binary extensions
    if suffix in BINARY_EXTENSIONS:
        return True

    # Check explicit text extensions
    if suffix in TEXT_EXTENSIONS:
        return False

    # For unknown extensions, try to detect
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            # Check for null bytes (common in binary files)
            if b"\x00" in chunk:
                return True
            # Try to decode as UTF-8
            try:
                chunk.decode("utf-8")
                return False
            except UnicodeDecodeError:
                return True
    except Exception:
        # Default to binary for safety
        return True


def _get_artifact_category(mime_type: str, suffix: str) -> str:
    """
    Determine artifact category from MIME type.

    Args:
        mime_type: MIME type string
        suffix: File extension

    Returns:
        Category string
    """
    if mime_type.startswith("image/"):
        return "image"
    elif mime_type.startswith("video/"):
        return "video"
    elif mime_type.startswith("audio/"):
        return "audio"
    elif mime_type == "application/pdf":
        return "document"
    elif mime_type in ("application/json", "application/xml", "text/csv"):
        return "data"
    elif suffix in (
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
    ):
        return "code"
    elif suffix in (".md", ".txt", ".rst", ".html"):
        return "text"
    elif suffix in (".zip", ".tar", ".gz", ".7z", ".rar"):
        return "archive"
    else:
        return "file"


async def export_artifact(
    file_path: str,
    encoding: str = "auto",
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Export a file as an artifact with proper encoding and metadata.

    This tool reads any file type (text or binary) and returns it with:
    - Proper MIME type detection
    - Base64 encoding for binary files
    - File metadata (size, type, category)

    Args:
        file_path: Path to the file to export
        encoding: Encoding mode: "auto" (detect), "base64" (force), "text" (force text)
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Dict with file content, encoding, and metadata
    """
    try:
        resolved = _resolve_path(file_path, _workspace_dir)

        if not resolved.exists():
            return {
                "content": [{"type": "text", "text": f"Error: File not found: {file_path}"}],
                "isError": True,
                "errorCode": "FILE_NOT_FOUND",
                "errorDetails": {"file_path": file_path},
            }

        if not resolved.is_file():
            return {
                "content": [{"type": "text", "text": f"Error: Not a file: {file_path}"}],
                "isError": True,
                "errorCode": "NOT_A_FILE",
                "errorDetails": {"file_path": file_path},
            }

        # Get file stats
        try:
            stats = resolved.stat()
        except PermissionError:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: Permission denied accessing file: {file_path}",
                    }
                ],
                "isError": True,
                "errorCode": "PERMISSION_DENIED",
                "errorDetails": {"file_path": file_path},
            }

        file_size = stats.st_size

        # Check size limit
        if file_size > MAX_EXPORT_SIZE:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: File too large ({file_size} bytes > {MAX_EXPORT_SIZE} bytes limit)",
                    }
                ],
                "isError": True,
                "errorCode": "FILE_TOO_LARGE",
                "errorDetails": {
                    "file_path": file_path,
                    "file_size": file_size,
                    "max_size": MAX_EXPORT_SIZE,
                },
            }

        # Detect file type
        mime_type = _get_mime_type(resolved)
        suffix = resolved.suffix.lower()
        is_binary = _is_binary_file(resolved)
        category = _get_artifact_category(mime_type, suffix)

        # Determine encoding to use
        use_base64 = False
        if encoding == "base64":
            use_base64 = True
        elif encoding == "text":
            use_base64 = False
        else:  # auto
            use_base64 = is_binary or file_size > AUTO_BASE64_THRESHOLD

        # Read file content with explicit error handling
        try:
            if use_base64:
                with open(resolved, "rb") as f:
                    raw_content = f.read()
                content_data = base64.b64encode(raw_content).decode("ascii")
                content_encoding = "base64"
            else:
                with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                    content_data = f.read()
                content_encoding = "utf-8"
        except PermissionError:
            return {
                "content": [
                    {"type": "text", "text": f"Error: Permission denied reading file: {file_path}"}
                ],
                "isError": True,
                "errorCode": "PERMISSION_DENIED",
                "errorDetails": {"file_path": file_path, "operation": "read"},
            }
        except IOError as e:
            return {
                "content": [{"type": "text", "text": f"Error: Failed to read file: {str(e)}"}],
                "isError": True,
                "errorCode": "IO_ERROR",
                "errorDetails": {"file_path": file_path, "error": str(e)},
            }

        # Build response with MCP image content type for images
        if category == "image" and use_base64:
            # Return as MCP image content
            return {
                "content": [
                    {
                        "type": "image",
                        "data": content_data,
                        "mimeType": mime_type,
                    },
                    {
                        "type": "text",
                        "text": f"Exported artifact: {resolved.name}",
                    },
                ],
                "isError": False,
                "artifact": {
                    "filename": resolved.name,
                    "path": str(resolved),
                    "mime_type": mime_type,
                    "category": category,
                    "size": file_size,
                    "encoding": content_encoding,
                    "is_binary": is_binary,
                },
            }
        else:
            # Return as text/data content
            return {
                "content": [
                    {
                        "type": "text",
                        "text": content_data
                        if not use_base64
                        else f"[Base64 encoded {category} file: {resolved.name}]",
                    }
                ],
                "isError": False,
                "artifact": {
                    "filename": resolved.name,
                    "path": str(resolved),
                    "mime_type": mime_type,
                    "category": category,
                    "size": file_size,
                    "encoding": content_encoding,
                    "is_binary": is_binary,
                    "data": content_data if use_base64 else None,
                },
            }

    except ValueError as e:
        # Path security error or validation error
        error_msg = str(e)
        return {
            "content": [{"type": "text", "text": f"Error: {error_msg}"}],
            "isError": True,
            "errorCode": "VALIDATION_ERROR",
            "errorDetails": {"file_path": file_path, "error": error_msg},
        }
    except PermissionError as e:
        return {
            "content": [{"type": "text", "text": f"Error: Permission denied: {str(e)}"}],
            "isError": True,
            "errorCode": "PERMISSION_DENIED",
            "errorDetails": {"file_path": file_path, "error": str(e)},
        }
    except OSError as e:
        # Handle various OS-level errors (IO errors, disk full, etc.)
        error_msg = str(e)
        error_code = "OS_ERROR"
        if "No space left" in error_msg:
            error_code = "DISK_FULL"
        elif "Input/output error" in error_msg:
            error_code = "IO_ERROR"
        logger.error(f"OS error exporting artifact {file_path}: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {error_msg}"}],
            "isError": True,
            "errorCode": error_code,
            "errorDetails": {"file_path": file_path, "error": error_msg},
        }
    except Exception as e:
        logger.error(f"Error exporting artifact {file_path}: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
            "errorCode": "UNKNOWN_ERROR",
            "errorDetails": {"file_path": file_path, "error": str(e)},
        }


async def list_artifacts(
    directory: str = "/workspace/output",
    recursive: bool = True,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    List files in a directory that could be exported as artifacts.

    Args:
        directory: Directory to scan for artifacts
        recursive: Whether to scan recursively
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Dict with list of files and their metadata
    """
    try:
        resolved = _resolve_path(directory, _workspace_dir)

        if not resolved.exists():
            return {
                "content": [{"type": "text", "text": f"Directory not found: {directory}"}],
                "isError": False,
                "files": [],
            }

        if not resolved.is_dir():
            return {
                "content": [{"type": "text", "text": f"Not a directory: {directory}"}],
                "isError": True,
            }

        # Collect files
        files: List[Dict[str, Any]] = []
        pattern = "**/*" if recursive else "*"

        for file_path in resolved.glob(pattern):
            if not file_path.is_file():
                continue

            # Skip hidden files and common ignore patterns
            if any(part.startswith(".") for part in file_path.parts):
                continue
            if "__pycache__" in str(file_path):
                continue

            try:
                stats = file_path.stat()
                mime_type = _get_mime_type(file_path)
                suffix = file_path.suffix.lower()

                files.append(
                    {
                        "path": str(file_path),
                        "name": file_path.name,
                        "size": stats.st_size,
                        "mime_type": mime_type,
                        "category": _get_artifact_category(mime_type, suffix),
                        "is_binary": _is_binary_file(file_path),
                    }
                )
            except Exception as e:
                logger.warning(f"Could not stat file {file_path}: {e}")

        # Sort by path
        files.sort(key=lambda x: x["path"])

        # Build summary text
        summary_lines = [f"Found {len(files)} files in {directory}:"]
        for f in files[:50]:  # Limit output
            size_str = f"{f['size']:,} bytes"
            summary_lines.append(f"  {f['name']} ({f['category']}, {size_str})")

        if len(files) > 50:
            summary_lines.append(f"  ... and {len(files) - 50} more files")

        return {
            "content": [{"type": "text", "text": "\n".join(summary_lines)}],
            "isError": False,
            "files": files,
        }

    except ValueError as e:
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }
    except Exception as e:
        logger.error(f"Error listing artifacts: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


async def batch_export_artifacts(
    file_paths: List[str],
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Export multiple files as artifacts in a single call.

    Args:
        file_paths: List of file paths to export
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Dict with results for each file
    """
    results = []
    errors = []

    for path in file_paths:
        try:
            result = await export_artifact(
                file_path=path,
                encoding="auto",
                _workspace_dir=_workspace_dir,
            )

            if result.get("isError"):
                errors.append({"path": path, "error": result["content"][0]["text"]})
            else:
                artifact = result.get("artifact", {})
                results.append(
                    {
                        "path": path,
                        "filename": artifact.get("filename"),
                        "mime_type": artifact.get("mime_type"),
                        "category": artifact.get("category"),
                        "size": artifact.get("size"),
                        "encoding": artifact.get("encoding"),
                        "data": artifact.get("data"),
                    }
                )

        except Exception as e:
            errors.append({"path": path, "error": str(e)})

    # Build summary
    summary_lines = [f"Exported {len(results)} files, {len(errors)} errors"]
    for r in results:
        summary_lines.append(f"  ✓ {r['filename']} ({r['category']}, {r['size']:,} bytes)")
    for e in errors:
        summary_lines.append(f"  ✗ {e['path']}: {e['error']}")

    return {
        "content": [{"type": "text", "text": "\n".join(summary_lines)}],
        "isError": len(errors) > 0 and len(results) == 0,
        "results": results,
        "errors": errors,
    }


def create_export_artifact_tool() -> MCPTool:
    """Create the export_artifact tool."""
    return MCPTool(
        name="export_artifact",
        description=(
            "Export a file as an artifact with proper encoding and MIME type detection. "
            "Supports all file types including images, documents, code, data files, "
            "audio, video, and archives. Binary files are automatically base64 encoded. "
            "Use this tool to retrieve generated files (images, PDFs, data files, etc.) "
            "from the workspace."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to export (absolute or relative to workspace)",
                },
                "encoding": {
                    "type": "string",
                    "enum": ["auto", "base64", "text"],
                    "description": "Encoding mode: 'auto' (detect based on file type), 'base64' (force), 'text' (force text)",
                    "default": "auto",
                },
            },
            "required": ["file_path"],
        },
        handler=export_artifact,
    )


def create_list_artifacts_tool() -> MCPTool:
    """Create the list_artifacts tool."""
    return MCPTool(
        name="list_artifacts",
        description=(
            "List files in a directory that could be exported as artifacts. "
            "Returns file metadata including name, size, MIME type, and category. "
            "Useful for discovering generated output files."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to scan for artifacts (default: /workspace/output)",
                    "default": "/workspace/output",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Whether to scan subdirectories recursively",
                    "default": True,
                },
            },
            "required": [],
        },
        handler=list_artifacts,
    )


def create_batch_export_artifacts_tool() -> MCPTool:
    """Create the batch_export_artifacts tool."""
    return MCPTool(
        name="batch_export_artifacts",
        description=(
            "Export multiple files as artifacts in a single call. "
            "More efficient than calling export_artifact multiple times."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to export",
                },
            },
            "required": ["file_paths"],
        },
        handler=batch_export_artifacts,
    )
