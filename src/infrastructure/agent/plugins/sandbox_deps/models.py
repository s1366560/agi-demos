"""Data models for the dual-runtime dependency management system.

This module defines the core data models used by the sandbox dependency
orchestrator to declare, track, and install plugin dependencies across
the host runtime and sandbox Docker containers.

Key concepts:
- ExecutionContext: Where a tool runs (host, sandbox, or hybrid)
- RuntimeDependencies: Declarative dependency manifest for a plugin tool
- PreparedState: Snapshot of a successfully prepared environment
- DepsStateRecord: Persisted record tracking dependency installation state
- InstallRequest / InstallResult: Request-response pair for installation
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class ExecutionContext(Enum):
    """Where a tool executes within the dual-runtime architecture.

    The agent system runs across two runtimes: the host (where ReActAgent
    and the orchestrator live) and the sandbox (isolated Docker containers
    where MCP tools and file operations run). Some tools require packages
    installed in both.

    Values:
        HOST: Tool runs on the host machine only.
        SANDBOX: Tool runs inside a sandbox container only.
        HYBRID: Tool requires dependencies in both host and sandbox.
    """

    HOST = "host"
    SANDBOX = "sandbox"
    HYBRID = "hybrid"


@dataclass(frozen=True, kw_only=True)
class MCPServerDependency:
    """Describes an MCP server that a plugin tool depends on.

    When a plugin tool relies on an MCP server for functionality, this
    value object captures the server's launch configuration so the
    dependency installer can ensure the server is available in the
    sandbox environment.

    Attributes:
        name: Unique identifier for the MCP server (e.g., "filesystem-server").
        transport_type: Communication protocol ("stdio" or "sse").
        command: Executable command to start the server.
        args: Command-line arguments for the server process.
        env: Environment variables required by the server.
    """

    name: str
    transport_type: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RuntimeDependencies:
    """Declarative manifest of what a plugin tool needs to run.

    This is a frozen value object attached to a plugin tool definition.
    It describes all external dependencies (Python packages, system
    packages, MCP servers, environment variables) required for the tool
    to function in its target execution context.

    Attributes:
        pip_packages: Python packages with optional version constraints
            (e.g., ("pandas>=2.0", "numpy")).
        system_packages: OS-level packages installed via apt/apk
            (e.g., ("ffmpeg", "imagemagick")).
        mcp_servers: MCP server dependencies required by the tool.
        env_vars: Environment variables that must be set at runtime.
        python_version: Minimum Python version constraint (e.g., "3.11").
    """

    pip_packages: tuple[str, ...] = ()
    system_packages: tuple[str, ...] = ()
    mcp_servers: tuple[MCPServerDependency, ...] = ()
    env_vars: dict[str, str] = field(default_factory=dict)
    python_version: str | None = None

    def deps_hash(self) -> str:
        """Compute a SHA256 hash of the canonical dependency representation.

        The hash is deterministic: identical dependency declarations always
        produce the same hash, regardless of dict ordering. This is used
        to detect whether the sandbox environment needs re-preparation.

        Returns:
            A hex-encoded SHA256 digest string.
        """
        canonical = {
            "pip_packages": sorted(self.pip_packages),
            "system_packages": sorted(self.system_packages),
            "mcp_servers": [
                {
                    "name": srv.name,
                    "transport_type": srv.transport_type,
                    "command": srv.command,
                    "args": list(srv.args),
                    "env": dict(sorted(srv.env.items())),
                }
                for srv in sorted(self.mcp_servers, key=lambda s: s.name)
            ],
            "env_vars": dict(sorted(self.env_vars.items())),
            "python_version": self.python_version,
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class PreparedState:
    """Snapshot confirming that dependencies are installed and ready.

    Created after a successful dependency installation. The deps_hash
    links this state to a specific RuntimeDependencies configuration,
    so any change in dependencies invalidates the prepared state.

    Attributes:
        plugin_id: The plugin that owns this prepared environment.
        deps_hash: SHA256 of the RuntimeDependencies that were installed.
        sandbox_image_digest: Docker image digest of the sandbox at install time.
        prepared_at: Timestamp when preparation completed.
        venv_path: Filesystem path to the virtual environment inside the sandbox
            (e.g., "/opt/memstack/envs/{plugin_id}/{hash}/").
    """

    plugin_id: str
    deps_hash: str
    sandbox_image_digest: str
    prepared_at: datetime
    venv_path: str


@dataclass(kw_only=True)
class DepsStateRecord:
    """Persisted record tracking dependency installation state in Redis.

    This is a mutable entity stored per (plugin, project, sandbox) triple.
    It tracks the current prepared state, installation attempts, and any
    errors encountered during dependency installation.

    Attributes:
        plugin_id: The plugin this record belongs to.
        project_id: The project scope for multi-tenancy.
        sandbox_id: The sandbox instance where deps are installed.
        state: The current prepared state, or None if not yet prepared.
        last_check: Timestamp of the last state check or install attempt.
        install_attempts: Number of installation attempts (for retry tracking).
        last_error: Error message from the most recent failed attempt.
    """

    plugin_id: str
    project_id: str
    sandbox_id: str
    state: PreparedState | None = None
    last_check: datetime = field(default_factory=lambda: datetime.now(UTC))
    install_attempts: int = 0
    last_error: str | None = None

    def is_prepared(self) -> bool:
        """Check whether dependencies are fully installed and ready.

        Returns:
            True if a PreparedState exists, indicating successful installation.
        """
        return self.state is not None


@dataclass(frozen=True, kw_only=True)
class InstallRequest:
    """Request to install dependencies for a plugin in a sandbox.

    Submitted to the sandbox dependency orchestrator, which determines
    whether installation is needed and executes it if so.

    Attributes:
        plugin_id: The plugin requesting installation.
        project_id: The project scope for multi-tenancy.
        sandbox_id: Target sandbox instance.
        dependencies: The full dependency manifest to install.
        force: If True, reinstall even if deps_hash matches.
    """

    plugin_id: str
    project_id: str
    sandbox_id: str
    dependencies: RuntimeDependencies
    force: bool = False


@dataclass(frozen=True, kw_only=True)
class InstallResult:
    """Result of a dependency installation attempt.

    Returned by the sandbox installer after attempting to install
    dependencies. Contains detailed information about what was
    installed, skipped, or failed.

    Attributes:
        success: Whether the installation completed without errors.
        plugin_id: The plugin that was being installed.
        installed_packages: Packages that were newly installed.
        skipped_packages: Packages already present (no action taken).
        errors: Error messages for any failed installations.
        duration_ms: Wall-clock time of the installation in milliseconds.
    """

    success: bool
    plugin_id: str
    installed_packages: tuple[str, ...] = ()
    skipped_packages: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    duration_ms: int = 0
