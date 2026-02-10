"""File system tools for MCP server.

Implements read, write, edit, glob, and grep operations.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import aiofiles

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)


def _resolve_path(path: str, workspace_dir: str) -> Path:
    """
    Resolve a path relative to workspace directory.

    Ensures the path stays within the workspace for security.

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
        resolved = _resolve_path(file_path, _workspace_dir)

        if not resolved.exists():
            return {
                "content": [{"type": "text", "text": f"Error: File not found: {file_path}"}],
                "isError": True,
            }

        if not resolved.is_file():
            return {
                "content": [{"type": "text", "text": f"Error: Not a file: {file_path}"}],
                "isError": True,
            }

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

        return {
            "content": [{"type": "text", "text": content}],
            "isError": False,
            "metadata": {
                "total_lines": total_lines,
                "offset": offset,
                "lines_returned": len(selected_lines),
            },
        }

    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


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

        # Create parent directories
        resolved.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.write(content)

        return {
            "content": [{"type": "text", "text": f"Successfully wrote to {file_path}"}],
            "isError": False,
        }

    except Exception as e:
        logger.error(f"Error writing file: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


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

        if not resolved.exists():
            return {
                "content": [{"type": "text", "text": f"Error: File not found: {file_path}"}],
                "isError": True,
            }

        async with aiofiles.open(resolved, "r", encoding="utf-8") as f:
            content = await f.read()

        # Check if old_string exists
        if old_string not in content:
            return {
                "content": [
                    {"type": "text", "text": f"Error: String not found in file: {old_string[:100]}"}
                ],
                "isError": True,
            }

        # Check uniqueness if not replacing all
        if not replace_all and content.count(old_string) > 1:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: String appears {content.count(old_string)} times. "
                        "Use replace_all=true or provide more context.",
                    }
                ],
                "isError": True,
            }

        # Perform replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1

        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.write(new_content)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Successfully replaced {count} occurrence(s) in {file_path}",
                }
            ],
            "isError": False,
        }

    except Exception as e:
        logger.error(f"Error editing file: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


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
        if path:
            base_dir = _resolve_path(path, _workspace_dir)
        else:
            base_dir = Path(_workspace_dir)

        if not base_dir.exists():
            return {
                "content": [{"type": "text", "text": f"Error: Directory not found: {path}"}],
                "isError": True,
            }

        # Use pathlib glob
        matches = []
        for match in base_dir.glob(pattern):
            if match.is_file():
                # Return relative path from workspace
                try:
                    rel_path = match.relative_to(_workspace_dir)
                    matches.append(str(rel_path))
                except ValueError:
                    matches.append(str(match))

        # Sort by modification time (newest first)
        def get_mtime(p):
            try:
                return (Path(_workspace_dir) / p).stat().st_mtime
            except OSError:
                return 0

        matches.sort(key=get_mtime, reverse=True)

        if not matches:
            return {
                "content": [{"type": "text", "text": f"No files found matching: {pattern}"}],
                "isError": False,
            }

        result = "\n".join(matches[:100])  # Limit to 100 files
        if len(matches) > 100:
            result += f"\n... and {len(matches) - 100} more files"

        return {
            "content": [{"type": "text", "text": result}],
            "isError": False,
            "metadata": {"total_matches": len(matches)},
        }

    except Exception as e:
        logger.error(f"Error in glob: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


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
            },
            "required": ["pattern"],
        },
        handler=glob_files,
    )


# =============================================================================
# GREP TOOL
# =============================================================================


