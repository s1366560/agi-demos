"""Bash command execution tool for MCP server.

Provides secure command execution within the sandbox environment.
"""

import asyncio
import logging
import os
import signal
from typing import Any, Dict, Optional

from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)

# Commands that are blocked for security
BLOCKED_COMMANDS = {
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",  # Fork bomb
}

# Maximum output size (16MB)
MAX_OUTPUT_SIZE = 16 * 1024 * 1024

# Default timeout (5 minutes)
DEFAULT_TIMEOUT = 300


async def execute_bash(
    command: str,
    timeout: int = DEFAULT_TIMEOUT,
    working_dir: Optional[str] = None,
    _workspace_dir: str = "/workspace",
    **kwargs,
) -> Dict[str, Any]:
    """
    Execute a bash command.

    Args:
        command: Command to execute
        timeout: Timeout in seconds (max 600)
        working_dir: Working directory (default: workspace)
        _workspace_dir: Workspace directory

    Returns:
        Command output
    """
    try:
        # Security check: block dangerous commands
        cmd_lower = command.lower().strip()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return {
                    "content": [
                        {"type": "text", "text": f"Error: Command blocked for security: {command}"}
                    ],
                    "isError": True,
                }

        # Validate timeout
        timeout = min(max(1, timeout), 600)

        # Set working directory
        if working_dir:
            # Resolve relative to workspace
            if not os.path.isabs(working_dir):
                cwd = os.path.join(_workspace_dir, working_dir)
            else:
                cwd = working_dir
                # Security: ensure within workspace
                if not cwd.startswith(_workspace_dir):
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": "Error: Working directory must be within workspace",
                            }
                        ],
                        "isError": True,
                    }
        else:
            cwd = _workspace_dir

        # Ensure working directory exists, or use a fallback
        try:
            os.makedirs(cwd, exist_ok=True)
        except (OSError, PermissionError):
            # If we can't create the workspace, check if it exists
            if not os.path.exists(cwd):
                # Fallback to current directory if workspace is unavailable
                cwd = os.getcwd()
                logger.warning(f"Workspace {_workspace_dir} unavailable, using {cwd}")
            # If it exists but we can't create it, we'll try to use it anyway

        logger.info(f"Executing: {command[:100]}... (timeout={timeout}s, cwd={cwd})")

        # Create subprocess with sanitized environment
        # Start from os.environ but override path-related variables to prevent host path leakage
        sanitized_env = {
            **os.environ,
            # Override path-related variables to sandbox workspace
            "HOME": _workspace_dir,
            "PWD": cwd,
            "OLDPWD": cwd,
            "TERM": "xterm-256color",
            # Preserve DEBIAN_FRONTEND for non-interactive apt commands
            "DEBIAN_FRONTEND": os.environ.get("DEBIAN_FRONTEND", "noninteractive"),
        }
        # Remove any variables that might contain host paths
        for var in ["HOST_PATH", "PROJECT_PATH", "WORKSPACE_PATH"]:
            sanitized_env.pop(var, None)

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=sanitized_env,
            start_new_session=True,  # Own process group so we can kill all children
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            # Kill entire process group (shell + all children including backgrounded)
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                process.kill()
            await process.wait()
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: Command execution timed out after {timeout}s limit",
                    }
                ],
                "isError": True,
            }

        # Decode output
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        # Truncate if too large
        if len(stdout_str) > MAX_OUTPUT_SIZE:
            stdout_str = stdout_str[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
        if len(stderr_str) > MAX_OUTPUT_SIZE:
            stderr_str = stderr_str[:MAX_OUTPUT_SIZE] + "\n... (stderr truncated)"

        # Format output
        output_parts = []

        if stdout_str.strip():
            output_parts.append(stdout_str.rstrip())

        if stderr_str.strip():
            if output_parts:
                output_parts.append("\n--- stderr ---")
            output_parts.append(stderr_str.rstrip())

        if not output_parts:
            output_parts.append("(no output)")

        output = "\n".join(output_parts)

        # Check exit code
        is_error = process.returncode != 0

        if is_error:
            output = f"Exit code: {process.returncode}\n{output}"

        return {
            "content": [{"type": "text", "text": output}],
            "isError": is_error,
            "metadata": {
                "exit_code": process.returncode,
                "working_dir": cwd,
            },
        }

    except Exception as e:
        logger.error(f"Error executing command: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_bash_tool() -> MCPTool:
    """Create the bash tool."""
    return MCPTool(
        name="bash",
        description="Execute a bash command in the sandbox. Commands run in the workspace directory by default.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 300, max: 600)",
                    "default": 300,
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for command execution",
                },
            },
            "required": ["command"],
        },
        handler=execute_bash,
    )
