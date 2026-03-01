"""Dependency management and plugin execution tools for MCP server.

Provides tools for installing packages, checking dependency availability,
and executing commands within isolated virtual environments.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import time
from typing import Any, Dict

from src.mcp_manager.installer import (
    _is_command_available,
)
from src.server.websocket_server import MCPTool

logger = logging.getLogger(__name__)

# Regex to validate pip package specifiers (name with optional version constraints).
# Allows: pandas, numpy>=2.0, requests[security]==2.31.0, my-pkg~=1.0
# Blocks: shell metacharacters like ;, &, |, $, `, (, ), etc.
_PIP_PKG_RE = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(\[[A-Za-z0-9,._-]+\])?"
    r"([><=!~]=?[A-Za-z0-9.*+!_-]+)*$"
)

# Regex to validate system package names (dpkg-compatible).
_SYSTEM_PKG_RE = re.compile(r"^[a-z0-9][a-z0-9.+\-]+$")

# Regex to validate npm package specifiers.
_NPM_PKG_RE = re.compile(r"^(@[a-z0-9._-]+/)?[a-z0-9._-]+(@[a-z0-9^~>=<.*-]+)?$")

# Maximum output size (4MB)
MAX_OUTPUT_SIZE = 4 * 1024 * 1024


def _validate_packages(
    packages_str: str,
    package_type: str,
) -> tuple[list[str], str | None]:
    """Parse and validate a comma-separated package list.

    Returns:
        Tuple of (validated_packages, error_message).
        error_message is None when validation passes.
    """
    raw = [p.strip() for p in packages_str.split(",") if p.strip()]
    if not raw:
        return [], "No packages specified"

    if package_type == "pip":
        pattern = _PIP_PKG_RE
    elif package_type in ("system", "apt"):
        pattern = _SYSTEM_PKG_RE
    elif package_type == "npm":
        pattern = _NPM_PKG_RE
    elif package_type == "command":
        # For command checks, just ensure no shell metacharacters
        pattern = re.compile(r"^[A-Za-z0-9._/-]+$")
    else:
        return [], f"Unsupported package_type: {package_type}"

    invalid = [p for p in raw if not pattern.match(p)]
    if invalid:
        return [], f"Invalid package name(s): {', '.join(invalid)}"

    return raw, None


async def _run_subprocess(
    cmd: str,
    cwd: str,
    timeout: int,
    env: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a subprocess with timeout, returning (stdout, stderr, returncode)."""
    run_env = {
        **os.environ,
        "HOME": cwd,
        "DEBIAN_FRONTEND": "noninteractive",
        "TERM": "xterm-256color",
    }
    if env:
        run_env.update(env)

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=run_env,
        start_new_session=True,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        await process.wait()
        raise

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    # Truncate oversized output
    if len(stdout_str) > MAX_OUTPUT_SIZE:
        stdout_str = stdout_str[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"
    if len(stderr_str) > MAX_OUTPUT_SIZE:
        stderr_str = stderr_str[:MAX_OUTPUT_SIZE] + "\n... (stderr truncated)"

    return stdout_str, stderr_str, process.returncode or 0


# =============================================================================
# DEPS_INSTALL TOOL
# =============================================================================


async def deps_install(
    packages: str,
    package_type: str = "pip",
    venv_path: str | None = None,
    timeout: int = 120,
    _workspace_dir: str = "/workspace",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Install packages into the sandbox environment.

    Args:
        packages: Comma-separated package specifiers (e.g. "pandas>=2.0,numpy")
        package_type: Package manager type: "pip" | "system" | "npm"
        venv_path: Optional path to a Python virtualenv for isolated installs
        timeout: Timeout in seconds (max 300)
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Installation results with status per package
    """
    start = time.monotonic()

    try:
        # Validate timeout
        timeout = min(max(10, timeout), 300)

        # Validate packages
        pkgs, err = _validate_packages(packages, package_type)
        if err:
            return {
                "content": [{"type": "text", "text": f"Error: {err}"}],
                "isError": True,
            }

        results: list[dict[str, Any]] = []
        errors: list[str] = []

        if package_type == "pip":
            pip_cmd = "pip"

            # Handle venv creation / selection
            if venv_path:
                if not os.path.isabs(venv_path):
                    venv_path = os.path.join(_workspace_dir, venv_path)

                if not os.path.exists(os.path.join(venv_path, "bin", "pip")):
                    logger.info(f"Creating venv at {venv_path}")
                    try:
                        await _run_subprocess(
                            f"python3 -m venv {venv_path}",
                            cwd=_workspace_dir,
                            timeout=60,
                        )
                    except asyncio.TimeoutError:
                        return {
                            "content": [
                                {"type": "text", "text": "Error: Timed out creating virtualenv"}
                            ],
                            "isError": True,
                        }

                pip_cmd = os.path.join(venv_path, "bin", "pip")

            # Install each package
            for pkg in pkgs:
                logger.info(f"Installing pip package: {pkg}")
                try:
                    stdout, stderr, rc = await _run_subprocess(
                        f"{pip_cmd} install {pkg}",
                        cwd=_workspace_dir,
                        timeout=timeout,
                    )
                    if rc == 0:
                        results.append({"package": pkg, "status": "installed"})
                    else:
                        msg = stderr.strip() or stdout.strip() or f"exit code {rc}"
                        results.append({"package": pkg, "status": "failed", "error": msg[:500]})
                        errors.append(f"{pkg}: {msg[:200]}")
                except asyncio.TimeoutError:
                    results.append({"package": pkg, "status": "timeout"})
                    errors.append(f"{pkg}: timed out after {timeout}s")

        elif package_type == "system":
            # Root check
            if os.geteuid() != 0:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: System package installation requires root privileges",
                        }
                    ],
                    "isError": True,
                }

            pkg_list = " ".join(pkgs)
            logger.info(f"Installing system packages: {pkg_list}")
            try:
                # Update package lists first
                await _run_subprocess(
                    "apt-get update -qq",
                    cwd=_workspace_dir,
                    timeout=60,
                )
                stdout, stderr, rc = await _run_subprocess(
                    f"apt-get install -y -qq {pkg_list}",
                    cwd=_workspace_dir,
                    timeout=timeout,
                )
                if rc == 0:
                    for pkg in pkgs:
                        results.append({"package": pkg, "status": "installed"})
                else:
                    msg = stderr.strip() or stdout.strip() or f"exit code {rc}"
                    for pkg in pkgs:
                        results.append({"package": pkg, "status": "failed", "error": msg[:500]})
                    errors.append(msg[:200])
            except asyncio.TimeoutError:
                for pkg in pkgs:
                    results.append({"package": pkg, "status": "timeout"})
                errors.append(f"System install timed out after {timeout}s")

        elif package_type == "npm":
            if not _is_command_available("npm"):
                return {
                    "content": [{"type": "text", "text": "Error: npm is not available"}],
                    "isError": True,
                }

            pkg_list = " ".join(pkgs)
            logger.info(f"Installing npm packages: {pkg_list}")
            try:
                stdout, stderr, rc = await _run_subprocess(
                    f"npm install -g {pkg_list}",
                    cwd=_workspace_dir,
                    timeout=timeout,
                )
                if rc == 0:
                    for pkg in pkgs:
                        results.append({"package": pkg, "status": "installed"})
                else:
                    msg = stderr.strip() or stdout.strip() or f"exit code {rc}"
                    for pkg in pkgs:
                        results.append({"package": pkg, "status": "failed", "error": msg[:500]})
                    errors.append(msg[:200])
            except asyncio.TimeoutError:
                for pkg in pkgs:
                    results.append({"package": pkg, "status": "timeout"})
                errors.append(f"npm install timed out after {timeout}s")

        else:
            return {
                "content": [
                    {"type": "text", "text": f"Error: Unsupported package_type: {package_type}"}
                ],
                "isError": True,
            }

        elapsed = time.monotonic() - start
        is_error = len(errors) > 0

        summary_parts = []
        installed = [r for r in results if r["status"] == "installed"]
        failed = [r for r in results if r["status"] != "installed"]
        summary_parts.append(f"Installed {len(installed)}/{len(results)} packages")
        if failed:
            summary_parts.append(f"Failed: {', '.join(r['package'] for r in failed)}")
        summary_parts.append(f"Duration: {elapsed:.1f}s")

        return {
            "content": [{"type": "text", "text": "\n".join(summary_parts)}],
            "isError": is_error,
            "metadata": {
                "results": results,
                "errors": errors,
                "duration_seconds": round(elapsed, 2),
                "package_type": package_type,
            },
        }

    except Exception as e:
        logger.error(f"Error in deps_install: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_deps_install_tool() -> MCPTool:
    """Create the deps_install tool."""
    return MCPTool(
        name="deps_install",
        description=(
            "Install packages into the sandbox environment. "
            "Supports pip (Python), system (apt-get), and npm packages. "
            "Optionally install pip packages into an isolated virtualenv."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "packages": {
                    "type": "string",
                    "description": (
                        "Comma-separated package specifiers "
                        '(e.g. "pandas>=2.0,numpy", "curl,wget", "@scope/pkg")'
                    ),
                },
                "package_type": {
                    "type": "string",
                    "description": 'Package manager type: "pip" | "system" | "npm"',
                    "default": "pip",
                    "enum": ["pip", "system", "npm"],
                },
                "venv_path": {
                    "type": "string",
                    "description": (
                        "Optional: path to a Python virtualenv for isolated installs. "
                        "Created automatically if it does not exist. Only used with pip."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120, max: 300)",
                    "default": 120,
                },
            },
            "required": ["packages"],
        },
        handler=deps_install,
    )


# =============================================================================
# DEPS_CHECK TOOL
# =============================================================================


async def deps_check(
    packages: str,
    package_type: str = "pip",
    venv_path: str | None = None,
    _workspace_dir: str = "/workspace",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Check whether packages are available in the environment.

    Args:
        packages: Comma-separated package names
        package_type: Check type: "pip" | "system" | "command"
        venv_path: Optional virtualenv path (only for pip checks)
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Availability status for each package
    """
    try:
        pkgs, err = _validate_packages(packages, package_type)
        if err:
            return {
                "content": [{"type": "text", "text": f"Error: {err}"}],
                "isError": True,
            }

        check_results: dict[str, dict[str, Any]] = {}

        if package_type == "pip":
            pip_cmd = "pip"
            if venv_path:
                if not os.path.isabs(venv_path):
                    venv_path = os.path.join(_workspace_dir, venv_path)
                pip_cmd = os.path.join(venv_path, "bin", "pip")
                if not os.path.exists(pip_cmd):
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error: Virtualenv not found at {venv_path}",
                            }
                        ],
                        "isError": True,
                    }

            for pkg in pkgs:
                try:
                    stdout, stderr, rc = await _run_subprocess(
                        f"{pip_cmd} show {pkg}",
                        cwd=_workspace_dir,
                        timeout=15,
                    )
                    if rc == 0:
                        # Extract version from pip show output
                        version = None
                        for line in stdout.splitlines():
                            if line.startswith("Version:"):
                                version = line.split(":", 1)[1].strip()
                                break
                        check_results[pkg] = {"available": True, "version": version}
                    else:
                        check_results[pkg] = {"available": False, "version": None}
                except asyncio.TimeoutError:
                    check_results[pkg] = {"available": False, "version": None, "error": "timeout"}

        elif package_type == "system":
            for pkg in pkgs:
                try:
                    stdout, stderr, rc = await _run_subprocess(
                        f"dpkg -l {pkg}",
                        cwd=_workspace_dir,
                        timeout=10,
                    )
                    if rc == 0 and "ii" in stdout:
                        # Parse version from dpkg output
                        version = None
                        for line in stdout.splitlines():
                            if line.startswith("ii"):
                                parts = line.split()
                                if len(parts) >= 3:
                                    version = parts[2]
                                break
                        check_results[pkg] = {"available": True, "version": version}
                    else:
                        check_results[pkg] = {"available": False, "version": None}
                except asyncio.TimeoutError:
                    check_results[pkg] = {"available": False, "version": None, "error": "timeout"}

        elif package_type == "command":
            for pkg in pkgs:
                path = shutil.which(pkg)
                if path:
                    check_results[pkg] = {"available": True, "version": None, "path": path}
                else:
                    check_results[pkg] = {"available": False, "version": None}

        else:
            return {
                "content": [
                    {"type": "text", "text": f"Error: Unsupported package_type: {package_type}"}
                ],
                "isError": True,
            }

        # Format output
        lines = []
        all_available = True
        for name, info in check_results.items():
            status = "available" if info["available"] else "missing"
            version_str = f" (v{info['version']})" if info.get("version") else ""
            lines.append(f"  {name}: {status}{version_str}")
            if not info["available"]:
                all_available = False

        summary = "All packages available" if all_available else "Some packages missing"
        output = f"{summary}\n" + "\n".join(lines)

        return {
            "content": [{"type": "text", "text": output}],
            "isError": False,
            "metadata": {"results": check_results},
        }

    except Exception as e:
        logger.error(f"Error in deps_check: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_deps_check_tool() -> MCPTool:
    """Create the deps_check tool."""
    return MCPTool(
        name="deps_check",
        description=(
            "Check whether packages are available in the sandbox environment. "
            "Supports pip packages, system (dpkg) packages, and command availability checks."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "packages": {
                    "type": "string",
                    "description": 'Comma-separated package names (e.g. "pandas,numpy,requests")',
                },
                "package_type": {
                    "type": "string",
                    "description": 'Check type: "pip" | "system" | "command"',
                    "default": "pip",
                    "enum": ["pip", "system", "command"],
                },
                "venv_path": {
                    "type": "string",
                    "description": "Optional: virtualenv path for pip checks",
                },
            },
            "required": ["packages"],
        },
        handler=deps_check,
    )


