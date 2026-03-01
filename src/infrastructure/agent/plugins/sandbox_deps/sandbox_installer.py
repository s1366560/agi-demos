"""Host-side installer that drives dependency installation inside sandboxes.

This module runs on the HOST side.  It does NOT execute ``pip`` or ``apt``
directly.  Instead it calls the sandbox-side ``deps_install`` and
``deps_check`` MCP tools through a callable that abstracts the sandbox
adapter, keeping this component fully decoupled from infrastructure.

Tool response shape (MCP format)::

    {
        "content": [{"type": "text", "text": "<JSON payload>"}],
        "isError": false
    }
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .models import InstallRequest, InstallResult, RuntimeDependencies
from .security_gate import SecurityGate, ValidationResult

logger = logging.getLogger(__name__)


class SandboxDependencyInstaller:
    """Installs dependencies in sandbox containers via MCP tool calls.

    This runs on the HOST side. It does NOT directly execute pip/apt.
    Instead, it calls the sandbox-side ``deps_install`` and ``deps_check``
    MCP tools through a callable that abstracts the sandbox adapter.

    The callable signature matches UnifiedSandboxService.execute_tool::

        async def call_sandbox_tool(
            tool_name: str,
            arguments: dict[str, Any],
            timeout: float = 60.0,
        ) -> dict[str, Any]
    """

    def __init__(
        self,
        *,
        sandbox_tool_caller: Callable[..., Awaitable[dict[str, Any]]],
        security_gate: SecurityGate | None = None,
        default_timeout: float = 120.0,
    ) -> None:
        self._sandbox_tool_caller = sandbox_tool_caller
        self._security_gate = security_gate if security_gate is not None else SecurityGate()
        self._default_timeout = default_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def install(self, request: InstallRequest) -> InstallResult:
        """Install dependencies declared in *request* into the sandbox.

        Workflow:
            1. Validate the request through the :class:`SecurityGate`.
            2. Check which packages are already installed (``deps_check``).
            3. Install missing pip packages (``deps_install``).
            4. Install missing system packages (``deps_install``).
            5. Return an :class:`InstallResult` with installed / skipped / errors.
        """
        start = time.monotonic()
        deps = request.dependencies

        # -- Step 1: security validation ------------------------------------
        validation: ValidationResult = self._security_gate.validate_request(request)
        if not validation.valid:
            logger.warning(
                "Security gate rejected install for plugin=%s: %s",
                request.plugin_id,
                validation.errors,
            )
            return InstallResult(
                success=False,
                plugin_id=request.plugin_id,
                errors=validation.errors,
                duration_ms=self._elapsed_ms(start),
            )

        installed: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        # -- Step 2: check already-installed packages -----------------------
        try:
            already_installed = await self.check_installed(deps)
        except Exception:
            logger.exception(
                "Failed to check installed packages for plugin=%s",
                request.plugin_id,
            )
            already_installed = {}

        # -- Step 3: install missing pip packages ---------------------------
        missing_pip = tuple(
            pkg for pkg in deps.pip_packages if not already_installed.get(pkg, False)
        )
        if missing_pip:
            pip_result = await self._install_packages(
                packages=missing_pip,
                package_type="pip",
                plugin_id=request.plugin_id,
                installed_out=installed,
                errors_out=errors,
            )
            if not pip_result:
                logger.warning("Some pip packages failed for plugin=%s", request.plugin_id)
        pip_skipped = tuple(pkg for pkg in deps.pip_packages if already_installed.get(pkg, False))
        skipped.extend(pip_skipped)

        # -- Step 4: install missing system packages ------------------------
        missing_sys = tuple(
            pkg for pkg in deps.system_packages if not already_installed.get(pkg, False)
        )
        if missing_sys:
            sys_result = await self._install_packages(
                packages=missing_sys,
                package_type="system",
                plugin_id=request.plugin_id,
                installed_out=installed,
                errors_out=errors,
            )
            if not sys_result:
                logger.warning("Some system packages failed for plugin=%s", request.plugin_id)
        sys_skipped = tuple(
            pkg for pkg in deps.system_packages if already_installed.get(pkg, False)
        )
        skipped.extend(sys_skipped)

        success = len(errors) == 0
        result = InstallResult(
            success=success,
            plugin_id=request.plugin_id,
            installed_packages=tuple(installed),
            skipped_packages=tuple(skipped),
            errors=tuple(errors),
            duration_ms=self._elapsed_ms(start),
        )
        logger.info(
            "Install complete for plugin=%s success=%s installed=%d skipped=%d errors=%d "
            "duration_ms=%d",
            request.plugin_id,
            result.success,
            len(result.installed_packages),
            len(result.skipped_packages),
            len(result.errors),
            result.duration_ms,
        )
        return result

    async def check_installed(
        self,
        dependencies: RuntimeDependencies,
        venv_path: str | None = None,
    ) -> dict[str, bool]:
        """Check which packages from *dependencies* are already installed.

        Calls the ``deps_check`` MCP tool for pip and system packages
        separately, then merges results into a single mapping of
        ``package_name -> is_installed``.
        """
        result: dict[str, bool] = {}

        if dependencies.pip_packages:
            pip_status = await self._call_deps_check(
                packages=dependencies.pip_packages,
                package_type="pip",
                venv_path=venv_path,
            )
            result.update(self._parse_check_result(pip_status))

        if dependencies.system_packages:
            sys_status = await self._call_deps_check(
                packages=dependencies.system_packages,
                package_type="system",
                venv_path=venv_path,
            )
            result.update(self._parse_check_result(sys_status))

        return result

    # ------------------------------------------------------------------
    # Sandbox tool call helpers
    # ------------------------------------------------------------------

    async def _call_deps_install(
        self,
        packages: tuple[str, ...],
        package_type: str,
        venv_path: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Call the sandbox ``deps_install`` MCP tool.

        Args:
            packages: Package specifiers to install.
            package_type: ``"pip"`` or ``"system"``.
            venv_path: Optional virtual-env path inside the sandbox.
            timeout: Per-call timeout; falls back to *default_timeout*.

        Returns:
            Raw MCP tool response dict.
        """
        arguments: dict[str, Any] = {
            "packages": ",".join(packages),
            "package_type": package_type,
        }
        if venv_path is not None:
            arguments["venv_path"] = venv_path

        effective_timeout = timeout if timeout is not None else self._default_timeout
        logger.debug(
            "Calling deps_install type=%s packages=%s timeout=%.1f",
            package_type,
            packages,
            effective_timeout,
        )
        return await self._sandbox_tool_caller("deps_install", arguments, effective_timeout)

    async def _call_deps_check(
        self,
        packages: tuple[str, ...],
        package_type: str,
        venv_path: str | None = None,
    ) -> dict[str, Any]:
        """Call the sandbox ``deps_check`` MCP tool.

        Args:
            packages: Package names to check.
            package_type: ``"pip"`` or ``"system"``.
            venv_path: Optional virtual-env path inside the sandbox.

        Returns:
            Raw MCP tool response dict.
        """
        arguments: dict[str, Any] = {
            "packages": ",".join(packages),
            "package_type": package_type,
        }
        if venv_path is not None:
            arguments["venv_path"] = venv_path

        logger.debug("Calling deps_check type=%s packages=%s", package_type, packages)
        return await self._sandbox_tool_caller("deps_check", arguments, self._default_timeout)

    async def _parse_tool_result(self, result: dict[str, Any]) -> tuple[bool, str]:
        """Extract success flag and text payload from an MCP tool response.

        Tool results have shape::

            {"content": [{"type": "text", "text": "..."}], "isError": bool}

        Returns:
            A ``(success, text)`` tuple.  *success* is ``False`` when the
            tool reported an error or the response could not be parsed.
        """
        is_error = result.get("isError", False)
        content_items: list[dict[str, Any]] = result.get("content", [])

        text_parts: list[str] = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))

        text = "\n".join(text_parts) if text_parts else ""
        return (not is_error, text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _install_packages(
        self,
        *,
        packages: tuple[str, ...],
        package_type: str,
        plugin_id: str,
        installed_out: list[str],
        errors_out: list[str],
    ) -> bool:
        """Install *packages* via ``deps_install`` and collect results.

        Appends successfully installed package names to *installed_out* and
        any error messages to *errors_out*.

        Returns:
            ``True`` when the tool call succeeded without errors.
        """
        try:
            raw = await self._call_deps_install(packages=packages, package_type=package_type)
        except Exception as exc:
            msg = (
                f"deps_install call failed for {package_type} packages (plugin={plugin_id}): {exc}"
            )
            logger.exception(msg)
            errors_out.append(msg)
            return False

        success, text = await self._parse_tool_result(raw)
        if not success:
            msg = (
                f"deps_install reported error for {package_type} packages "
                f"(plugin={plugin_id}): {text}"
            )
            logger.error(msg)
            errors_out.append(msg)
            return False

        self._collect_installed_from_text(
            text=text,
            packages=packages,
            installed_out=installed_out,
            errors_out=errors_out,
            plugin_id=plugin_id,
            package_type=package_type,
        )
        return True

    @staticmethod
    def _collect_installed_from_text(
        *,
        text: str,
        packages: tuple[str, ...],
        installed_out: list[str],
        errors_out: list[str],
        plugin_id: str,
        package_type: str,
    ) -> None:
        """Parse the JSON text from ``deps_install`` and collect outcomes.

        The expected JSON shape from the sandbox tool is::

            {
                "installed": ["pkg1", "pkg2"],
                "failed": [{"package": "pkg3", "error": "..."}]
            }

        When the text is not valid JSON, all *packages* are assumed
        installed (optimistic fallback — the tool itself reported success).
        """
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Optimistic: tool reported success, assume all installed
            installed_out.extend(packages)
            return

        if not isinstance(data, dict):
            installed_out.extend(packages)
            return

        for pkg in data.get("installed", []):
            if isinstance(pkg, str):
                installed_out.append(pkg)

        for entry in data.get("failed", []):
            if isinstance(entry, dict):
                pkg_name = entry.get("package", "<unknown>")
                err = entry.get("error", "unknown error")
                errors_out.append(
                    f"{package_type} package '{pkg_name}' failed (plugin={plugin_id}): {err}"
                )

    @staticmethod
    def _parse_check_result(raw: dict[str, Any]) -> dict[str, bool]:
        """Extract per-package booleans from a ``deps_check`` response.

        The expected JSON shape inside the text content is::

            {"packages": {"pkg1": true, "pkg2": false}}

        Returns a dict mapping ``package_name -> is_installed``.  If parsing
        fails, returns an empty dict (caller treats missing keys as *not
        installed*).
        """
        content_items: list[dict[str, Any]] = raw.get("content", [])
        text_parts: list[str] = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))

        text = "\n".join(text_parts) if text_parts else ""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {}

        if not isinstance(data, dict):
            return {}

        packages_map: dict[str, bool] = {}
        pkg_data = data.get("packages", data)
        if isinstance(pkg_data, dict):
            for name, status in pkg_data.items():
                packages_map[str(name)] = bool(status)
        return packages_map

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        """Return wall-clock milliseconds since *start*."""
        return int((time.monotonic() - start) * 1000)