async def grep_files(
    pattern: str,
    path: Optional[str] = None,
    glob_pattern: Optional[str] = None,
    case_insensitive: bool = False,
    context_lines: int = 0,
    max_results: int = 100,
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
            base_dir = _resolve_path(path, _workspace_dir)
        else:
            base_dir = Path(_workspace_dir)

        if not base_dir.exists():
            return {
                "content": [{"type": "text", "text": f"Error: Directory not found: {path}"}],
                "isError": True,
            }

        # Compile regex
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return {
                "content": [{"type": "text", "text": f"Error: Invalid regex pattern: {e}"}],
                "isError": True,
            }

        results = []
        files_searched = 0
        matches_found = 0

        # Get files to search
        if glob_pattern:
            files = list(base_dir.glob(glob_pattern))
        else:
            files = list(base_dir.rglob("*"))

        for file_path in files:
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

                for i, line in enumerate(lines):
                    if regex.search(line):
                        rel_path = file_path.relative_to(_workspace_dir)

                        result_text = f"{rel_path}:{i + 1}: {line.rstrip()}"
                        results.append(result_text)
                        matches_found += 1

                        if matches_found >= max_results:
                            break

            except Exception as e:
                logger.debug(f"Error reading {file_path}: {e}")
                continue

            if matches_found >= max_results:
                break

        if not results:
            return {
                "content": [{"type": "text", "text": f"No matches found for: {pattern}"}],
                "isError": False,
                "metadata": {"files_searched": files_searched},
            }

        result_text = "\n".join(results)
        if matches_found >= max_results:
            result_text += f"\n... (truncated, showing first {max_results} matches)"

        return {
            "content": [{"type": "text", "text": result_text}],
            "isError": False,
            "metadata": {
                "files_searched": files_searched,
                "matches_found": matches_found,
            },
        }

    except Exception as e:
        logger.error(f"Error in grep: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


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
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 100,
                },
            },
            "required": ["pattern"],
        },
        handler=grep_files,
    )


# =============================================================================
# LIST TOOL
# =============================================================================


