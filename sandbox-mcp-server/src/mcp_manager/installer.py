"""Package installer for MCP servers.

Handles detection and installation of MCP server packages
using npm, pip, or uvx depending on the package type.
"""

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class PackageManager(str, Enum):
    """Supported package managers."""

    NPM = "npm"
    PIP = "pip"
    UVX = "uvx"
    PIPX = "pipx"


@dataclass
class InstallResult:
    """Result of a package installation."""

    success: bool
    package_manager: Optional[PackageManager] = None
    installed_command: Optional[str] = None
    error: Optional[str] = None
    output: str = ""


def _detect_package_manager(command: str) -> Optional[PackageManager]:
    """Detect which package manager to use based on the command.

    Args:
        command: The command string from MCP server transport config.

    Returns:
        Detected package manager or None if command is a direct path.
    """
    cmd_parts = command.strip().split()
    if not cmd_parts:
        return None

    base_cmd = cmd_parts[0]

    if base_cmd in ("npx", "npm"):
        return PackageManager.NPM
    if base_cmd == "uvx":
        return PackageManager.UVX
    if base_cmd == "pipx":
        return PackageManager.PIPX
    if base_cmd in ("pip", "pip3", "python", "python3"):
        return PackageManager.PIP

    return None


def _is_command_available(command: str) -> bool:
    """Check if a command is available on the system."""
    base_cmd = command.strip().split()[0]
    return shutil.which(base_cmd) is not None


async def install_package(
    command: str,
    args: List[str],
    env: Optional[Dict[str, str]] = None,
    timeout: int = 120,
) -> InstallResult:
    """Install an MCP server package if needed.

    For npx commands, npm packages are installed globally.
    For pip/uvx commands, packages are installed in the sandbox environment.
    If the command is already available, installation is skipped.

    Args:
        command: The command to run the MCP server.
        args: Command arguments.
        env: Environment variables.
        timeout: Installation timeout in seconds.

    Returns:
        InstallResult with success status and details.
    """
    pkg_manager = _detect_package_manager(command)
    cmd_parts = command.strip().split()
    base_cmd = cmd_parts[0]

    if pkg_manager is None:
        if _is_command_available(command):
            return InstallResult(
                success=True,
                installed_command=command,
                output="Command already available",
            )
        return InstallResult(
            success=False,
            error=f"Command not found: {base_cmd}",
        )

    if pkg_manager == PackageManager.NPM:
        return await _install_npm(cmd_parts, args, timeout)
    if pkg_manager == PackageManager.UVX:
        return await _install_uvx(cmd_parts, args, timeout)
    if pkg_manager == PackageManager.PIPX:
        return await _install_pipx(cmd_parts, args, timeout)
    if pkg_manager == PackageManager.PIP:
        return await _install_pip(cmd_parts, args, timeout)

    return InstallResult(success=False, error=f"Unsupported package manager: {pkg_manager}")


async def _run_install_command(
    install_cmd: str,
    timeout: int,
    pkg_manager: PackageManager,
) -> InstallResult:
    """Run an installation command and return the result."""
    logger.info(f"Installing: {install_cmd}")
    try:
        process = await asyncio.create_subprocess_shell(
            install_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        output = stdout.decode("utf-8", errors="replace")
        err_output = stderr.decode("utf-8", errors="replace")

        if process.returncode != 0:
            return InstallResult(
                success=False,
                package_manager=pkg_manager,
                error=f"Installation failed (exit {process.returncode}): {err_output}",
                output=output,
            )

        return InstallResult(
            success=True,
            package_manager=pkg_manager,
            output=output,
        )

    except asyncio.TimeoutError:
        return InstallResult(
            success=False,
            package_manager=pkg_manager,
            error=f"Installation timed out after {timeout}s",
        )
    except Exception as e:
        return InstallResult(
            success=False,
            package_manager=pkg_manager,
            error=f"Installation error: {str(e)}",
        )


async def _install_npm(
    cmd_parts: List[str],
    args: List[str],
    timeout: int,
) -> InstallResult:
    """Install npm/npx package globally."""
    # For npx commands like: npx @modelcontextprotocol/server-filesystem
    # We need to install the package globally first
    if cmd_parts[0] == "npx":
        # The package name is typically the first non-flag argument after npx
        pkg_name = None
        for part in cmd_parts[1:] + args:
            if not part.startswith("-"):
                pkg_name = part
                break

        if not pkg_name:
            return InstallResult(success=False, error="Cannot determine npm package name")

        install_cmd = f"npm install -g {pkg_name}"
        result = await _run_install_command(install_cmd, timeout, PackageManager.NPM)
        if result.success:
            result.installed_command = " ".join(cmd_parts)
        return result

    return InstallResult(
        success=True,
        package_manager=PackageManager.NPM,
        installed_command=" ".join(cmd_parts),
        output="npm command available",
    )


async def _install_uvx(
    cmd_parts: List[str],
    args: List[str],
    timeout: int,
) -> InstallResult:
    """Install uvx package."""
    # uvx runs packages in isolated environments, no pre-install needed
    if not _is_command_available("uvx"):
        return InstallResult(
            success=False,
            package_manager=PackageManager.UVX,
            error="uvx not available in sandbox",
        )
    return InstallResult(
        success=True,
        package_manager=PackageManager.UVX,
        installed_command=" ".join(cmd_parts),
        output="uvx available, packages run in isolated environments",
    )


async def _install_pipx(
    cmd_parts: List[str],
    args: List[str],
    timeout: int,
) -> InstallResult:
    """Install pipx package."""
    if not _is_command_available("pipx"):
        return InstallResult(
            success=False,
            package_manager=PackageManager.PIPX,
            error="pipx not available in sandbox",
        )
    return InstallResult(
        success=True,
        package_manager=PackageManager.PIPX,
        installed_command=" ".join(cmd_parts),
        output="pipx available",
    )


async def _install_pip(
    cmd_parts: List[str],
    args: List[str],
    timeout: int,
) -> InstallResult:
    """Install pip package."""
    # For: python -m module_name or pip install package_name
    if cmd_parts[0] in ("python", "python3") and "-m" in cmd_parts:
        m_index = cmd_parts.index("-m")
        if m_index + 1 < len(cmd_parts):
            module_name = cmd_parts[m_index + 1]
            install_cmd = f"pip install {module_name}"
            result = await _run_install_command(install_cmd, timeout, PackageManager.PIP)
            if result.success:
                result.installed_command = " ".join(cmd_parts)
            return result

    return InstallResult(
        success=True,
        package_manager=PackageManager.PIP,
        installed_command=" ".join(cmd_parts),
        output="pip command available",
    )
