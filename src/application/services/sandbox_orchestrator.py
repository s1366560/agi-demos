"""Sandbox Orchestrator - Unified sandbox service orchestration layer.
used by both REST API and Agent Tools to eliminate code duplication.
(user's machine via WebSocket tunnel).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.domain.ports.services.sandbox_port import SandboxPort

if TYPE_CHECKING:
    from src.application.services.sandbox_event_service import SandboxEventPublisher
    from src.infrastructure.adapters.secondary.sandbox.local_sandbox_adapter import (
        LocalSandboxAdapter,
    )

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Data Classes
# ============================================================================


@dataclass
class DesktopConfig:
    """Desktop service configuration."""

    resolution: str = "1920x1080"
    display: str = ":1"
    port: int = 6080


@dataclass
class TerminalConfig:
    """Terminal service configuration."""

    port: int = 7681
    shell: str = "/bin/bash"


# ============================================================================
# Status Data Classes
# ============================================================================


@dataclass
class DesktopStatus:
    """Desktop service status."""

    running: bool
    url: str | None = None
    display: str = ":1"
    resolution: str = "1920x1080"
    port: int = 6080
    pid: int | None = None
    audio_enabled: bool = False
    dynamic_resize: bool = True
    encoding: str = "webp"


@dataclass
class TerminalStatus:
    """Terminal service status."""

    running: bool
    url: str | None = None
    port: int = 7681
    pid: int | None = None
    session_id: str | None = None


@dataclass
class CommandResult:
    """Command execution result."""

    exit_code: int
    stdout: str
    stderr: str
    execution_time_ms: int


# ============================================================================
# Sandbox Orchestrator (Interface)
# ============================================================================


class SandboxOrchestrator:
    """
    Unified sandbox service orchestration layer.

    This class provides a single entry point for all sandbox operations,
    used by both REST API endpoints and Agent Tools. It wraps the
    MCPSandboxAdapter and provides a consistent interface with
    unified event publishing.

    Supports both:
    - Cloud sandboxes: Docker containers managed by MCPSandboxAdapter
    - Local sandboxes: User's machine via LocalSandboxAdapter

    Usage:
        orchestrator = SandboxOrchestrator(sandbox_adapter, event_publisher)

        # Start desktop
        status = await orchestrator.start_desktop(
            sandbox_id="sb_123",
            config=DesktopConfig(resolution="1920x1080")
        )

        # Execute command
        result = await orchestrator.execute_command(
            sandbox_id="sb_123",
            command="ls -la"
        )
    """

    def __init__(
        self,
        sandbox_adapter: SandboxPort,  # SandboxPort (MCPSandboxAdapter for cloud)
        event_publisher: SandboxEventPublisher | None = None,  # Reserved for future use
        default_timeout: int = 30,
        local_sandbox_adapter: LocalSandboxAdapter | None = None,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            sandbox_adapter: Cloud sandbox adapter (MCPSandboxAdapter instance)
            event_publisher: Reserved for future event publishing integration
            default_timeout: Default timeout for operations (seconds)
            local_sandbox_adapter: Optional local sandbox adapter for user's machine
        """
        self._adapter = sandbox_adapter
        self._local_adapter = local_sandbox_adapter
        self._events = event_publisher  # Currently not used; events handled by API layer
        self._default_timeout = default_timeout
        # Track sandbox type mapping: sandbox_id -> "cloud" or "local"
        self._sandbox_types: dict[str, str] = {}

    def register_sandbox_type(self, sandbox_id: str, sandbox_type: str) -> None:
        """
        Register the type of a sandbox for routing.

        Args:
            sandbox_id: Sandbox identifier
            sandbox_type: "cloud" or "local"
        """
        self._sandbox_types[sandbox_id] = sandbox_type
        logger.debug(f"Registered sandbox {sandbox_id} as {sandbox_type}")

    def get_sandbox_type(self, sandbox_id: str) -> str:
        """Get the type of a sandbox (defaults to "cloud")."""
        return self._sandbox_types.get(sandbox_id, "cloud")

    def is_local_sandbox(self, sandbox_id: str) -> bool:
        """Check if a sandbox is a local sandbox."""
        return self.get_sandbox_type(sandbox_id) == "local"

    def _get_adapter_for_sandbox(self, sandbox_id: str) -> SandboxPort:
        """Get the appropriate adapter for a sandbox."""
        if self.is_local_sandbox(sandbox_id) and self._local_adapter:
            return self._local_adapter
        return self._adapter

    # ========================================================================
    # Desktop Service Management
    # ========================================================================

    async def start_desktop(
        self,
        sandbox_id: str,
        config: DesktopConfig | None = None,
    ) -> DesktopStatus:
        """
        Start the remote desktop service.

        Unified entry point for:
        - Agent Tools (DesktopTool)
        - REST API (POST /sandbox/{id}/desktop)

        Args:
            sandbox_id: Sandbox identifier
            config: Desktop configuration

        Returns:
            DesktopStatus object

        Raises:
            SandboxConnectionError: If connection fails
            SandboxNotFoundError: If sandbox doesn't exist
        """
        config = config or DesktopConfig()
        adapter = self._get_adapter_for_sandbox(sandbox_id)

        try:
            # Call MCP tool via adapter
            result = await adapter.call_tool(
                sandbox_id,
                "start_desktop",
                {
                    "resolution": config.resolution,
                    "display": config.display,
                    "port": config.port,
                    "_workspace_dir": "/workspace",
                },
                timeout=self._default_timeout,
            )

            # Parse result
            status = self._parse_desktop_result(result)

            logger.info(
                f"Desktop started for sandbox {sandbox_id}: {status.url}, running={status.running}"
            )

            return status

        except Exception as e:
            logger.error(f"Failed to start desktop for {sandbox_id}: {e}")
            raise

    async def stop_desktop(self, sandbox_id: str) -> bool:
        """Stop the remote desktop service."""
        adapter = self._get_adapter_for_sandbox(sandbox_id)
        try:
            _ = await adapter.call_tool(
                sandbox_id,
                "stop_desktop",
                {"_workspace_dir": "/workspace"},
                timeout=self._default_timeout,
            )

            logger.info(f"Desktop stopped for sandbox {sandbox_id}")

            return True

        except Exception as e:
            logger.error(f"Failed to stop desktop for {sandbox_id}: {e}")
            return False

    async def get_desktop_status(self, sandbox_id: str) -> DesktopStatus:
        """Get the current desktop service status."""
        result = await self._adapter.call_tool(
            sandbox_id,
            "get_desktop_status",
            {"_workspace_dir": "/workspace"},
            timeout=self._default_timeout,
        )

        return self._parse_desktop_result(result)

    # ========================================================================
    # Terminal Service Management
    # ========================================================================

    async def start_terminal(
        self,
        sandbox_id: str,
        config: TerminalConfig | None = None,
    ) -> TerminalStatus:
        """Start the web terminal service."""
        config = config or TerminalConfig()

        try:
            logger.debug(
                f"Starting terminal for sandbox {sandbox_id} with config: port={config.port}"
            )
            result = await self._adapter.call_tool(
                sandbox_id,
                "start_terminal",
                {
                    "port": config.port,
                    "_workspace_dir": "/workspace",
                },
                timeout=self._default_timeout,
            )
            logger.debug(f"MCP call_tool result for start_terminal: {result}")

            status = self._parse_terminal_result(result)

            if status.running:
                logger.info(f"Terminal started for sandbox {sandbox_id}: {status.url}")
            else:
                logger.warning(f"Terminal did not start for sandbox {sandbox_id}, status: {status}")

            return status

        except Exception as e:
            logger.error(f"Failed to start terminal for {sandbox_id}: {e}")
            raise

    async def stop_terminal(self, sandbox_id: str) -> bool:
        """Stop the web terminal service."""
        try:
            _ = await self._adapter.call_tool(
                sandbox_id,
                "stop_terminal",
                {"_workspace_dir": "/workspace"},
                timeout=self._default_timeout,
            )

            logger.info(f"Terminal stopped for sandbox {sandbox_id}")

            return True

        except Exception as e:
            logger.error(f"Failed to stop terminal for {sandbox_id}: {e}")
            return False

    async def get_terminal_status(self, sandbox_id: str) -> TerminalStatus:
        """Get the current terminal service status."""
        adapter = self._get_adapter_for_sandbox(sandbox_id)
        result = await adapter.call_tool(
            sandbox_id,
            "get_terminal_status",
            {"_workspace_dir": "/workspace"},
            timeout=self._default_timeout,
        )

        return self._parse_terminal_result(result)

    # ========================================================================
    # Command Execution
    # ========================================================================

    async def execute_command(
        self,
        sandbox_id: str,
        command: str,
        working_dir: str = "/workspace",
        timeout: int = 60,
    ) -> CommandResult:
        """
        Execute a shell command in the sandbox.

        Uses the MCP bash tool for execution.

        Args:
            sandbox_id: Sandbox identifier
            command: Shell command to execute
            working_dir: Working directory for command execution
            timeout: Execution timeout in seconds

        Returns:
            CommandResult with exit code, stdout, stderr, and timing
        """
        start_time = time.time()
        adapter = self._get_adapter_for_sandbox(sandbox_id)

        result = await adapter.call_tool(
            sandbox_id,
            "bash",
            {
                "command": command,
                "working_dir": working_dir,
                "timeout": timeout,
                "_workspace_dir": working_dir,
            },
            timeout=timeout + 5,
        )

        execution_time_ms = int((time.time() - start_time) * 1000)

        # Parse result
        content_list = result.get("content", [])
        output = ""
        if content_list:
            output = content_list[0].get("text", "")

        return CommandResult(
            exit_code=0 if not result.get("is_error") else 1,
            stdout=output if not result.get("is_error") else "",
            stderr=output if result.get("is_error") else "",
            execution_time_ms=execution_time_ms,
        )

    # ========================================================================
    # Result Parsing Helpers
    # ========================================================================

    def _parse_desktop_result(self, result: dict[str, Any]) -> DesktopStatus:
        """Parse MCP tool result to DesktopStatus."""
        content_list = result.get("content", [])
        if not content_list:
            logger.warning(f"Desktop result has no content: {result}")
            return DesktopStatus(running=False, url=None, display="", resolution="", port=0)

        try:
            text_content = content_list[0].get("text", "{}")
            data = json.loads(text_content)
            # If success is True, consider desktop as running
            running = data.get("running", data.get("success", False))
            return DesktopStatus(
                running=running,
                url=data.get("url"),
                display=data.get("display", ""),
                resolution=data.get("resolution", ""),
                port=data.get("port", 0),
                pid=data.get("kasmvnc_pid"),
                audio_enabled=data.get("audio_enabled", False),
                dynamic_resize=data.get("dynamic_resize", True),
                encoding=data.get("encoding", "webp"),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error(f"Failed to parse desktop result: {e}, content: {content_list}")
            return DesktopStatus(running=False, url=None, display="", resolution="", port=0)

    def _parse_terminal_result(self, result: dict[str, Any]) -> TerminalStatus:
        """Parse MCP tool result to TerminalStatus."""
        logger.debug(f"Parsing terminal result: {result}")
        content_list = result.get("content", [])
        if not content_list:
            logger.warning(f"Terminal result has no content: {result}")
            return TerminalStatus(running=False, url=None, port=0)

        try:
            text_content = content_list[0].get("text", "{}")
            logger.debug(f"Terminal result text: {text_content}")
            data = json.loads(text_content)
            # If success is True, consider terminal as running
            running = data.get("running", data.get("success", False))
            return TerminalStatus(
                running=running,
                url=data.get("url"),
                port=data.get("port", 0),
                pid=data.get("pid"),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error(f"Failed to parse terminal result: {e}, content: {content_list}")
            return TerminalStatus(running=False, url=None, port=0)
