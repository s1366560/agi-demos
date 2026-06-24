"""Desktop and Terminal service endpoints for Sandbox API.

Provides management of interactive services:
- start_desktop / stop_desktop / get_desktop_status: Desktop (noVNC)
- start_terminal / stop_terminal / get_terminal_status: Terminal (ttyd)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_orchestrator import (
    DesktopConfig,
    SandboxOrchestrator,
    TerminalConfig,
)
from src.infrastructure.adapters.primary.web.dependencies import get_current_user, get_db
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.i18n import gettext as _

from .schemas import (
    DesktopStartRequest,
    DesktopStatusResponse,
    DesktopStopResponse,
    TerminalStartRequest,
    TerminalStatusResponse,
    TerminalStopResponse,
)
from .utils import (
    assert_caller_owns_sandbox,
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
    db: AsyncSession = Depends(get_db),
) -> DesktopStatusResponse:
    """
    Start the remote desktop service (noVNC) for a sandbox.

    Starts Xvfb (virtual display), VNC server, and noVNC web client,
    allowing browser-based GUI access to the sandbox.
    """
    # Authorize and resolve project_id in a single hop.
    _instance, project_id = await assert_caller_owns_sandbox(
        sandbox_id=sandbox_id, user=current_user, db=db, adapter=adapter
    )

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
                logger.warning(
                    "Failed to publish desktop_started event: error_type=%s",
                    type(e).__name__,
                )

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
        logger.exception("Failed to start desktop for sandbox %s", sandbox_id)
        raise HTTPException(status_code=500, detail=_("Failed to start desktop")) from e


@router.delete("/{sandbox_id}/desktop", response_model=DesktopStopResponse)
async def stop_desktop(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
    db: AsyncSession = Depends(get_db),
) -> DesktopStopResponse:
    """
    Stop the remote desktop service for a sandbox.

    Stops the Xvfb, VNC, and noVNC processes.
    """
    _instance, project_id = await assert_caller_owns_sandbox(
        sandbox_id=sandbox_id, user=current_user, db=db, adapter=adapter
    )

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
                logger.warning(
                    "Failed to publish desktop_stopped event: error_type=%s",
                    type(e).__name__,
                )

        return DesktopStopResponse(
            success=success, message="Desktop stopped" if success else "Failed to stop desktop"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to stop desktop for sandbox %s", sandbox_id)
        raise HTTPException(status_code=500, detail=_("Failed to stop desktop")) from e


@router.get("/{sandbox_id}/desktop", response_model=DesktopStatusResponse)
async def get_desktop_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    db: AsyncSession = Depends(get_db),
) -> DesktopStatusResponse:
    """
    Get the current status of the remote desktop service.
    """
    await assert_caller_owns_sandbox(
        sandbox_id=sandbox_id, user=current_user, db=db, adapter=adapter
    )

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
        logger.exception("Failed to get desktop status for sandbox %s", sandbox_id)
        raise HTTPException(status_code=500, detail=_("Failed to get desktop status")) from e


# --- Terminal Management Endpoints ---


@router.post("/{sandbox_id}/terminal", response_model=TerminalStatusResponse)
async def start_terminal(
    sandbox_id: str,
    request: TerminalStartRequest = TerminalStartRequest(),
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
    db: AsyncSession = Depends(get_db),
) -> TerminalStatusResponse:
    """
    Start the web terminal service (ttyd) for a sandbox.

    Starts a ttyd server that provides shell access via WebSocket.
    """
    _instance, project_id = await assert_caller_owns_sandbox(
        sandbox_id=sandbox_id, user=current_user, db=db, adapter=adapter
    )

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
                logger.warning(
                    "Failed to publish terminal_started event: error_type=%s",
                    type(e).__name__,
                )

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
        logger.exception("Failed to start terminal for sandbox %s", sandbox_id)
        raise HTTPException(status_code=500, detail=_("Failed to start terminal")) from e


@router.delete("/{sandbox_id}/terminal", response_model=TerminalStopResponse)
async def stop_terminal(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
    db: AsyncSession = Depends(get_db),
) -> TerminalStopResponse:
    """
    Stop the web terminal service for a sandbox.

    Stops the ttyd server process.
    """
    _instance, project_id = await assert_caller_owns_sandbox(
        sandbox_id=sandbox_id, user=current_user, db=db, adapter=adapter
    )

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
                logger.warning(
                    "Failed to publish terminal_stopped event: error_type=%s",
                    type(e).__name__,
                )

        return TerminalStopResponse(
            success=success, message="Terminal stopped" if success else "Failed to stop terminal"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to stop terminal for sandbox %s", sandbox_id)
        raise HTTPException(status_code=500, detail=_("Failed to stop terminal")) from e


@router.get("/{sandbox_id}/terminal", response_model=TerminalStatusResponse)
async def get_terminal_status(
    sandbox_id: str,
    current_user: User = Depends(get_current_user),
    adapter: MCPSandboxAdapter = Depends(get_sandbox_adapter),
    orchestrator: SandboxOrchestrator = Depends(get_sandbox_orchestrator),
    db: AsyncSession = Depends(get_db),
) -> TerminalStatusResponse:
    """
    Get the current status of the web terminal service.
    """
    await assert_caller_owns_sandbox(
        sandbox_id=sandbox_id, user=current_user, db=db, adapter=adapter
    )

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
        logger.exception("Failed to get terminal status for sandbox %s", sandbox_id)
        raise HTTPException(status_code=500, detail=_("Failed to get terminal status")) from e