async def list_directory(
    path: str = ".",
    recursive: bool = False,
    include_hidden: bool = False,
    detailed: bool = False,
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
        _workspace_dir: Workspace directory

    Returns:
        Formatted directory listing
    """
    try:
        resolved = _resolve_path(path, _workspace_dir)

        if not resolved.exists():
            return {
                "content": [{"type": "text", "text": f"Error: Path not found: {path}"}],
                "isError": True,
            }

        if resolved.is_file():
            # Single file - return file info
            stat = resolved.stat()
            size_str = _format_size(stat.st_size)
            mtime = _format_mtime(stat.st_mtime)

            return {
                "content": [{"type": "text", "text": f"📄 {resolved.name} ({size_str}, {mtime})"}],
                "isError": False,
            }

        # It's a directory - list contents
        entries = []

        if recursive:
            # Recursive listing using rglob
            pattern = "**/*" if include_hidden else "*"
            items = sorted(resolved.rglob(pattern), key=lambda p: (not p.name.startswith("."), p.name.lower()))
        else:
            # Non-recursive
            items = sorted(
                resolved.iterdir(),
                key=lambda p: (not p.name.startswith("."), p.name.lower()),
            )

        if not items:
            return {
                "content": [{"type": "text", "text": f"📁 Empty directory: {path}"}],
                "isError": False,
            }

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
            return {
                "content": [{"type": "text", "text": f"📁 Empty directory: {path}"}],
                "isError": False,
            }

        header = f"📁 Listing: {path}"
        if recursive:
            header += " (recursive)"
        if include_hidden:
            header += " (including hidden)"

        result = f"{header}\n" + "\n".join(entries)

        if recursive and len(entries) > 50:
            result += f"\n... ({len(entries)} total entries)"

        return {
            "content": [{"type": "text", "text": result}],
            "isError": False,
            "metadata": {"total_entries": len(entries)},
        }

    except Exception as e:
        logger.error(f"Error listing directory: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


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

        if not resolved.exists():
            return {
                "content": [{"type": "text", "text": f"Error: File not found: {file_path}"}],
                "isError": True,
            }

        if not resolved.is_file():
            return {
                "content": [{"type": "text", "text": f"Error: Not a file: {file_path}"}],
                "isError": True,
            }

        # Read original file
        async with aiofiles.open(resolved, "r", encoding="utf-8") as f:
            original_lines = await f.readlines()

        # Parse patch
        parsed_hunks = _parse_unified_diff(patch, strip)
        if not parsed_hunks:
            return {
                "content": [{"type": "text", "text": "Error: Invalid patch format or no hunks found"}],
                "isError": True,
            }

        # Apply hunks to file content
        new_lines, failed_hunks = _apply_hunks(original_lines, parsed_hunks)

        if failed_hunks:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: Patch application failed. {len(failed_hunks)} hunks could not be applied.",
                    }
                ],
                "isError": True,
                "metadata": {"failed_hunks": failed_hunks},
            }

        # Write patched content
        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.writelines(new_lines)

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Successfully applied patch to {file_path} ({len(parsed_hunks)} hunks)",
                }
            ],
            "isError": False,
            "metadata": {"hunks_applied": len(parsed_hunks)},
        }

    except ValueError as e:
        # Path security error
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }
    except Exception as e:
        logger.error(f"Error applying patch: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def _parse_unified_diff(patch_content: str, strip: int = 0) -> list:
    """
    Parse unified diff format patch into hunks.

    Args:
        patch_content: Unified diff patch content
        strip: Number of path components to strip

    Returns:
        List of hunk dictionaries
    """
    hunks = []
    lines = patch_content.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for hunk header: @@ -old_start,old_count +new_start,new_count @@
        if line.startswith("@@"):
            try:
                # Parse hunk header
                header = line
                # Extract -old_start,old_count +new_start,new_count
                parts = header.split("@@")[1].strip().split()
                old_range = parts[0]  # -old_start,old_count
                new_range = parts[1]  # +new_start,new_count

                old_start = int(old_range.split(",")[0].lstrip("-"))
                old_count = int(old_range.split(",")[1]) if "," in old_range else 1
                new_start = int(new_range.split(",")[0].lstrip("+"))
                new_count = int(new_range.split(",")[1]) if "," in new_range else 1

                # Collect hunk lines
                i += 1
                hunk_lines = []
                while i < len(lines):
                    hunk_line = lines[i]
                    if hunk_line.startswith("@@") or hunk_line.startswith("---") or hunk_line.startswith("+++"):
                        break  # Next hunk or new file

                    if hunk_line.startswith(" ") or hunk_line.startswith("+") or hunk_line.startswith("-"):
                        hunk_lines.append(hunk_line)
                    elif hunk_line == "\\":
                        # Handle "\ No newline at end of file"
                        pass
                    elif hunk_line.strip():  # Non-empty line not starting with +/-/space
                        # Could be context line or garbage, stop
                        if not hunk_line.startswith(" "):
                            # Unexpected format
                            break
                    i += 1

                hunks.append({
                    "old_start": old_start - 1,  # Convert to 0-based
                    "old_count": old_count,
                    "new_start": new_start - 1,  # Convert to 0-based
                    "new_count": new_count,
                    "lines": hunk_lines,
                })
                continue
            except (ValueError, IndexError):
                # Failed to parse hunk header, skip
                pass

        i += 1

    return hunks


def _apply_hunks(original_lines: list, hunks: list) -> tuple:
    """
    Apply hunks to file content.

    Args:
        original_lines: Original file lines
        hunks: List of parsed hunks

    Returns:
        Tuple of (new_lines, failed_hunks)
    """
    # Sort hunks by old_start (apply from bottom to top to avoid line number shifts)
    sorted_hunks = sorted(hunks, key=lambda h: h["old_start"], reverse=True)

    result_lines = original_lines.copy()
    failed_hunks = []

    for hunk in sorted_hunks:
        old_start = hunk["old_start"]
        old_count = hunk["old_count"]
        hunk_lines = hunk["lines"]

        # Check if old lines match (normalize by stripping newlines for comparison)
        old_lines_from_hunk = [line[1:].rstrip("\n") for line in hunk_lines if line.startswith(" ") or line.startswith("-")]
        actual_old_lines = [line.rstrip("\n") for line in result_lines[old_start:old_start + old_count]] if old_start < len(result_lines) else []

        if old_lines_from_hunk != actual_old_lines:
            failed_hunks.append(hunk)
            continue

        # Apply hunk: remove old lines, insert new lines
        # Remove old lines
        del result_lines[old_start:old_start + old_count]

        # Build new lines to insert
        new_lines = []
        for line in hunk_lines:
            if line.startswith(" ") or line.startswith("+"):
                new_lines.append(line[1:] + "\n")
            elif line == "\\ No newline at end of file":
                pass  # Special marker, no line to add

        # Insert new lines at old_start position
        for new_line in reversed(new_lines):
            result_lines.insert(old_start, new_line)

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
