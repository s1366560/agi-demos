"""File system tools for MCP server.

Implements read, write, edit, glob, and grep operations.
"""

import asyncio
import difflib
import fnmatch
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatchHunkLine:
    """Represents a single parsed line inside a unified diff hunk."""

    operation: str
    text: str
    has_newline: bool = True

    def render(self) -> str:
        """Render the line back into file content."""
        return self.text + ("\n" if self.has_newline else "")


@dataclass(frozen=True)
class PatchHunk:
    """Represents a parsed unified diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[PatchHunkLine]

    def to_dict(self) -> dict[str, Any]:
        """Convert hunk metadata into a JSON-friendly dictionary."""
        diff_lines: list[str] = []
        for line in self.lines:
            diff_lines.append(f"{line.operation}{line.text}")
            if not line.has_newline:
                diff_lines.append("\\ No newline at end of file")
        return {
            "old_start": self.old_start,
            "old_count": self.old_count,
            "new_start": self.new_start,
            "new_count": self.new_count,
            "lines": diff_lines,
        }


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)

# Additional paths outside workspace that tools are allowed to access.
# These are common system directories that agents legitimately need to read/list.
_EXTRA_ALLOWED_PATHS: list[Path] = [
    Path("/tmp"),
    Path("/var/tmp"),
    Path("/etc"),
]

# If MCP_HOST_SOURCE is set, allow read-only access to the host source directory.
_host_source = os.getenv("MCP_HOST_SOURCE", "")
if _host_source:
    _EXTRA_ALLOWED_PATHS.append(Path(_host_source))


_DEFAULT_SCAN_EXCLUDES = {
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    ".cache",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    ".eggs",
    "*.egg-info",
    ".gradle",
    ".m2",
    "target",
}


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 100_000) -> int:
    """Read a bounded integer from the environment."""
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


def _env_float(name: str, default: float, *, minimum: float = 1.0, maximum: float = 300.0) -> float:
    """Read a bounded float from the environment."""
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


_DEFAULT_SCAN_MAX_FILES = _env_int("MCP_FILE_TOOL_MAX_SCAN_FILES", 5000)
_DEFAULT_SCAN_TIME_BUDGET_SECONDS = _env_float("MCP_FILE_TOOL_SCAN_TIME_BUDGET_SECONDS", 20.0)


@dataclass(frozen=True)
class _FileScanResult:
    files: list[Path]
    files_seen: int
    skipped_dirs: int
    truncated: bool
    elapsed_seconds: float


def _expand_user_path(path: str) -> str:
    """Expand user-home shorthand while preserving empty-path semantics."""
    return os.path.expanduser(path.strip() or ".")


def _build_error_text(
    message: str,
    *,
    hint: str | None = None,
    suggestions: list[str] | None = None,
) -> str:
    """Build a readable error message for MCP text content."""
    lines = [f"Error: {message}"]
    if hint:
        lines.append(f"Hint: {hint}")
    if suggestions:
        lines.append("Suggestions:")
        lines.extend(f"- {suggestion}" for suggestion in suggestions)
    return "\n".join(lines)


def _path_metadata(resolved: Path, workspace_dir: str) -> dict[str, Any]:
    """Return consistent path metadata for tool responses."""
    workspace = Path(_expand_user_path(workspace_dir)).resolve()
    metadata: dict[str, Any] = {
        "resolved_path": str(resolved),
        "workspace_root": str(workspace),
    }
    try:
        metadata["workspace_relative_path"] = str(resolved.relative_to(workspace))
    except ValueError:
        metadata["workspace_relative_path"] = None
    return metadata


def _nearest_existing_parent(path: Path) -> Path | None:
    """Find the nearest existing parent directory for a candidate path."""
    current = path if path.is_dir() else path.parent
    while True:
        if current.exists():
            return current
        if current == current.parent:
            return None
        current = current.parent


def _suggest_path_matches(
    path: str,
    workspace_dir: str,
    *,
    allow_extra_paths: bool = False,
    limit: int = 5,
) -> list[str]:
    """Return a compact list of similar nearby paths."""
    workspace = Path(_expand_user_path(workspace_dir)).resolve()
    normalized = _expand_user_path(path)
    candidate = Path(normalized) if os.path.isabs(normalized) else workspace / normalized
    parent = _nearest_existing_parent(candidate)
    if parent is None or not parent.is_dir():
        return []

    try:
        children = sorted(child.name for child in parent.iterdir())
    except OSError:
        return []

    close_matches = difflib.get_close_matches(candidate.name, children, n=limit, cutoff=0.4)
    suggestions: list[str] = []
    for match in close_matches:
        suggestion_path = (parent / match).resolve()
        try:
            suggestions.append(str(suggestion_path.relative_to(workspace)))
            continue
        except ValueError:
            pass

        if allow_extra_paths:
            suggestions.append(str(suggestion_path))

    return suggestions


def _success_result(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Return a standard successful MCP tool payload."""
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": text}],
        "isError": False,
    }
    if metadata is not None:
        result["metadata"] = metadata
    result.update(extra)
    return result


