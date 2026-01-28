"""Edit tools for MCP server.

Provides AST-based editing, batch editing, and edit preview capabilities.
"""

import ast
import asyncio
import difflib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiofiles

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)


# =============================================================================
# EDIT BY AST TOOL
# =============================================================================


async def edit_by_ast(
    file_path: str,
    target_type: str,
    target_name: str,
    operation: str,
    new_value: str,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Perform AST-based editing on a Python file.

    Supports operations:
    - rename: Rename a class, function, or method
    - delete: Delete a class, function, or method
    - modify: Modify a decorator or base class

    Args:
        file_path: Path to the Python file
        target_type: Type of target (class, function, method)
        target_name: Name of the target
        operation: Operation (rename, delete, modify)
        new_value: New value for the operation
        _workspace_dir: Workspace directory

    Returns:
        Edit result
    """
    try:
        full_path = Path(_workspace_dir) / file_path

        if not full_path.exists():
            return {
                "content": [{"type": "text", "text": f"File not found: {file_path}"}],
                "isError": True,
            }

        content = full_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(full_path))

        modified = False
        class_context = None  # Track if we're inside a class

        class NameTransformer(ast.NodeTransformer):
            """AST node transformer for renaming."""

            def __init__(self, old_name: str, new_name: str):
                self.old_name = old_name
                self.new_name = new_name
                self.target_type = target_type
                self.modified = False

            def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
                # Check if this is the target class
                if target_type == "class" and node.name == self.old_name:
                    node.name = self.new_name
                    self.modified = True
                return node

            def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
                # Check if this is the target function
                if target_type == "function" and node.name == self.old_name:
                    node.name = self.new_name
                    self.modified = True
                return node

            def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
                # Check for references to the old name
                if isinstance(node.value, ast.Name) and node.value.id == self.old_name:
                    # Only rename if it's the direct attribute (not method call)
                    if node.attr == self.old_name:
                        return ast.Attribute(
                            ast.Name(self.new_name),
                            self.new_name
                        )
                return node

        # Apply transformation based on operation
        if operation == "rename":
            transformer = NameTransformer(target_name, new_value)
            new_tree = transformer.visit(tree)

            if transformer.modified:
                modified = True
                new_content = ast.unparse(new_tree)
            else:
                return {
                    "content": [{"type": "text", "text": f"Target '{target_name}' not found or operation not applicable"}],
                    "isError": False,
                    "metadata": {"modified": False},
                }

        elif operation == "delete":
            # Simplified delete - would need more sophisticated AST manipulation
            return {
                "content": [{"type": "text", "text": f"Delete operation not yet implemented"}],
                "isError": True,
            }

        else:
            return {
                "content": [{"type": "text", "text": f"Unknown operation: {operation}"}],
                "isError": True,
            }

        if modified:
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(new_content)

            return {
                "content": [{"type": "text", "text": f"Successfully edited {file_path}"}],
                "isError": False,
                "metadata": {"modified": True, "operation": operation},
            }

        return {
            "content": [{"type": "text", "text": f"No changes made to {file_path}"}],
            "isError": False,
            "metadata": {"modified": False},
        }

    except Exception as e:
        logger.error(f"Error in edit_by_ast: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_edit_by_ast_tool() -> MCPTool:
    """Create the edit by AST tool."""
    return MCPTool(
        name="edit_by_ast",
        description="Perform AST-based editing on Python files. Supports renaming classes, functions, and methods.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file",
                },
                "target_type": {
                    "type": "string",
                    "enum": ["class", "function", "method"],
                    "description": "Type of target to edit",
                },
                "target_name": {
                    "type": "string",
                    "description": "Current name of the target",
                },
                "operation": {
                    "type": "string",
                    "enum": ["rename", "delete"],
                    "description": "Operation to perform",
                },
                "new_value": {
                    "type": "string",
                    "description": "New value (for rename) or replacement value",
                },
            },
            "required": ["file_path", "target_type", "target_name", "operation", "new_value"],
        },
        handler=edit_by_ast,
    )


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
                results.append({
                    "file": file_path,
                    "status": "error",
                    "message": "Missing required fields",
                })
                if stop_on_error:
                    break
                continue

            try:
                full_path = Path(_workspace_dir) / file_path

                if not full_path.exists():
                    failed += 1
                    results.append({
                        "file": file_path,
                        "status": "error",
                        "message": "File not found",
                    })
                    if stop_on_error:
                        break
                    continue

                content = full_path.read_text(encoding="utf-8")

                if old_string not in content:
                    failed += 1
                    results.append({
                        "file": file_path,
                        "status": "error",
                        "message": "Old string not found",
                    })
                    if stop_on_error:
                        break
                    continue

                # Check for uniqueness
                occurrences = content.count(old_string)
                if occurrences > 1 and edit_spec.get("replace_all", False) is False:
                    failed += 1
                    results.append({
                        "file": file_path,
                        "status": "error",
                        "message": f"String appears {occurrences} times, use replace_all=true",
                    })
                    if stop_on_error:
                        break
                    continue

                # Apply edit
                new_content = content.replace(old_string, new_string)

                if not dry_run:
                    async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                        await f.write(new_content)

                successful += 1
                results.append({
                    "file": file_path,
                    "status": "success",
                    "message": "Applied successfully",
                })

            except Exception as e:
                failed += 1
                results.append({
                    "file": file_path,
                    "status": "error",
                    "message": str(e),
                })
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
        full_path = Path(_workspace_dir) / file_path

        if not full_path.exists():
            return {
                "content": [{"type": "text", "text": f"File not found: {file_path}"}],
                "isError": True,
            }

        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)

        if old_string not in content:
            return {
                "content": [{"type": "text", "text": f"Old string not found in file"}],
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
        diff = list(difflib.unified_diff(
            lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        ))

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
        result_lines.extend(diff)

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
        create_edit_by_ast_tool(),
        create_batch_edit_tool(),
        create_preview_edit_tool(),
    ]
