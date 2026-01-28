"""Git tools for MCP server.

Provides git diff, log, and commit message generation capabilities.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)


# =============================================================================
# GIT DIFF TOOL
# =============================================================================


async def git_diff(
    file_path: Optional[str] = None,
    cached: bool = False,
    context_lines: int = 3,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Get git diff for changes in the workspace.

    Args:
        file_path: Optional specific file to diff
        cached: Show staged changes instead of working directory
        context_lines: Number of context lines to show
        _workspace_dir: Workspace directory

    Returns:
        Git diff output
    """
    try:
        # Check if we're in a git repo
        git_dir = Path(_workspace_dir)
        if not (git_dir / ".git").exists():
            return {
                "content": [{"type": "text", "text": "Not a git repository"}],
                "isError": False,
                "metadata": {"files_changed": 0, "in_git_repo": False},
            }

        # Build git diff command
        cmd = ["git", "diff", f"-U{context_lines}"]
        if cached:
            cmd.append("--cached")
        if file_path:
            cmd.append(file_path)

        result = subprocess.run(
            cmd,
            cwd=_workspace_dir,
            capture_output=True,
            text=True,
        )

        # Parse diff output
        lines = result.stdout.split("\n")
        files_changed = 0
        hunks = []

        current_file = None
        for line in lines:
            if line.startswith("diff --git"):
                files_changed += 1
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[3].lstrip("b/")
            elif line.startswith("@@"):
                hunks.append(line)

        output_lines = []
        if not result.stdout.strip():
            output_lines.append("No changes to display.")
        else:
            output_lines.append(f"Files changed: {files_changed}")
            output_lines.append(f"Hunks: {len(hunks)}")
            output_lines.append("")
            output_lines.append("--- Diff ---")
            output_lines.extend(lines[:200])  # Limit output
            if len(lines) > 200:
                output_lines.append("... (truncated)")

        return {
            "content": [{"type": "text", "text": "\n".join(output_lines)}],
            "isError": False,
            "metadata": {
                "files_changed": files_changed,
                "hunks": len(hunks),
                "cached": cached,
                "in_git_repo": True,
            },
        }

    except Exception as e:
        logger.error(f"Error in git_diff: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_git_diff_tool() -> MCPTool:
    """Create the git diff tool."""
    return MCPTool(
        name="git_diff",
        description="Get git diff for changes in the workspace. Shows changes between working directory and last commit.",
        input_schema={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Optional specific file to diff",
                },
                "cached": {
                    "type": "boolean",
                    "description": "Show staged changes instead of working directory",
                    "default": False,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines to show",
                    "default": 3,
                },
            },
            "required": [],
        },
        handler=git_diff,
    )


# =============================================================================
# GIT LOG TOOL
# =============================================================================