def _error_result(
    message: str,
    *,
    code: str,
    hint: str | None = None,
    suggestions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Return a standard error MCP tool payload."""
    error = {
        "code": code,
        "message": message,
        "hint": hint,
        "suggestions": suggestions or [],
    }
    merged_metadata = dict(metadata or {})
    merged_metadata["error"] = error
    result: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": _build_error_text(
                    message,
                    hint=hint,
                    suggestions=suggestions or None,
                ),
            }
        ],
        "isError": True,
        "error": error,
        "metadata": merged_metadata,
    }
    result.update(extra)
    return result


def get_path_error_result(
    message: str,
    *,
    code: str = "path_error",
    hint: str | None = None,
    suggestions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public helper for standardized path-related errors."""
    return _error_result(
        message,
        code=code,
        hint=hint,
        suggestions=suggestions,
        metadata=metadata,
    )

def _resolve_path(
    path: str,
    workspace_dir: str,
    allow_extra_paths: bool = False,
) -> Path:
    """
    Resolve a path relative to workspace directory.

    Ensures the path stays within the workspace (or within the
    extra-allowed paths if allow_extra_paths=True) for security.

    Args:
        path: User-provided path
        workspace_dir: Workspace root directory
        allow_extra_paths: If True, also permits paths under _EXTRA_ALLOWED_PATHS

    Returns:
        Resolved absolute path

    Raises:
        ValueError: If path escapes allowed directories
    """
    normalized_path = _expand_user_path(path)
    workspace = Path(_expand_user_path(workspace_dir)).resolve()

    # Handle absolute paths
    if os.path.isabs(normalized_path):
        resolved = Path(normalized_path).resolve()
    else:
        resolved = (workspace / normalized_path).resolve()

    # Security check: ensure path is within workspace
    try:
        resolved.relative_to(workspace)
        return resolved
    except ValueError:
        pass

    # Check extra allowed paths if enabled
    if allow_extra_paths:
        for allowed in _EXTRA_ALLOWED_PATHS:
            try:
                allowed_resolved = allowed.resolve()
                resolved.relative_to(allowed_resolved)
                return resolved
            except ValueError:
                continue

    raise ValueError(f"Path '{path}' is outside workspace directory")


# =============================================================================
# READ TOOL
# =============================================================================


async def read_file(
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
    raw: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Read contents of a file.

    Args:
        file_path: Path to the file (absolute or relative to workspace)
        offset: Line number to start reading from (0-based)
        limit: Maximum number of lines to read
        raw: If True, return raw content without line numbers
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Dict with file contents and metadata
    """
    try:
        resolved = _resolve_path(file_path, _workspace_dir, allow_extra_paths=True)
        path_metadata = _path_metadata(resolved, _workspace_dir)

        if not resolved.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Use glob to discover valid files near the requested path.",
                suggestions=_suggest_path_matches(
                    file_path,
                    _workspace_dir,
                    allow_extra_paths=True,
                ),
                metadata={"requested_path": file_path, **path_metadata},
            )

        if not resolved.is_file():
            return _error_result(
                f"Not a file: {file_path}",
                code="not_a_file",
                hint="Pass a concrete file path instead of a directory.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        async with aiofiles.open(resolved, "r", encoding="utf-8", errors="replace") as f:
            lines = await f.readlines()

        total_lines = len(lines)
        selected_lines = lines[offset : offset + limit]

        if raw:
            content = "".join(selected_lines)
        else:
            # Format with line numbers (1-based for display)
            numbered_lines = []
            for i, line in enumerate(selected_lines, start=offset + 1):
                # Truncate long lines
                if len(line) > 2000:
                    line = line[:2000] + "...(truncated)\n"
                numbered_lines.append(f"{i:6}\t{line.rstrip()}")
            content = "\n".join(numbered_lines)

        return _success_result(
            content,
            metadata={
                "total_lines": total_lines,
                "offset": offset,
                "offset_unit": "lines",
                "lines_returned": len(selected_lines),
                **path_metadata,
            },
        )

    except ValueError as exc:
        return get_path_error_result(
            str(exc),
            code="path_outside_workspace",
            hint="Use a path inside the workspace or an allowlisted read-only directory.",
            suggestions=_suggest_path_matches(
                file_path,
                _workspace_dir,
                allow_extra_paths=True,
            ),
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return _error_result(
            str(e),
            code="read_failed",
            metadata={"requested_path": file_path},
        )


def create_read_tool() -> MCPTool:
    """Create the read file tool."""
    return MCPTool(
        name="read",
        description="Read contents of a file. Returns lines with line numbers by default, or raw content with raw=true.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                    "default": 2000,
                },
                "raw": {
                    "type": "boolean",
                    "description": "If true, return raw file content without line numbers",
                    "default": False,
                },
            },
            "required": ["file_path"],
        },
        handler=read_file,
    )


async def batch_read(
    file_paths: list[str],
    offset: int = 0,
    limit: int = 2000,
    raw: bool = False,
    stop_on_error: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """Read multiple files in a single call."""
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for file_path in file_paths:
        result = await read_file(
            file_path=file_path,
            offset=offset,
            limit=limit,
            raw=raw,
            _workspace_dir=_workspace_dir,
        )
        if result.get("isError"):
            error_metadata = result.get("metadata", {}).get("error", {})
            errors.append(
                {
                    "file_path": file_path,
                    "error": error_metadata
                    or {"code": "read_failed", "message": result["content"][0]["text"]},
                }
            )
            if stop_on_error:
                break
            continue

        results.append(
            {
                "file_path": file_path,
                "content": result["content"][0]["text"],
                "metadata": result.get("metadata", {}),
            }
        )

    return _success_result(
        f"Batch read complete: {len(results)} successful, {len(errors)} failed",
        metadata={
            "total": len(file_paths),
            "successful": len(results),
            "failed": len(errors),
            "offset": offset,
            "offset_unit": "lines",
            "limit": limit,
            "raw": raw,
            "stop_on_error": stop_on_error,
        },
        results=results,
        errors=errors,
    )


def create_batch_read_tool() -> MCPTool:
    """Create the batch read tool."""
    return MCPTool(
        name="batch_read",
        description="Read multiple files in one call. Returns per-file content, metadata, and errors.",
        input_schema={
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (0-based)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read from each file",
                    "default": 2000,
                },
                "raw": {
                    "type": "boolean",
                    "description": "If true, return raw file content without line numbers",
                    "default": False,
                },
                "stop_on_error": {
                    "type": "boolean",
                    "description": "Stop after the first read failure",
                    "default": False,
                },
            },
            "required": ["file_paths"],
        },
        handler=batch_read,
    )


# =============================================================================
# WRITE TOOL
# =============================================================================


async def write_file(
    file_path: str,
    content: str,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Write content to a file (creates or overwrites).

    Args:
        file_path: Path to the file
        content: Content to write
        _workspace_dir: Workspace directory

    Returns:
        Result dict
    """
    try:
        resolved = _resolve_path(file_path, _workspace_dir)
        path_metadata = _path_metadata(resolved, _workspace_dir)

        # Create parent directories
        resolved.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.write(content)

        return _success_result(
            f"Successfully wrote to {file_path}",
            metadata={
                "bytes_written": len(content.encode("utf-8")),
                **path_metadata,
            },
        )

    except ValueError as exc:
        return get_path_error_result(
            str(exc),
            code="path_outside_workspace",
            hint="Write operations are limited to files inside the workspace.",
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error writing file: {e}")
        return _error_result(
            str(e),
            code="write_failed",
            metadata={"requested_path": file_path},
        )


def create_write_tool() -> MCPTool:
    """Create the write file tool."""
    return MCPTool(
        name="write",
        description="Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        },
        handler=write_file,
    )


# =============================================================================
# EDIT TOOL
# =============================================================================


async def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Edit a file by replacing text.

    Args:
        file_path: Path to the file
        old_string: Text to replace
        new_string: Replacement text
        replace_all: If True, replace all occurrences
        _workspace_dir: Workspace directory

    Returns:
        Result dict
    """
    try:
        resolved = _resolve_path(file_path, _workspace_dir)
        path_metadata = _path_metadata(resolved, _workspace_dir)

        if not resolved.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Use glob to discover valid files before editing.",
                suggestions=_suggest_path_matches(file_path, _workspace_dir),
                metadata={"requested_path": file_path, **path_metadata},
            )

        async with aiofiles.open(resolved, "r", encoding="utf-8") as f:
            content = await f.read()

        # Check if old_string exists
        if old_string not in content:
            return _error_result(
                f"String not found in file: {old_string[:100]}",
                code="string_not_found",
                hint="Read the file first or use grep to confirm the exact text to replace.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        # Check uniqueness if not replacing all
        if not replace_all and content.count(old_string) > 1:
            return _error_result(
                f"String appears {content.count(old_string)} times.",
                code="ambiguous_replacement",
                hint="Use replace_all=true or provide a longer unique old_string.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        # Perform replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1

        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.write(new_content)

        return _success_result(
            f"Successfully replaced {count} occurrence(s) in {file_path}",
            metadata={
                "replacements": count,
                **path_metadata,
            },
        )

    except ValueError as exc:
        return get_path_error_result(
            str(exc),
            code="path_outside_workspace",
            hint="Edit operations are limited to files inside the workspace.",
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error editing file: {e}")
        return _error_result(
            str(e),
            code="edit_failed",
            metadata={"requested_path": file_path},
        )


def create_edit_tool() -> MCPTool:
    """Create the edit file tool."""
    return MCPTool(
        name="edit",
        description="Edit a file by replacing exact string matches. The old_string must be unique unless replace_all is true.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "Text to replace with",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false)",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        handler=edit_file,
    )


# =============================================================================
# GLOB TOOL
# =============================================================================


async def glob_files(
    pattern: str,
    path: Optional[str] = None,
    max_results: int = 100,
    max_files: int = _DEFAULT_SCAN_MAX_FILES,
    exclude: Optional[list[str]] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "src/*.ts")
        path: Base directory to search in (default: workspace)
        _workspace_dir: Workspace directory

    Returns:
        List of matching file paths
    """
    try:
        workspace = Path(_expand_user_path(_workspace_dir)).resolve()
        normalized_pattern = _expand_user_path(pattern)

        # Handle absolute patterns like /workspace/**/*.py
        # pathlib.glob() rejects non-relative patterns, so we convert them
        if os.path.isabs(normalized_pattern):
            pattern_path = Path(normalized_pattern)
            # Check if the absolute pattern starts with the workspace dir
            try:
                rel_pattern = str(pattern_path.relative_to(workspace))
                normalized_pattern = rel_pattern
            except ValueError:
                # Pattern is outside workspace - also try unresolved workspace
                try:
                    rel_pattern = str(pattern_path.relative_to(Path(_expand_user_path(_workspace_dir))))
                    normalized_pattern = rel_pattern
                except ValueError:
                    return get_path_error_result(
                        f"Absolute pattern '{pattern}' is outside workspace directory",
                        code="path_outside_workspace",
                        hint="Use a pattern rooted in the workspace or pass a workspace-relative pattern.",
                        metadata={"pattern": pattern},
                    )

        if path:
            base_dir = _resolve_path(path, _workspace_dir, allow_extra_paths=True)
        else:
            base_dir = workspace

        if not base_dir.exists():
            return _error_result(
                f"Directory not found: {path}",
                code="directory_not_found",
                hint="Use list or glob on a parent directory to discover valid search roots.",
                suggestions=_suggest_path_matches(path or ".", _workspace_dir, allow_extra_paths=True),
                metadata={"requested_path": path, "pattern": pattern},
            )

        scan = await asyncio.to_thread(
            _collect_scan_files,
            base_dir,
            pattern=normalized_pattern,
            excludes=_scan_excludes(exclude),
            max_files=_coerce_scan_limit(max_files, _DEFAULT_SCAN_MAX_FILES),
            time_budget_seconds=_DEFAULT_SCAN_TIME_BUDGET_SECONDS,
        )

        matches = []
        for match in scan.files:
            # Return relative path from workspace
            try:
                rel_path = match.relative_to(workspace)
                matches.append(str(rel_path))
            except ValueError:
                matches.append(str(match))

        # Sort by modification time (newest first)
        def get_mtime(p):
            try:
                return (workspace / p).stat().st_mtime
            except OSError:
                return 0

        matches.sort(key=get_mtime, reverse=True)

        max_results = _coerce_scan_limit(max_results, 100, maximum=1000)

        if not matches:
            return _success_result(
                f"No files found matching: {pattern}",
                metadata={
                    "total_matches": 0,
                    "pattern": normalized_pattern,
                    "search_root": str(base_dir.resolve()),
                    "files_seen": scan.files_seen,
                    "skipped_dirs": scan.skipped_dirs,
                    "search_truncated": scan.truncated,
                    "elapsed_seconds": round(scan.elapsed_seconds, 3),
                },
            )

        result = "\n".join(matches[:max_results])
        if len(matches) > max_results:
            result += f"\n... and {len(matches) - max_results} more files"
        if scan.truncated:
            result += "\n... (search stopped early by scan safety limits)"

        return _success_result(
            result,
            metadata={
                "total_matches": len(matches),
                "pattern": normalized_pattern,
                "search_root": str(base_dir.resolve()),
                "files_seen": scan.files_seen,
                "skipped_dirs": scan.skipped_dirs,
                "search_truncated": scan.truncated,
                "elapsed_seconds": round(scan.elapsed_seconds, 3),
            },
        )

    except ValueError as exc:
        return get_path_error_result(
            str(exc),
            code="path_outside_workspace",
            hint="Search roots must stay inside the workspace or an allowlisted read-only directory.",
            metadata={"requested_path": path, "pattern": pattern},
        )
    except Exception as e:
        logger.error(f"Error in glob: {e}")
        return _error_result(
            str(e),
            code="glob_failed",
            metadata={"requested_path": path, "pattern": pattern},
        )


def create_glob_tool() -> MCPTool:
    """Create the glob tool."""
    return MCPTool(
        name="glob",
        description="Find files matching a glob pattern. Supports ** for recursive matching.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts')",
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search in (default: workspace root)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching paths to return (default: 100)",
                    "default": 100,
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum candidate files to scan before stopping (default: 5000)",
                    "default": _DEFAULT_SCAN_MAX_FILES,
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional directory/file names or glob patterns to skip",
                },
            },
            "required": ["pattern"],
        },
        handler=glob_files,
    )


