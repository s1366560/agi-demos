"""Edit tools for MCP server.

Provides batch editing and edit preview capabilities.
"""

import difflib
import logging
from typing import Any, Dict, List

import aiofiles

from src.server.websocket_server import MCPTool
from src.tools.file_tools import _resolve_path

logger = logging.getLogger(__name__)


# =============================================================================
# BATCH EDIT TOOL
# =============================================================================


async def batch_edit(
    edits: List[Dict[str, str]],
    dry_run: bool = False,
    stop_on_error: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Apply multiple edits across multiple files.

    Args:
        edits: List of edit specifications, each with file_path, old_string, new_string
        dry_run: If True, preview changes without applying
        stop_on_error: Stop on first error
        _workspace_dir: Workspace directory

    Returns:
        Batch edit result
    """
    try:
        results = []
        successful = 0
        failed = 0

        for edit_spec in edits:
            file_path = edit_spec.get("file_path")
            old_string = edit_spec.get("old_string")
            new_string = edit_spec.get("new_string")

            if not all([file_path, old_string, new_string is not None]):
                failed += 1
                results.append(
                    {
                        "file": file_path,
                        "status": "error",
                        "message": "Missing required fields",
                    }
                )
                if stop_on_error:
                    break
                continue

            try:
                full_path = _resolve_path(file_path, _workspace_dir)

                if not full_path.exists():
                    failed += 1
                    results.append(
                        {
                            "file": file_path,
                            "status": "error",
                            "message": "File not found",
                        }
                    )
                    if stop_on_error:
                        break
                    continue

                content = full_path.read_text(encoding="utf-8")

                if old_string not in content:
                    failed += 1
                    results.append(
                        {
                            "file": file_path,
                            "status": "error",
                            "message": "Old string not found",
                        }
                    )
                    if stop_on_error:
                        break
                    continue

                # Check for uniqueness
                occurrences = content.count(old_string)
                if occurrences > 1 and edit_spec.get("replace_all", False) is False:
                    failed += 1
                    results.append(
                        {
                            "file": file_path,
                            "status": "error",
                            "message": f"String appears {occurrences} times, use replace_all=true",
                        }
                    )
                    if stop_on_error:
                        break
                    continue

                # Apply edit
                new_content = content.replace(old_string, new_string)

                if not dry_run:
                    async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                        await f.write(new_content)

                successful += 1
                results.append(
                    {
                        "file": file_path,
                        "status": "success",
                        "message": "Applied successfully",
                    }
                )

            except Exception as e:
                failed += 1
                results.append(
                    {
                        "file": file_path,
                        "status": "error",
                        "message": str(e),
                    }
                )
                if stop_on_error:
                    break

        lines = [
            f"Batch edit complete: {successful} successful, {failed} failed",
        ]
        for r in results:
            lines.append(f"  {r['file']}: {r['status']}")

        return {
            "content": [{"type": "text", "text": "\n".join(lines)}],
            "isError": False,
            "metadata": {
                "total": len(edits),
                "successful": successful,
                "failed": failed,
                "dry_run": dry_run,
                "results": results,
            },
        }

    except Exception as e:
        logger.error(f"Error in batch_edit: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_batch_edit_tool() -> MCPTool:
    """Create the batch edit tool."""
    return MCPTool(
        name="batch_edit",
        description="Apply multiple edits across multiple files. Supports dry-run mode and error handling.",
        input_schema={
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                        },
                        "required": ["file_path", "old_string", "new_string"],
                    },
                    "description": "List of edit specifications",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview changes without applying",
                    "default": False,
                },
                "stop_on_error": {
                    "type": "boolean",
                    "description": "Stop on first error",
                    "default": False,
                },
            },
            "required": ["edits"],
        },
        handler=batch_edit,
    )


# =============================================================================
# PREVIEW EDIT TOOL
# =============================================================================


async def preview_edit(
    file_path: str,
    old_string: str,
    new_string: str,
    context_lines: int = 3,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Preview an edit before applying it.

    Shows a unified diff of the changes that would be made.

    Args:
        file_path: Path to the file
        old_string: Text to replace
        new_string: Replacement text
        context_lines: Number of context lines to show
        _workspace_dir: Workspace directory

    Returns:
        Preview with diff
    """
    try:
        full_path = _resolve_path(file_path, _workspace_dir)

        if not full_path.exists():
            return {
                "content": [{"type": "text", "text": f"File not found: {file_path}"}],
                "isError": True,
            }

        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        if old_string not in content:
            return {
                "content": [{"type": "text", "text": "Old string not found in file"}],
                "isError": False,
                "metadata": {
                    "changes_found": 0,
                    "file_path": file_path,
                },
            }

        # Apply change to generate diff
        new_content = content.replace(old_string, new_string)
        new_lines = new_content.splitlines(keepends=True)

        # Generate unified diff
        diff = list(
            difflib.unified_diff(
                lines,
                new_lines,
                fromfile=f"a/{file_path}",
                tofile=f"b/{file_path}",
                n=context_lines,
                lineterm="",
            )
        )

        if not diff:
            return {
                "content": [{"type": "text", "text": "No changes to show"}],
                "isError": False,
                "metadata": {
                    "changes_found": 0,
                    "file_path": file_path,
                },
            }

        # Format diff output
        output = []
        changes_found = 0

        for line in diff:
            output.append(line.rstrip())
            if line.startswith("+") or line.startswith("-"):
                changes_found += 1

        # Add context info
        result_lines = [
            f"Preview for {file_path}:",
            f"Old string: {old_string[:50]}...",
            f"New string: {new_string[:50]}...",
            f"Changes: {changes_found} lines affected",
            "",
            "--- Diff ---",
        ]
        result_lines.extend(output)

        # Truncate if too long
        if len(result_lines) > 200:
            result_lines = result_lines[:200]
            result_lines.append("... (truncated)")

        return {
            "content": [{"type": "text", "text": "\n".join(result_lines)}],
            "isError": False,
            "metadata": {
                "changes_found": changes_found,
                "file_path": file_path,
                "preview": diff,
            },
        }

    except Exception as e:
        logger.error(f"Error in preview_edit: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_preview_edit_tool() -> MCPTool:
    """Create the preview edit tool."""
    return MCPTool(
        name="preview_edit",
        description="Preview an edit before applying it. Shows unified diff of the changes.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file",
                },
                "old_string": {
                    "type": "string",
                    "description": "Text to replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines to show in diff",
                    "default": 3,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        handler=preview_edit,
    )


# =============================================================================
# GET ALL EDIT TOOLS
# =============================================================================


def get_edit_tools() -> List[MCPTool]:
    """Get all edit tool definitions."""
    return [
        create_batch_edit_tool(),
        create_preview_edit_tool(),
    ]