async def git_log(
    max_count: int = 10,
    file_path: Optional[str] = None,
    since: Optional[str] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Get git log history.

    Args:
        max_count: Maximum number of commits to show
        file_path: Optional specific file to show history for
        since: Show commits since a specific date (e.g., "1 week ago")
        _workspace_dir: Workspace directory

    Returns:
        Git log output
    """
    try:
        # Check if we're in a git repo
        git_dir = Path(_workspace_dir)
        if not (git_dir / ".git").exists():
            return {
                "content": [{"type": "text", "text": "Not a git repository"}],
                "isError": False,
                "metadata": {"commit_count": 0, "in_git_repo": False},
            }

        # Build git log command
        cmd = [
            "git", "log",
            f"-{max_count}",
            "--pretty=format:%H|%an|%ae|%ad|%s",
            "--date=short",
        ]
        if since:
            cmd.append(f"--since={since}")
        if file_path:
            cmd.append("--")
            cmd.append(file_path)

        result = subprocess.run(
            cmd,
            cwd=_workspace_dir,
            capture_output=True,
            text=True,
        )

        # Parse log output
        commits = []
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []

        for line in lines:
            if "|" in line:
                parts = line.split("|", 4)
                if len(parts) == 5:
                    commits.append({
                        "hash": parts[0][:8],  # Short hash
                        "author": parts[1],
                        "email": parts[2],
                        "date": parts[3],
                        "message": parts[4],
                    })

        output_lines = [f"Found {len(commits)} commit(s):", ""]

        for commit in commits:
            output_lines.append(f"commit {commit['hash']}")
            output_lines.append(f"Author: {commit['author']} <{commit['email']}>")
            output_lines.append(f"Date: {commit['date']}")
            output_lines.append(f"    {commit['message']}")
            output_lines.append("")

        if not commits:
            output_lines.append("No commits found.")

        return {
            "content": [{"type": "text", "text": "\n".join(output_lines)}],
            "isError": False,
            "metadata": {
                "commit_count": len(commits),
                "commits": commits,
                "in_git_repo": True,
            },
        }

    except Exception as e:
        logger.error(f"Error in git_log: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_git_log_tool() -> MCPTool:
    """Create the git log tool."""
    return MCPTool(
        name="git_log",
        description="Get git log history. Shows commit history with author, date, and message.",
        input_schema={
            "type": "object",
            "properties": {
                "max_count": {
                    "type": "integer",
                    "description": "Maximum number of commits to show",
                    "default": 10,
                },
                "file_path": {
                    "type": "string",
                    "description": "Optional specific file to show history for",
                },
                "since": {
                    "type": "string",
                    "description": "Show commits since a specific date (e.g., '1 week ago')",
                },
            },
            "required": [],
        },
        handler=git_log,
    )


# =============================================================================
# GENERATE COMMIT TOOL
# =============================================================================


async def generate_commit(
    message: Optional[str] = None,
    auto_add: bool = False,
    dry_run: bool = False,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Generate a commit message and optionally create the commit.

    Args:
        message: Optional custom commit message
        auto_add: Automatically stage all changes before committing
        dry_run: Generate message without creating commit
        _workspace_dir: Workspace directory

    Returns:
        Commit result
    """
    try:
        # Check if we're in a git repo
        git_dir = Path(_workspace_dir)
        if not (git_dir / ".git").exists():
            return {
                "content": [{"type": "text", "text": "Not a git repository"}],
                "isError": False,
                "metadata": {"in_git_repo": False},
            }

        # Auto-add changes if requested
        if auto_add:
            subprocess.run(
                ["git", "add", "-A"],
                cwd=_workspace_dir,
                capture_output=True,
            )

        # Check if there are staged changes
        status_result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=_workspace_dir,
            capture_output=True,
            text=True,
        )

        staged_files = [f for f in status_result.stdout.strip().split("\n") if f]

        # Also check for unstaged changes for message generation
        unstaged_result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=_workspace_dir,
            capture_output=True,
            text=True,
        )
        unstaged_files = [f for f in unstaged_result.stdout.strip().split("\n") if f]

        # Use staged files if available, otherwise check unstaged for message generation
        files_for_message = staged_files if staged_files else unstaged_files

        if not files_for_message:
            return {
                "content": [{"type": "text", "text": "No changes to commit"}],
                "isError": False,
                "metadata": {
                    "staged_count": 0,
                    "dry_run": dry_run,
                    "commit_message": message,
                },
            }

        # Generate commit message if not provided
        if not message:
            # Simple message generation based on changes
            if len(files_for_message) == 1:
                file_name = files_for_message[0]
                if file_name.endswith(".py"):
                    message = f"Update {file_name}"
                elif file_name.endswith(".md"):
                    message = f"Update documentation in {file_name}"
                elif file_name.endswith(".txt"):
                    message = f"Modify {file_name}"
                else:
                    message = f"Update {file_name}"
            else:
                message = f"Update {len(files_for_message)} files"

            # Add common prefix based on file types
            py_files = [f for f in files_for_message if f.endswith(".py")]
            test_files = [f for f in files_for_message if "test" in f]
            doc_files = [f for f in files_for_message if f.endswith(".md")]

            if test_files and len(test_files) == len(files_for_message):
                message = f"test: {message}"
            elif doc_files and len(doc_files) == len(files_for_message):
                message = f"docs: {message}"
            elif py_files:
                message = f"feat: {message}"

        # Only create commit if we have staged files
        commit_result = None
        committed = False

        if staged_files and not dry_run:
            commit_result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=_workspace_dir,
                capture_output=True,
                text=True,
            )
            committed = commit_result.returncode == 0

        output_lines = [
            f"Commit message: {message}",
            f"Files affected: {len(files_for_message)}",
            f"Staged files: {len(staged_files)}",
            f"Dry run: {dry_run}",
        ]

        if not dry_run and staged_files:
            if committed:
                output_lines.append("Commit created successfully.")
            else:
                output_lines.append("Failed to create commit.")
        elif not staged_files:
            output_lines.append("Note: No staged changes. Stage files with 'git add' or use auto_add=True.")

        return {
            "content": [{"type": "text", "text": "\n".join(output_lines)}],
            "isError": False,
            "metadata": {
                "commit_message": message,
                "staged_count": len(staged_files),
                "unstaged_count": len(unstaged_files),
                "files_for_message": list(files_for_message),
                "dry_run": dry_run,
                "committed": committed,
            },
        }

    except Exception as e:
        logger.error(f"Error in generate_commit: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_generate_commit_tool() -> MCPTool:
    """Create the generate commit tool."""
    return MCPTool(
        name="generate_commit",
        description="Generate a commit message and optionally create the commit. Analyzes changes to create meaningful commit messages.",
        input_schema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Optional custom commit message",
                },
                "auto_add": {
                    "type": "boolean",
                    "description": "Automatically stage all changes before committing",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Generate message without creating commit",
                    "default": False,
                },
            },
            "required": [],
        },
        handler=generate_commit,
    )


# =============================================================================
# GET ALL GIT TOOLS
# =============================================================================


def get_git_tools() -> List[MCPTool]:
    """Get all git tool definitions."""
    return [
        create_git_diff_tool(),
        create_git_log_tool(),
        create_generate_commit_tool(),
    ]