# =============================================================================
# GREP TOOL
# =============================================================================


def _merge_context_ranges(
    match_indices: list[int],
    context_lines: int,
    total_lines: int,
) -> list[tuple[int, int]]:
    """Merge overlapping context windows for grep output."""
    if context_lines <= 0 or not match_indices:
        return []

    ranges: list[tuple[int, int]] = []
    for index in match_indices:
        start = max(0, index - context_lines)
        end = min(total_lines - 1, index + context_lines)
        if not ranges or start > ranges[-1][1] + 1:
            ranges.append((start, end))
        else:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
    return ranges


def _format_grep_path(file_path: Path, workspace_dir: str, base_dir: Path) -> str:
    """Format a grep result path relative to workspace or search root."""
    resolved_file = file_path.resolve()
    workspace = Path(workspace_dir).resolve()
    try:
        return str(resolved_file.relative_to(workspace))
    except ValueError:
        search_root = base_dir.resolve() if base_dir.is_dir() else base_dir.resolve().parent
        try:
            return str(resolved_file.relative_to(search_root))
        except ValueError:
            return str(resolved_file)


def _coerce_scan_limit(value: int | None, default: int, *, maximum: int = 50_000) -> int:
    """Clamp caller-provided scan limits to a bounded positive range."""
    if value is None:
        return default
    try:
        return min(max(int(value), 1), maximum)
    except (TypeError, ValueError):
        return default