# =============================================================================
# PLUGIN_TOOL_EXEC TOOL
# =============================================================================


async def plugin_tool_exec(
    command: str,
    venv_path: str | None = None,
    timeout: int = 60,
    env: str | None = None,
    _workspace_dir: str = "/workspace",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Execute a command, optionally within a virtualenv context.

    Args:
        command: Shell command to execute
        venv_path: Optional virtualenv path (prepends bin/ to PATH)
        timeout: Timeout in seconds (max 300)
        env: Optional JSON-encoded dict of extra environment variables
        _workspace_dir: Workspace directory (injected by server)

    Returns:
        Command output, exit code, and duration
    """
    start = time.monotonic()

    try:
        # Validate timeout
        timeout = min(max(1, timeout), 300)

        # Parse extra env vars
        extra_env: dict[str, str] = {}
        if env:
            try:
                parsed = json.loads(env)
                if not isinstance(parsed, dict):
                    return {
                        "content": [{"type": "text", "text": "Error: env must be a JSON object"}],
                        "isError": True,
                    }
                extra_env = {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError as e:
                return {
                    "content": [
                        {"type": "text", "text": f"Error: Invalid JSON in env parameter: {e}"}
                    ],
                    "isError": True,
                }

        # Build PATH with venv if provided
        if venv_path:
            if not os.path.isabs(venv_path):
                venv_path = os.path.join(_workspace_dir, venv_path)

            venv_bin = os.path.join(venv_path, "bin")
            if not os.path.isdir(venv_bin):
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error: Virtualenv bin directory not found: {venv_bin}",
                        }
                    ],
                    "isError": True,
                }

            current_path = os.environ.get("PATH", "/usr/bin:/bin")
            extra_env["PATH"] = f"{venv_bin}:{current_path}"
            extra_env["VIRTUAL_ENV"] = venv_path

        logger.info(f"Executing plugin command: {command[:100]}... (timeout={timeout}s)")

        try:
            stdout, stderr, rc = await _run_subprocess(
                command,
                cwd=_workspace_dir,
                timeout=timeout,
                env=extra_env if extra_env else None,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: Command timed out after {timeout}s",
                    }
                ],
                "isError": True,
                "metadata": {
                    "exit_code": -1,
                    "duration_seconds": round(elapsed, 2),
                    "timed_out": True,
                },
            }

        elapsed = time.monotonic() - start

        # Format output
        output_parts = []
        if stdout.strip():
            output_parts.append(stdout.rstrip())
        if stderr.strip():
            if output_parts:
                output_parts.append("\n--- stderr ---")
            output_parts.append(stderr.rstrip())
        if not output_parts:
            output_parts.append("(no output)")

        output = "\n".join(output_parts)
        is_error = rc != 0

        if is_error:
            output = f"Exit code: {rc}\n{output}"

        return {
            "content": [{"type": "text", "text": output}],
            "isError": is_error,
            "metadata": {
                "exit_code": rc,
                "duration_seconds": round(elapsed, 2),
                "working_dir": _workspace_dir,
                "venv_path": venv_path,
            },
        }

    except Exception as e:
        logger.error(f"Error in plugin_tool_exec: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True,
        }


def create_plugin_tool_exec_tool() -> MCPTool:
    """Create the plugin_tool_exec tool."""
    return MCPTool(
        name="plugin_tool_exec",
        description=(
            "Execute a shell command, optionally within a virtualenv context. "
            "Useful for running plugin scripts or tools installed in isolated environments."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "venv_path": {
                    "type": "string",
                    "description": (
                        "Optional: virtualenv path. "
                        "Prepends venv/bin to PATH for command resolution."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 60, max: 300)",
                    "default": 60,
                },
                "env": {
                    "type": "string",
                    "description": (
                        "Optional: JSON-encoded dict of extra environment variables "
                        '(e.g. \'{"MY_VAR": "value"}\')'
                    ),
                },
            },
            "required": ["command"],
        },
        handler=plugin_tool_exec,
    )
