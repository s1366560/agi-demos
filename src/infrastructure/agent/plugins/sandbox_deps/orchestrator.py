"""Main coordinator for the dual-runtime dependency management lifecycle.

Manages the full dependency lifecycle across host and sandbox runtimes.
Determines whether dependencies need installation, validates them through
the security gate, delegates to the appropriate installer, and tracks
state in Redis via DepsStateStore.

This module does NOT import Redis or sandbox adapters directly -- it uses
the injected collaborators (state_store, sandbox_installer, security_gate).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Protocol

from .models import (
    DepsStateRecord,
    ExecutionContext,
    InstallRequest,
    InstallResult,
    PreparedState,
    RuntimeDependencies,
)
from .security_gate import SecurityGate
from .state_store import DepsStateStore

logger = logging.getLogger(__name__)


class SandboxDependencyInstaller(Protocol):
    """Protocol for the sandbox dependency installer.

    Defined here so the orchestrator can depend on a structural type
    rather than a concrete import.  Any object with an async ``install``
    method matching this signature satisfies the contract.
    """

    async def install(self, request: InstallRequest) -> InstallResult: ...


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HOST_PIP_TIMEOUT_SECONDS: float = 120.0
_DEFAULT_VENV_PREFIX = "/opt/memstack/envs"


class DependencyOrchestrator:
    """Coordinates dependency installation across host and sandbox runtimes.

    This is the main entry point for the dependency management system.
    It determines whether dependencies need to be installed, validates
    them through the security gate, delegates installation to the
    appropriate installer, and tracks state in Redis.

    Usage pattern::

        orchestrator = DependencyOrchestrator(
            state_store=deps_state_store,
            sandbox_installer=sandbox_installer,
            security_gate=security_gate,
        )
        result = await orchestrator.ensure_dependencies(
            plugin_id="my-plugin",
            project_id="proj-123",
            sandbox_id="sbx-456",
            dependencies=runtime_deps,
        )
    """

    def __init__(
        self,
        *,
        state_store: DepsStateStore,
        sandbox_installer: SandboxDependencyInstaller,
        security_gate: SecurityGate | None = None,
        max_retries: int = 2,
    ) -> None:
        self._state_store = state_store
        self._sandbox_installer = sandbox_installer
        self._security_gate = security_gate or SecurityGate()
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_dependencies(
        self,
        *,
        plugin_id: str,
        project_id: str,
        sandbox_id: str,
        dependencies: RuntimeDependencies,
        execution_context: ExecutionContext = ExecutionContext.SANDBOX,
        force: bool = False,
    ) -> InstallResult:
        """Ensure that *dependencies* are installed for the given plugin.

        This is the main orchestration entry point.  Flow:

        1. Compute ``deps_hash`` from *dependencies*.
        2. Load existing state record from the state store.
        3. If a matching prepared state exists and *force* is False,
           return a cached success result (skip installation).
        4. Validate packages through the security gate.
        5. Route installation based on *execution_context*:
           - ``SANDBOX``: delegate to the sandbox installer.
           - ``HOST``: run ``pip install`` via subprocess.
           - ``HYBRID``: install in sandbox first, then host.
        6. On success: create a :class:`PreparedState`, update the
           :class:`DepsStateRecord`, and persist via the state store.
        7. On failure: increment ``install_attempts``, record the error,
           and retry up to ``max_retries``.

        Returns:
            An :class:`InstallResult` summarising what happened.
        """
        start = time.monotonic()
        deps_hash = dependencies.deps_hash()

        logger.info(
            "ensure_dependencies plugin=%s project=%s sandbox=%s context=%s force=%s hash=%s",
            plugin_id,
            project_id,
            sandbox_id,
            execution_context.value,
            force,
            deps_hash[:12],
        )

        # 1. Check cached state ----------------------------------------
        existing = await self._state_store.load(plugin_id, sandbox_id)
        if (
            not force
            and existing is not None
            and existing.state is not None
            and existing.state.deps_hash == deps_hash
        ):
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Dependencies already prepared plugin=%s (cached, %dms)",
                plugin_id,
                elapsed_ms,
            )
            return InstallResult(
                success=True,
                plugin_id=plugin_id,
                skipped_packages=dependencies.pip_packages,
                duration_ms=elapsed_ms,
            )

        # 2. Security validation ----------------------------------------
        request = InstallRequest(
            plugin_id=plugin_id,
            project_id=project_id,
            sandbox_id=sandbox_id,
            dependencies=dependencies,
            force=force,
        )

        validation = self._security_gate.validate_request(request)
        if not validation.valid:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "Security gate rejected plugin=%s: %s",
                plugin_id,
                "; ".join(validation.errors),
            )
            return InstallResult(
                success=False,
                plugin_id=plugin_id,
                errors=validation.errors,
                duration_ms=elapsed_ms,
            )

        # 3. Install with retry ----------------------------------------
        record = existing or DepsStateRecord(
            plugin_id=plugin_id,
            project_id=project_id,
            sandbox_id=sandbox_id,
        )

        last_result: InstallResult | None = None
        attempts = 0

        while attempts <= self._max_retries:
            attempts += 1
            record.install_attempts += 1
            record.last_check = datetime.now(UTC)

            logger.info(
                "Installing dependencies plugin=%s attempt=%d/%d context=%s",
                plugin_id,
                attempts,
                self._max_retries + 1,
                execution_context.value,
            )

            last_result = await self._route_install(
                request=request,
                execution_context=execution_context,
            )

            if last_result.success:
                break

            # Record error and decide whether to retry
            record.last_error = "; ".join(last_result.errors) or "unknown error"
            await self._state_store.save(record)

            if attempts <= self._max_retries:
                logger.warning(
                    "Install failed plugin=%s attempt=%d, retrying: %s",
                    plugin_id,
                    attempts,
                    record.last_error,
                )

        assert last_result is not None  # guaranteed by loop

        elapsed_ms = int((time.monotonic() - start) * 1000)

        # 4. Persist outcome -------------------------------------------
        if last_result.success:
            prepared = await self._create_prepared_state(
                plugin_id=plugin_id,
                dependencies=dependencies,
                sandbox_id=sandbox_id,
            )
            record.state = prepared
            record.last_error = None
            await self._state_store.save(record)

            logger.info(
                "Dependencies installed plugin=%s (%dms, %d packages)",
                plugin_id,
                elapsed_ms,
                len(last_result.installed_packages),
            )
        else:
            logger.error(
                "Dependency installation failed plugin=%s after %d attempt(s): %s",
                plugin_id,
                attempts,
                "; ".join(last_result.errors),
            )

        return InstallResult(
            success=last_result.success,
            plugin_id=last_result.plugin_id,
            installed_packages=last_result.installed_packages,
            skipped_packages=last_result.skipped_packages,
            errors=last_result.errors,
            duration_ms=elapsed_ms,
        )

    async def check_dependencies(
        self,
        *,
        plugin_id: str,
        project_id: str,
        sandbox_id: str,
        dependencies: RuntimeDependencies,
    ) -> DepsStateRecord:
        """Check whether dependencies are prepared without installing.

        Loads the state record from the store and verifies that the
        ``deps_hash`` matches the current *dependencies* manifest.
        Returns a fresh :class:`DepsStateRecord` if no record exists.

        Args:
            plugin_id: Plugin identifier.
            project_id: Project scope for multi-tenancy.
            sandbox_id: Target sandbox instance.
            dependencies: The dependency manifest to check against.

        Returns:
            The existing or newly-created state record.
        """
        existing = await self._state_store.load(plugin_id, sandbox_id)
        if existing is None:
            return DepsStateRecord(
                plugin_id=plugin_id,
                project_id=project_id,
                sandbox_id=sandbox_id,
            )

        # Invalidate if deps changed
        deps_hash = dependencies.deps_hash()
        if existing.state is not None and existing.state.deps_hash != deps_hash:
            logger.info(
                "Deps hash mismatch plugin=%s (stored=%s, current=%s)",
                plugin_id,
                existing.state.deps_hash[:12],
                deps_hash[:12],
            )
            existing.state = None

        return existing

    async def invalidate(
        self,
        *,
        plugin_id: str,
        sandbox_id: str,
        project_id: str,
    ) -> bool:
        """Invalidate cached dependency state for a specific plugin/sandbox.

        Use when the sandbox is rebuilt or the environment is otherwise
        known to be stale.

        Returns:
            True if a record was removed, False otherwise.
        """
        removed = await self._state_store.remove(plugin_id, sandbox_id, project_id)
        if removed:
            logger.info(
                "Invalidated deps state plugin=%s sandbox=%s",
                plugin_id,
                sandbox_id,
            )
        return removed

    async def invalidate_project(self, *, project_id: str) -> int:
        """Invalidate ALL dependency states for a project.

        Typically called when a project's sandbox pool is torn down.

        Returns:
            Number of records that were invalidated.
        """
        records = await self._state_store.list_by_project(project_id)
        count = 0
        for record in records:
            removed = await self._state_store.remove(
                record.plugin_id, record.sandbox_id, record.project_id
            )
            if removed:
                count += 1

        if count:
            logger.info(
                "Invalidated %d deps state record(s) for project=%s",
                count,
                project_id,
            )
        return count

    # ------------------------------------------------------------------
    # Private: routing
    # ------------------------------------------------------------------

    async def _route_install(
        self,
        *,
        request: InstallRequest,
        execution_context: ExecutionContext,
    ) -> InstallResult:
        """Route installation to the correct installer based on context."""
        if execution_context is ExecutionContext.SANDBOX:
            return await self._install_sandbox_deps(request)

        if execution_context is ExecutionContext.HOST:
            return await self._install_host_deps(request)

        # HYBRID: sandbox first (isolated), then host
        sandbox_result = await self._install_sandbox_deps(request)
        if not sandbox_result.success:
            return sandbox_result

        host_result = await self._install_host_deps(request)
        if not host_result.success:
            return InstallResult(
                success=False,
                plugin_id=request.plugin_id,
                installed_packages=sandbox_result.installed_packages,
                errors=(
                    *host_result.errors,
                    "Sandbox install succeeded but host install failed",
                ),
            )

        return InstallResult(
            success=True,
            plugin_id=request.plugin_id,
            installed_packages=(
                *sandbox_result.installed_packages,
                *host_result.installed_packages,
            ),
            skipped_packages=(
                *sandbox_result.skipped_packages,
                *host_result.skipped_packages,
            ),
        )

    async def _install_sandbox_deps(self, request: InstallRequest) -> InstallResult:
        """Delegate installation to the sandbox dependency installer."""
        try:
            return await self._sandbox_installer.install(request)
        except Exception as exc:
            logger.exception(
                "Sandbox installer raised for plugin=%s: %s",
                request.plugin_id,
                exc,
            )
            return InstallResult(
                success=False,
                plugin_id=request.plugin_id,
                errors=(f"Sandbox installer error: {exc}",),
            )

    async def _install_host_deps(self, request: InstallRequest) -> InstallResult:
        """Install pip packages on the host using subprocess.

        Only pip packages are installed on the host -- system packages
        are skipped (they only apply to sandbox containers).  Uses the
        same ``asyncio.to_thread(subprocess.run, ...)`` pattern as
        :class:`PluginRuntimeManager`.
        """
        import subprocess

        packages = list(request.dependencies.pip_packages)
        if not packages:
            return InstallResult(
                success=True,
                plugin_id=request.plugin_id,
                skipped_packages=request.dependencies.pip_packages,
            )

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *packages,
        ]

        logger.info(
            "Installing host pip packages plugin=%s: %s",
            request.plugin_id,
            ", ".join(packages),
        )

        try:
            process = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                ),
                timeout=_HOST_PIP_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            msg = f"pip install timed out after {_HOST_PIP_TIMEOUT_SECONDS:.0f}s"
            logger.error("Host pip install timeout plugin=%s", request.plugin_id)
            return InstallResult(
                success=False,
                plugin_id=request.plugin_id,
                errors=(msg,),
            )

        if process.returncode != 0:
            stderr_snippet = (process.stderr or "")[:500]
            msg = f"pip install failed (rc={process.returncode}): {stderr_snippet}"
            logger.error(
                "Host pip install failed plugin=%s rc=%d: %s",
                request.plugin_id,
                process.returncode,
                stderr_snippet,
            )
            return InstallResult(
                success=False,
                plugin_id=request.plugin_id,
                errors=(msg,),
            )

        logger.info(
            "Host pip install succeeded plugin=%s",
            request.plugin_id,
        )
        return InstallResult(
            success=True,
            plugin_id=request.plugin_id,
            installed_packages=tuple(packages),
        )

    # ------------------------------------------------------------------
    # Private: state helpers
    # ------------------------------------------------------------------

    async def _create_prepared_state(
        self,
        *,
        plugin_id: str,
        dependencies: RuntimeDependencies,
        sandbox_id: str,
    ) -> PreparedState:
        """Create a PreparedState snapshot after successful installation.

        The ``venv_path`` follows the convention
        ``/opt/memstack/envs/{plugin_id}/{hash_prefix}/`` so each plugin
        gets an isolated virtual environment keyed by its dependency hash.
        """
        deps_hash = dependencies.deps_hash()
        venv_path = f"{_DEFAULT_VENV_PREFIX}/{plugin_id}/{deps_hash[:16]}/"

        return PreparedState(
            plugin_id=plugin_id,
            deps_hash=deps_hash,
            sandbox_image_digest=sandbox_id,
            prepared_at=datetime.now(UTC),
            venv_path=venv_path,
        )