def _scan_excludes(extra_excludes: Optional[list[str]] = None) -> set[str]:
    """Return the default scan excludes plus caller-provided names/patterns."""
    excludes = set(_DEFAULT_SCAN_EXCLUDES)
    if extra_excludes:
        excludes.update(str(item) for item in extra_excludes if str(item).strip())
    return excludes


def _is_scan_excluded(relative_path: Path, excludes: set[str]) -> bool:
    """Return True when any path segment matches the scan exclude list."""
    for part in relative_path.parts:
        for exclude in excludes:
            if part == exclude or fnmatch.fnmatch(part, exclude):
                return True
    return False


def _matches_file_pattern(relative_path: Path, pattern: str | None) -> bool:
    """Match pathlib glob-style patterns without traversing excluded directories."""
    if not pattern:
        return True

    normalized = pattern.replace(os.sep, "/")
    path_text = relative_path.as_posix()

    if "/" not in normalized and "**" not in normalized:
        return len(relative_path.parts) == 1 and fnmatch.fnmatch(relative_path.name, normalized)

    if fnmatch.fnmatch(path_text, normalized):
        return True

    if normalized.startswith("**/"):
        return fnmatch.fnmatch(path_text, normalized[3:])

    return False


def _collect_scan_files(
    base_dir: Path,
    *,
    pattern: str | None,
    excludes: set[str],
    max_files: int,
    time_budget_seconds: float,
) -> _FileScanResult:
    """Collect candidate files in a bounded synchronous scan."""
    started_at = time.monotonic()
    files: list[Path] = []
    files_seen = 0
    skipped_dirs = 0
    truncated = False

    if base_dir.is_file():
        return _FileScanResult(
            files=[base_dir] if _matches_file_pattern(Path(base_dir.name), pattern) else [],
            files_seen=1,
            skipped_dirs=0,
            truncated=False,
            elapsed_seconds=time.monotonic() - started_at,
        )

    for root, dirnames, filenames in os.walk(base_dir, topdown=True, followlinks=False):
        elapsed = time.monotonic() - started_at
        if elapsed > time_budget_seconds:
            truncated = True
            break

        current = Path(root)
        try:
            relative_root = current.relative_to(base_dir)
        except ValueError:
            relative_root = Path(".")

        kept_dirs = []
        for dirname in dirnames:
            relative_dir = relative_root / dirname if str(relative_root) != "." else Path(dirname)
            if _is_scan_excluded(relative_dir, excludes):
                skipped_dirs += 1
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs

        for filename in filenames:
            relative_file = relative_root / filename if str(relative_root) != "." else Path(filename)
            if _is_scan_excluded(relative_file, excludes):
                continue

            files_seen += 1
            if _matches_file_pattern(relative_file, pattern):
                files.append(current / filename)
                if len(files) >= max_files:
                    truncated = True
                    break

            if time.monotonic() - started_at > time_budget_seconds:
                truncated = True
                break

        if truncated:
            break

    return _FileScanResult(
        files=files,
        files_seen=files_seen,
        skipped_dirs=skipped_dirs,
        truncated=truncated,
        elapsed_seconds=time.monotonic() - started_at,
    )


