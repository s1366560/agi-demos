"""Sandbox Port - Abstract interface for sandboxed code execution."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SandboxProvider(Enum):
    """Supported sandbox providers."""

    DOCKER = "docker"
    FIRECRACKER = "firecracker"
    KUBERNETES = "kubernetes"
    PODMAN = "podman"


class SandboxStatus(Enum):
    """Sandbox instance status."""

    CREATING = "creating"
    RUNNING = "running"
    STOPPED = "stopped"
    TERMINATED = "terminated"
    ERROR = "error"


@dataclass
class SandboxConfig:
    """Configuration for creating a sandbox instance.

    The default image should be read from configuration settings
    (settings.sandbox_default_image) to maintain a single source of truth.
    """

    image: str  # Required - no default, must be provided by caller
    provider: SandboxProvider = SandboxProvider.DOCKER
    cpu_limit: str = "2"
    memory_limit: str = "2G"
    timeout_seconds: int = 60
    network_isolated: bool = True
    network_mode: str = "bridge"  # bridge, none, host, container:<name>
    allowed_networks: list[str] = field(default_factory=list)  # CIDR ranges
    blocked_ports: list[int] = field(default_factory=list)  # Ports to block
    security_profile: str = "standard"
    environment: dict[str, str] = field(default_factory=dict)
    volumes: dict[str, str] = field(default_factory=dict)
    desktop_enabled: bool = True  # Whether to start desktop environment (VNC/noVNC)


@dataclass
class SandboxInstance:
    """Represents a running sandbox instance."""

    id: str
    status: SandboxStatus
    config: SandboxConfig
    project_path: str
    endpoint: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    terminated_at: datetime | None = None
    error_message: str | None = None
    last_activity_at: datetime | None = None  # Last tool execution/activity time
    labels: dict[str, str] = field(default_factory=dict)  # Container labels for identification


@dataclass
class CodeExecutionRequest:
    """Request to execute code in a sandbox."""

    sandbox_id: str
    code: str
    language: str = "python"
    timeout_seconds: int | None = None
    working_directory: str = "/workspace"
    environment: dict[str, str] = field(default_factory=dict)


@dataclass
class CodeExecutionResult:
    """Result of code execution in a sandbox."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    output_files: list[str] = field(default_factory=list)
    error: str | None = None


class SandboxPort(ABC):
    """
    Abstract interface for sandbox management and code execution.

    Provides isolation for executing untrusted code with resource limits
    and security controls.
    """

    @abstractmethod
    async def create_sandbox(
        self,
        project_path: str,
        config: SandboxConfig | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> SandboxInstance:
        """
        Create a new sandbox instance.

        Args:
            project_path: Path to mount as workspace (or temp path for empty sandbox)
            config: Sandbox configuration
            project_id: Optional project ID for labeling and identification
            tenant_id: Optional tenant ID for labeling and identification
            sandbox_id: Optional sandbox ID to reuse (for recreating with same ID)

        Returns:
            SandboxInstance with connection details
        """

    @abstractmethod
    async def get_sandbox(self, sandbox_id: str) -> SandboxInstance | None:
        """
        Get the status of a sandbox instance.

        Args:
            sandbox_id: Unique sandbox identifier

        Returns:
            SandboxInstance if found, None otherwise
        """

    @abstractmethod
    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """
        Terminate a sandbox instance.

        Args:
            sandbox_id: Unique sandbox identifier

        Returns:
            True if terminated successfully
        """

    @abstractmethod
    async def execute_code(
        self,
        request: CodeExecutionRequest,
    ) -> CodeExecutionResult:
        """
        Execute code in a sandbox.

        Args:
            request: Code execution request with code and parameters

        Returns:
            CodeExecutionResult with stdout, stderr, and output files
        """

    @abstractmethod
    async def stream_execute(
        self,
        request: CodeExecutionRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Execute code with streaming output.

        Args:
            request: Code execution request

        Yields:
            Dict with 'type' (stdout/stderr/status) and 'data'
        """

    @abstractmethod
    async def list_sandboxes(
        self,
        status: SandboxStatus | None = None,
    ) -> list[SandboxInstance]:
        """
        List all sandbox instances.

        Args:
            status: Optional filter by status

        Returns:
            List of sandbox instances
        """

    @abstractmethod
    async def get_output_files(
        self,
        sandbox_id: str,
        output_dir: str = "/output",
    ) -> dict[str, bytes]:
        """
        Retrieve output files from a sandbox.

        Args:
            sandbox_id: Sandbox identifier
            output_dir: Directory to read files from

        Returns:
            Dict mapping filename to file content
        """

    @abstractmethod
    async def cleanup_expired(
        self,
        max_age_seconds: int = 3600,
    ) -> int:
        """
        Clean up expired sandbox instances.

        Args:
            max_age_seconds: Maximum age before cleanup

        Returns:
            Number of sandboxes cleaned up
        """


# Domain Errors


class SandboxError(Exception):
    """Base class for sandbox errors."""

    def __init__(
        self,
        message: str,
        sandbox_id: str | None = None,
        operation: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self.message = message
        self.sandbox_id = sandbox_id
        self.operation = operation
        self.project_id = project_id
        super().__init__(self.message)


class SandboxTimeoutError(SandboxError):
    """Sandbox execution timed out."""



class SandboxResourceError(SandboxError):
    """Sandbox resource limits exceeded."""



class SandboxSecurityError(SandboxError):
    """Security violation in sandbox."""



class SandboxConnectionError(SandboxError):
    """Failed to connect to sandbox."""



class SandboxNotFoundError(SandboxError):
    """Sandbox instance not found."""

