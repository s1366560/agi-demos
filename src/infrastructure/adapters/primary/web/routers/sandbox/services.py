"""Desktop and Terminal service endpoints for Sandbox API.

Provides management of interactive services:
- start_desktop / stop_desktop / get_desktop_status: Desktop (noVNC)
- start_terminal / stop_terminal / get_terminal_status: Terminal (ttyd)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_orchestrator import (
    DesktopConfig,
    SandboxOrchestrator,
    TerminalConfig,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

from .schemas import (
    DesktopStartRequest,
    DesktopStatusResponse,
    DesktopStopResponse,
    TerminalStartRequest,
    TerminalStatusResponse,
    TerminalStopResponse,
)
from .utils import (
    extract_project_id,
    get_event_publisher,
    get_sandbox_adapter,
    get_sandbox_orchestrator,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Desktop Management Endpoints ---


@router.post("/{sandbox_id}/desktop", response_model=DesktopStatusResponse)
async def start_desktop(
    sandbox_id: str,
    request: DesktopStartRequest = DesktopStartRequest(),
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> DesktopStatusResponse:
    """
    Start the remote desktop service (noVNC) for a sandbox.

    Starts Xvfb (virtual display), VNC server, and noVNC web client,
    allowing browser-based GUI access to the sandbox.
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        config = DesktopConfig(
            resolution=request.resolution,
            display=request.display,
        )

        status = await orchestrator.start_desktop(sandbox_id, config)

        # Emit desktop_started event via event_publisher
        if event_publisher and status.running:
            try:
                await event_publisher.publish_desktop_started(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    url=status.url,
                    display=status.display,
                    resolution=status.resolution,
                    port=status.port,
                )
            except Exception as e:
                logger.warning(f"Failed to publish desktop_started event: {e}")

        return DesktopStatusResponse(
            running=status.running,
            url=status.url,
            display=status.display,
            resolution=status.resolution,
            port=status.port,
            audio_enabled=status.audio_enabled,
            dynamic_resize=status.dynamic_resize,
            encoding=status.encoding,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start desktop for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start desktop: {e!s}") from e


@router.delete("/{sandbox_id}/desktop", response_model=DesktopStopResponse)
async def stop_desktop(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> DesktopStopResponse:
    """
    Stop the remote desktop service for a sandbox.

    Stops the Xvfb, VNC, and noVNC processes.
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        success = await orchestrator.stop_desktop(sandbox_id)

        # Emit desktop_stopped event via event_publisher
        if event_publisher and success:
            try:
                await event_publisher.publish_desktop_stopped(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish desktop_stopped event: {e}")

        return DesktopStopResponse(
            success=success, message="Desktop stopped" if success else "Failed to stop desktop"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop desktop for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop desktop: {e!s}") from e


@router.get("/{sandbox_id}/desktop", response_model=DesktopStatusResponse)
async def get_desktop_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
) -> DesktopStatusResponse:
    """
    Get the current status of the remote desktop service.
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    try:
        status = await orchestrator.get_desktop_status(sandbox_id)

        return DesktopStatusResponse(
            running=status.running,
            url=status.url,
            display=status.display,
            resolution=status.resolution,
            port=status.port,
            audio_enabled=status.audio_enabled,
            dynamic_resize=status.dynamic_resize,
            encoding=status.encoding,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get desktop status for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get desktop status: {e!s}") from e


# --- Terminal Management Endpoints ---


@router.post("/{sandbox_id}/terminal", response_model=TerminalStatusResponse)
async def start_terminal(
    sandbox_id: str,
    request: TerminalStartRequest = TerminalStartRequest(),
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> TerminalStatusResponse:
    """
    Start the web terminal service (ttyd) for a sandbox.

    Starts a ttyd server that provides shell access via WebSocket.
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        config = TerminalConfig(port=request.port)

        status = await orchestrator.start_terminal(sandbox_id, config)

        # Emit terminal_started event via event_publisher
        if event_publisher and status.running:
            try:
                await event_publisher.publish_terminal_started(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    url=status.url,
                    port=status.port,
                    pid=status.pid,
                    session_id=status.session_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish terminal_started event: {e}")

        return TerminalStatusResponse(
            running=status.running,
            url=status.url,
            port=status.port,
            pid=status.pid,
            session_id=status.session_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start terminal for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start terminal: {e!s}") from e


@router.delete("/{sandbox_id}/terminal", response_model=TerminalStopResponse)
async def stop_terminal(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> TerminalStopResponse:
    """
    Stop the web terminal service for a sandbox.

    Stops the ttyd server process.
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Extract project_id from sandbox instance
    project_id = extract_project_id(instance.project_path)

    try:
        success = await orchestrator.stop_terminal(sandbox_id)

        # Emit terminal_stopped event via event_publisher
        if event_publisher and success:
            try:
                await event_publisher.publish_terminal_stopped(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish terminal_stopped event: {e}")

        return TerminalStopResponse(
            success=success, message="Terminal stopped" if success else "Failed to stop terminal"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop terminal for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop terminal: {e!s}") from e


@router.get("/{sandbox_id}/terminal", response_model=TerminalStatusResponse)
async def get_terminal_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
) -> TerminalStatusResponse:
    """
    Get the current status of the web terminal service.
    """
    # Verify sandbox exists
    instance = await adapter.get_sandbox(sandbox_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    try:
        status = await orchestrator.get_terminal_status(sandbox_id)

        return TerminalStatusResponse(
            running=status.running,
            url=status.url,
            port=status.port,
            pid=status.pid,
            session_id=status.session_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get terminal status for sandbox {sandbox_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get terminal status: {e!s}") from e