async def grep_files(
    pattern: str,
    path: Optional[str] = None,
    glob_pattern: Optional[str] = None,
    case_insensitive: bool = False,
    context_lines: int = 0,
    max_results: int = 100,
    max_files: int = _DEFAULT_SCAN_MAX_FILES,
    exclude: Optional[list[str]] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Search for pattern in files.

    Args:
        pattern: Regex pattern to search for
        path: Directory to search in (default: workspace)
        glob_pattern: File pattern to filter (e.g., "*.py")
        case_insensitive: Case insensitive search
        context_lines: Lines of context to show before/after match
        max_results: Maximum number of results
        _workspace_dir: Workspace directory

    Returns:
        Search results
    """
    try:
        if path:
            base_dir = _resolve_path(path, _workspace_dir, allow_extra_paths=True)
        else:
            base_dir = Path(_expand_user_path(_workspace_dir)).resolve()

        if not base_dir.exists():
            return _error_result(
                f"Directory not found: {path}",
                code="directory_not_found",
                hint="Use list or glob on a parent directory to discover valid search roots.",
                suggestions=_suggest_path_matches(path or ".", _workspace_dir, allow_extra_paths=True),
                metadata={"requested_path": path, "pattern": pattern},
            )

        # Compile regex
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return _error_result(
                f"Invalid regex pattern: {e}",
                code="invalid_regex",
                hint="Provide a valid Python regular expression.",
                metadata={"pattern": pattern},
            )

        max_results = _coerce_scan_limit(max_results, 100, maximum=1000)
        max_files = _coerce_scan_limit(max_files, _DEFAULT_SCAN_MAX_FILES)

        scan = await asyncio.to_thread(
            _collect_scan_files,
            base_dir,
            pattern=glob_pattern,
            excludes=_scan_excludes(exclude),
            max_files=max_files,
            time_budget_seconds=_DEFAULT_SCAN_TIME_BUDGET_SECONDS,
        )

        results = []
        files_searched = 0
        matches_found = 0
        search_truncated = scan.truncated
        started_at = time.monotonic()

        for file_path in scan.files:
            if not file_path.is_file():
                continue

            # Skip binary files
            try:
                with open(file_path, "rb") as f:
                    chunk = f.read(1024)
                    if b"\x00" in chunk:
                        continue
            except OSError:
                continue

            files_searched += 1

            try:
                async with aiofiles.open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = await f.readlines()

                line_texts = [line.rstrip("\n") for line in lines]
                match_indices = [i for i, line in enumerate(line_texts) if regex.search(line)]
                if not match_indices:
                    continue

                remaining = max_results - matches_found
                selected_matches = match_indices[:remaining]
                display_path = _format_grep_path(file_path, _workspace_dir, base_dir)

                if context_lines > 0:
                    merged_ranges = _merge_context_ranges(
                        selected_matches,
                        context_lines,
                        len(line_texts),
                    )
                    selected_match_set = set(selected_matches)
                    for start, end in merged_ranges:
                        for line_index in range(start, end + 1):
                            line_text = line_texts[line_index]
                            if line_index in selected_match_set:
                                results.append(f"{display_path}:{line_index + 1}: {line_text}")
                            else:
                                results.append(f"{display_path}-{line_index + 1}- {line_text}")
                else:
                    for line_index in selected_matches:
                        results.append(f"{display_path}:{line_index + 1}: {line_texts[line_index]}")

                matches_found += len(selected_matches)

            except Exception as e:
                logger.debug(f"Error reading {file_path}: {e}")
                continue

            if matches_found >= max_results:
                break

            if time.monotonic() - started_at > _DEFAULT_SCAN_TIME_BUDGET_SECONDS:
                search_truncated = True
                break

        if not results:
            return _success_result(
                f"No matches found for: {pattern}",
                metadata={
                    "files_searched": files_searched,
                    "files_seen": scan.files_seen,
                    "matches_found": 0,
                    "skipped_dirs": scan.skipped_dirs,
                    "search_truncated": search_truncated,
                    "elapsed_seconds": round(scan.elapsed_seconds, 3),
                },
            )

        result_text = "\n".join(results)
        if matches_found >= max_results:
            result_text += f"\n... (truncated, showing first {max_results} matches)"
        elif search_truncated:
            result_text += "\n... (search stopped early by scan safety limits)"

        return _success_result(
            result_text,
            metadata={
                "files_searched": files_searched,
                "files_seen": scan.files_seen,
                "matches_found": matches_found,
                "skipped_dirs": scan.skipped_dirs,
                "search_truncated": search_truncated,
                "elapsed_seconds": round(scan.elapsed_seconds, 3),
            },
        )

    except ValueError as exc:
        return get_path_error_result(
            str(exc),
            code="path_outside_workspace",
            hint="Search roots must stay inside the workspace or an allowlisted read-only directory.",
            metadata={"requested_path": path, "pattern": pattern},
        )
    except Exception as e:
        logger.error(f"Error in grep: {e}")
        return _error_result(
            str(e),
            code="grep_failed",
            metadata={"requested_path": path, "pattern": pattern},
        )


def create_grep_tool() -> MCPTool:
    """Create the grep tool."""
    return MCPTool(
        name="grep",
        description="Search for a regex pattern in files. Returns matching lines with file paths and line numbers.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: workspace)",
                },
                "glob_pattern": {
                    "type": "string",
                    "description": "File pattern to filter (e.g., '*.py', '**/*.ts')",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Case insensitive search",
                    "default": False,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines to include around each match",
                    "default": 0,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100,
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum candidate files to scan before stopping (default: 5000)",
                    "default": _DEFAULT_SCAN_MAX_FILES,
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional directory/file names or glob patterns to skip",
                },
            },
            "required": ["pattern"],
        },
        handler=grep_files,
    )


# =============================================================================
# LIST TOOL
# =============================================================================


# Maximum number of entries to collect during recursive listing to prevent
# extremely long output that overwhelms the agent's context window.
_MAX_RECURSIVE_ENTRIES = 500


def _walk_directory(
    root: Path,
    current: Path,
    items: list,
    max_depth: int,
    current_depth: int,
    include_hidden: bool,
    excludes: set,
) -> None:
    """Recursively walk a directory with depth limit and exclude support.

    Collects paths into `items` list. Stops descending into excluded
    directories and respects max_depth.
    """
    if current_depth >= max_depth:
        return
    if len(items) >= _MAX_RECURSIVE_ENTRIES:
        return

    try:
        children = sorted(
            current.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except PermissionError:
        return

    for child in children:
        if len(items) >= _MAX_RECURSIVE_ENTRIES:
            return

        name = child.name

        # Skip hidden items unless requested
        if not include_hidden and name.startswith("."):
            continue

        # Check excludes — supports both exact names and simple glob patterns
        if name in excludes:
            continue
        # Handle *.ext style patterns in excludes
        skip = False
        for exc in excludes:
            if exc.startswith("*") and name.endswith(exc[1:]):
                skip = True
                break
        if skip:
            continue

        items.append(child)

        if child.is_dir():
            _walk_directory(
                root, child, items,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                include_hidden=include_hidden,
                excludes=excludes,
            )


async def list_directory(
    path: str = ".",
    recursive: bool = False,
    include_hidden: bool = False,
    detailed: bool = False,
    max_depth: int = 5,
    exclude: Optional[list] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    List directory contents.

    Args:
        path: Path to list (default: current directory)
        recursive: Whether to list recursively
        include_hidden: Whether to include hidden files/directories
        detailed: Whether to show detailed info (permissions, size, etc.)
        max_depth: Maximum recursion depth for recursive listing (default: 5)
        exclude: Additional directory/file names to exclude from recursive listing.
            Default excludes always applied: node_modules, .git, __pycache__, etc.
        _workspace_dir: Workspace directory

    Returns:
        Formatted directory listing
    """
    try:
        resolved = _resolve_path(path, _workspace_dir, allow_extra_paths=True)
        path_metadata = _path_metadata(resolved, _workspace_dir)

        if not resolved.exists():
            return _error_result(
                f"Path not found: {path}",
                code="path_not_found",
                hint="Use list on a parent directory or glob to discover available paths.",
                suggestions=_suggest_path_matches(path, _workspace_dir, allow_extra_paths=True),
                metadata={"requested_path": path, **path_metadata},
            )

        if resolved.is_file():
            # Single file - return file info
            stat = resolved.stat()
            size_str = _format_size(stat.st_size)
            mtime = _format_mtime(stat.st_mtime)

            return _success_result(
                f"📄 {resolved.name} ({size_str}, {mtime})",
                metadata=path_metadata,
            )

        # It's a directory - list contents
        entries = []

        if recursive:
            # Default directories to exclude from recursive listing — these
            # produce massive output and are almost never what the caller wants.
            default_excludes = {
                "node_modules", ".git", "__pycache__", ".next", "dist",
                ".cache", ".venv", "venv", ".tox", ".mypy_cache",
                ".pytest_cache", ".ruff_cache", "build", ".eggs",
                "*.egg-info", ".gradle", ".m2", "target",
            }
            # Merge user-provided excludes
            excludes = default_excludes | set(exclude) if exclude else default_excludes

            # Depth-limited recursive listing to avoid unbounded traversal.
            # We walk the tree manually instead of using rglob so we can
            # enforce max_depth and skip excluded directories.
            items = []
            _walk_directory(
                resolved, resolved, items,
                max_depth=max_depth,
                current_depth=0,
                include_hidden=include_hidden,
                excludes=excludes,
            )
        else:
            # Non-recursive
            items = sorted(
                resolved.iterdir(),
                key=lambda p: (not p.name.startswith("."), p.name.lower()),
            )

        if not items:
            return _success_result(
                f"📁 Empty directory: {path}",
                metadata=path_metadata,
            )

        for item in items:
            try:
                # Skip hidden files if not requested
                if not include_hidden and item.name.startswith("."):
                    continue

                stat = item.stat()
                is_dir = item.is_dir()

                if is_dir:
                    icon = "📁"
                    name = item.name + "/"
                    size_str = "-"
                    mtime = _format_mtime(stat.st_mtime)
                else:
                    icon = "📄"
                    name = item.name
                    size_str = _format_size(stat.st_size)
                    mtime = _format_mtime(stat.st_mtime)

                if detailed:
                    # Add permissions
                    perms = stat.st_mode
                    perm_str = _format_permissions(perms)
                    entries.append(f"{icon} {perm_str} {size_str:>8} {mtime} {name}")
                else:
                    entries.append(f"{icon} {name}")

            except Exception as e:
                logger.debug(f"Error listing item: {e}")

        if not entries:
            return _success_result(
                f"📁 Empty directory: {path}",
                metadata=path_metadata,
            )

        header = f"📁 Listing: {path}"
        if recursive:
            header += " (recursive)"
        if include_hidden:
            header += " (including hidden)"

        result = f"{header}\n" + "\n".join(entries)

        if recursive and len(entries) >= _MAX_RECURSIVE_ENTRIES:
            result += (
                f"\n... truncated at {_MAX_RECURSIVE_ENTRIES} entries"
                f" (max_depth={max_depth}, excludes: {', '.join(sorted(list(excludes)[:5]))}...)"
            )
        elif recursive and len(entries) > 50:
            result += f"\n... ({len(entries)} total entries)"

        return _success_result(
            result,
            metadata={"total_entries": len(entries), **path_metadata},
        )

    except ValueError as exc:
        return get_path_error_result(
            str(exc),
            code="path_outside_workspace",
            hint="Listing is limited to the workspace or allowlisted read-only directories.",
            metadata={"requested_path": path},
        )
    except Exception as e:
        logger.error(f"Error listing directory: {e}")
        return _error_result(
            str(e),
            code="list_failed",
            metadata={"requested_path": path},
        )


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit, threshold in [("B", 1024), ("KB", 1024**2), ("MB", 1024**3), ("GB", 1024**4)]:
        if size < threshold:
            return f"{size}{unit}"
        size /= threshold
    return f"{size:.1f}GB"


def _format_mtime(mtime: float) -> str:
    """Format modification time."""
    from datetime import datetime

    dt = datetime.fromtimestamp(mtime)
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_permissions(mode: int) -> str:
    """Format file permissions (ls -l style)."""
    user_r = "r" if (mode & 0o400) else "-"
    user_w = "w" if (mode & 0o200) else "-"
    user_x = "x" if (mode & 0o100) else "-"
    return f"{user_r}{user_w}{user_x}"


def create_list_tool() -> MCPTool:
    """Create the list directory tool."""
    return MCPTool(
        name="list",
        description="List directory contents. Supports recursive listing, hidden files, and detailed info.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to list (default: current directory)",
                    "default": ".",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List directories recursively",
                    "default": False,
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files and directories",
                    "default": False,
                },
                "detailed": {
                    "type": "boolean",
                    "description": "Show detailed info (permissions, size, modification time)",
                    "default": False,
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum recursion depth (default: 5). Only used with recursive=true.",
                    "default": 5,
                },
                "exclude": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Additional directory/file names to exclude from recursive listing. Defaults already exclude node_modules, .git, __pycache__, .next, dist, etc.",
                },
            },
        },
        handler=list_directory,
    )


