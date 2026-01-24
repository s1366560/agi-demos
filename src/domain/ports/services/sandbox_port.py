"""Sandbox Port - Abstract interface for sandboxed code execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional


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
    """Configuration for creating a sandbox instance."""

    provider: SandboxProvider = SandboxProvider.DOCKER
    image: str = "python:3.12-slim"
    cpu_limit: str = "2"
    memory_limit: str = "2G"
    timeout_seconds: int = 60
    network_isolated: bool = True
    security_profile: str = "standard"
    environment: Dict[str, str] = field(default_factory=dict)
    volumes: Dict[str, str] = field(default_factory=dict)


@dataclass
class SandboxInstance:
    """Represents a running sandbox instance."""

    id: str
    status: SandboxStatus
    config: SandboxConfig
    project_path: str
    endpoint: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    terminated_at: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass
class CodeExecutionRequest:
    """Request to execute code in a sandbox."""

    sandbox_id: str
    code: str
    language: str = "python"
    timeout_seconds: Optional[int] = None
    working_directory: str = "/workspace"
    environment: Dict[str, str] = field(default_factory=dict)


@dataclass
class CodeExecutionResult:
    """Result of code execution in a sandbox."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    output_files: List[str] = field(default_factory=list)
    error: Optional[str] = None


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
        config: Optional[SandboxConfig] = None,
    ) -> SandboxInstance:
        """
        Create a new sandbox instance.

        Args:
            project_path: Path to mount as workspace (or temp path for empty sandbox)
            config: Sandbox configuration

        Returns:
            SandboxInstance with connection details
        """
        pass

    @abstractmethod
    async def get_sandbox(self, sandbox_id: str) -> Optional[SandboxInstance]:
        """
        Get the status of a sandbox instance.

        Args:
            sandbox_id: Unique sandbox identifier

        Returns:
            SandboxInstance if found, None otherwise
        """
        pass

    @abstractmethod
    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """
        Terminate a sandbox instance.

        Args:
            sandbox_id: Unique sandbox identifier

        Returns:
            True if terminated successfully
        """
        pass

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
        pass

    @abstractmethod
    async def stream_execute(
        self,
        request: CodeExecutionRequest,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute code with streaming output.

        Args:
            request: Code execution request

        Yields:
            Dict with 'type' (stdout/stderr/status) and 'data'
        """
        pass

    @abstractmethod
    async def list_sandboxes(
        self,
        status: Optional[SandboxStatus] = None,
    ) -> List[SandboxInstance]:
        """
        List all sandbox instances.

        Args:
            status: Optional filter by status

        Returns:
            List of sandbox instances
        """
        pass

    @abstractmethod
    async def get_output_files(
        self,
        sandbox_id: str,
        output_dir: str = "/output",
    ) -> Dict[str, bytes]:
        """
        Retrieve output files from a sandbox.

        Args:
            sandbox_id: Sandbox identifier
            output_dir: Directory to read files from

        Returns:
            Dict mapping filename to file content
        """
        pass

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
        pass


# Domain Errors


class SandboxError(Exception):
    """Base class for sandbox errors."""

    def __init__(
        self,
        message: str,
        sandbox_id: Optional[str] = None,
        operation: Optional[str] = None,
    ):
        self.message = message
        self.sandbox_id = sandbox_id
        self.operation = operation
        super().__init__(self.message)


class SandboxTimeoutError(SandboxError):
    """Sandbox execution timed out."""

    pass


class SandboxResourceError(SandboxError):
    """Sandbox resource limits exceeded."""

    pass


class SandboxSecurityError(SandboxError):
    """Security violation in sandbox."""

    pass


class SandboxConnectionError(SandboxError):
    """Failed to connect to sandbox."""

    pass


class SandboxNotFoundError(SandboxError):
    """Sandbox instance not found."""

    pass