# =============================================================================
# PATCH TOOL
# =============================================================================


async def apply_patch(
    file_path: str,
    patch: str,
    strip: int = 0,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Apply a unified diff patch to a file.

    Args:
        file_path: Path to the file to patch
        patch: Unified diff format patch content
        strip: Number of path components to strip from file names in patch
        _workspace_dir: Workspace directory

    Returns:
        Result dict with success/error status
    """
    try:
        resolved = _resolve_path(file_path, _workspace_dir)
        path_metadata = _path_metadata(resolved, _workspace_dir)

        if not resolved.exists():
            return _error_result(
                f"File not found: {file_path}",
                code="file_not_found",
                hint="Use list or glob to confirm the patch target exists.",
                suggestions=_suggest_path_matches(file_path, _workspace_dir),
                metadata={"requested_path": file_path, **path_metadata},
            )

        if not resolved.is_file():
            return _error_result(
                f"Not a file: {file_path}",
                code="not_a_file",
                hint="Patch requires a concrete file path.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        # Read original file
        async with aiofiles.open(resolved, "r", encoding="utf-8") as f:
            original_lines = await f.readlines()

        # Parse patch
        parsed_patch = _parse_unified_diff(patch, strip)
        parsed_hunks = parsed_patch["hunks"]
        if not parsed_hunks or parsed_patch["header_count"] != 1:
            return _error_result(
                "Invalid patch format, missing headers, or no hunks found",
                code="invalid_patch",
                hint="Provide a unified diff with one target file and at least one hunk.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        if not _patch_targets_match(
            resolved,
            _workspace_dir,
            parsed_patch["old_path"],
            parsed_patch["new_path"],
            strip,
        ):
            return _error_result(
                "Patch target does not match the requested file path",
                code="patch_target_mismatch",
                hint="Make sure the diff headers target the same file_path you passed to the tool.",
                metadata={"requested_path": file_path, **path_metadata},
            )

        # Apply hunks to file content
        new_lines, failed_hunks = _apply_hunks(original_lines, parsed_hunks)

        if failed_hunks:
            return _error_result(
                f"Patch application failed. {len(failed_hunks)} hunks could not be applied.",
                code="patch_apply_failed",
                hint="Re-read the target file and regenerate the patch against the current content.",
                metadata={
                    "failed_hunks": [hunk.to_dict() for hunk in failed_hunks],
                    "requested_path": file_path,
                    **path_metadata,
                },
            )

        # Write patched content
        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.writelines(new_lines)

        return _success_result(
            f"Successfully applied patch to {file_path} ({len(parsed_hunks)} hunks)",
            metadata={"hunks_applied": len(parsed_hunks), **path_metadata},
        )

    except ValueError as e:
        return get_path_error_result(
            str(e),
            code="path_outside_workspace",
            hint="Patch operations are limited to files inside the workspace.",
            metadata={"requested_path": file_path},
        )
    except Exception as e:
        logger.error(f"Error applying patch: {e}")
        return _error_result(
            str(e),
            code="patch_failed",
            metadata={"requested_path": file_path},
        )


def _extract_patch_path(header_value: str) -> str | None:
    """Extract the normalized file path from a unified diff header."""
    raw_path = header_value.split("\t", 1)[0].strip()
    if raw_path == "/dev/null":
        return None
    return raw_path.replace("\\", "/")


def _candidate_patch_paths(patch_path: str | None, strip: int = 0) -> set[str]:
    """Generate candidate normalized paths for a diff header."""
    if not patch_path:
        return set()

    parts = [part for part in patch_path.split("/") if part not in {"", "."}]
    if strip == 0 and parts[:1] in (["a"], ["b"]):
        parts = parts[1:]
    elif strip > 0:
        parts = parts[strip:] if strip < len(parts) else []

    return {"/".join(parts)} if parts else set()


def _patch_targets_match(
    target_file_path: Path,
    workspace_dir: str,
    old_path: str | None,
    new_path: str | None,
    strip: int = 0,
) -> bool:
    """Check whether diff headers target the requested file path."""
    workspace = Path(workspace_dir).resolve()
    try:
        normalized_target = str(target_file_path.resolve().relative_to(workspace))
    except ValueError:
        normalized_target = target_file_path.resolve().as_posix().lstrip("./")
    candidates = _candidate_patch_paths(old_path, strip) | _candidate_patch_paths(new_path, strip)
    return not candidates or normalized_target in candidates


def _parse_unified_diff(patch_content: str, strip: int = 0) -> dict[str, Any]:
    """
    Parse unified diff format patch into hunks.

    Args:
        patch_content: Unified diff patch content
        strip: Number of path components to strip

    Returns:
        Parsed patch metadata
    """
    hunks: list[PatchHunk] = []
    lines = patch_content.splitlines()
    old_path: str | None = None
    new_path: str | None = None
    header_count = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("--- "):
            header_count += 1
            old_path = _extract_patch_path(line[4:])
            i += 1
            if i < len(lines) and lines[i].startswith("+++ "):
                new_path = _extract_patch_path(lines[i][4:])
                i += 1
            continue

        # Look for hunk header: @@ -old_start,old_count +new_start,new_count @@
        match = _HUNK_HEADER_RE.match(line)
        if match:
            old_start = int(match.group("old_start"))
            old_count = int(match.group("old_count") or ("0" if old_start == 0 else "1"))
            new_start = int(match.group("new_start"))
            new_count = int(match.group("new_count") or ("0" if new_start == 0 else "1"))

            i += 1
            hunk_lines: list[PatchHunkLine] = []
            while i < len(lines):
                hunk_line = lines[i]
                if hunk_line.startswith("@@") or hunk_line.startswith("--- "):
                    break

                if hunk_line.startswith("\\ "):
                    if hunk_lines:
                        previous = hunk_lines[-1]
                        hunk_lines[-1] = PatchHunkLine(
                            operation=previous.operation,
                            text=previous.text,
                            has_newline=False,
                        )
                    i += 1
                    continue

                if hunk_line[:1] in {" ", "+", "-"}:
                    hunk_lines.append(
                        PatchHunkLine(
                            operation=hunk_line[0],
                            text=hunk_line[1:],
                        )
                    )
                    i += 1
                    continue

                break

            hunks.append(
                PatchHunk(
                    old_start=old_start - 1,
                    old_count=old_count,
                    new_start=new_start - 1,
                    new_count=new_count,
                    lines=hunk_lines,
                )
            )
            continue

        i += 1

    return {
        "old_path": old_path,
        "new_path": new_path,
        "header_count": header_count,
        "hunks": hunks,
    }


def _apply_hunks(
    original_lines: list[str],
    hunks: list[PatchHunk],
) -> tuple[list[str], list[PatchHunk]]:
    """
    Apply hunks to file content.

    Args:
        original_lines: Original file lines
        hunks: List of parsed hunks

    Returns:
        Tuple of (new_lines, failed_hunks)
    """
    # Sort hunks by old_start (apply from bottom to top to avoid line number shifts)
    sorted_hunks = sorted(hunks, key=lambda h: h.old_start, reverse=True)

    result_lines = original_lines.copy()
    failed_hunks: list[PatchHunk] = []

    for hunk in sorted_hunks:
        old_start = hunk.old_start
        old_count = hunk.old_count

        old_lines_from_hunk = [
            line.render()
            for line in hunk.lines
            if line.operation in {" ", "-"}
        ]
        actual_old_lines = result_lines[old_start:old_start + old_count]

        if old_lines_from_hunk != actual_old_lines:
            failed_hunks.append(hunk)
            continue

        new_lines = [
            line.render()
            for line in hunk.lines
            if line.operation in {" ", "+"}
        ]
        result_lines[old_start:old_start + old_count] = new_lines

    return result_lines, failed_hunks


def create_patch_tool() -> MCPTool:
    """Create the patch tool."""
    return MCPTool(
        name="patch",
        description="Apply a unified diff patch to a file. Supports multiple hunks and path stripping.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to patch",
                },
                "patch": {
                    "type": "string",
                    "description": "Unified diff format patch content",
                },
                "strip": {
                    "type": "integer",
                    "description": "Number of path components to strip from file names in patch (default: 0)",
                    "default": 0,
                },
            },
            "required": ["file_path", "patch"],
        },
        handler=apply_patch,
    )
