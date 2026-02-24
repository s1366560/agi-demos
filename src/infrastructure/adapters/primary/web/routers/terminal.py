"""Terminal WebSocket API routes for interactive shell sessions.

Provides WebSocket endpoints for connecting to Docker container
interactive shells via terminal proxy.
"""

import asyncio
import contextlib
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)
from src.infrastructure.adapters.secondary.sandbox.terminal_proxy import (
    TerminalSession,
    get_terminal_proxy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/terminal", tags=["terminal"])

# Global adapter instance (reuse from sandbox module)
_sandbox_adapter: MCPSandboxAdapter | None = None
_event_publisher: SandboxEventPublisher | None = None


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton."""
    global _sandbox_adapter
    if _sandbox_adapter is None:
        _sandbox_adapter = MCPSandboxAdapter()
    return _sandbox_adapter


def get_event_publisher(request: Request) -> SandboxEventPublisher | None:
    """Get the sandbox event publisher from app container.

    Uses the properly initialized container from app.state which has
    redis_client configured for the event bus.
    """
    global _event_publisher
    if _event_publisher is None:
        try:
            # Get container from app.state which has redis_client properly configured
            container = request.app.state.container
            _event_publisher = container.sandbox_event_publisher()
        except Exception as e:
            logger.warning(f"Could not create event publisher: {e}")
            _event_publisher = None
    return _event_publisher


async def get_project_id_from_sandbox(sandbox_id: str) -> str | None:
    """
    Extract project_id from sandbox by inspecting its project_path.

    Args:
        sandbox_id: Sandbox/container identifier

    Returns:
        Extracted project_id or None
    """
    adapter = get_sandbox_adapter()
    try:
        # Note: get_sandbox returns a coroutine, need to await
        sandbox = await adapter.get_sandbox(sandbox_id)
        if sandbox and sandbox.project_path:
            match = re.search(r"memstack_([a-zA-Z0-9_-]+)$", sandbox.project_path)
            if match:
                return match.group(1)
    except Exception as e:
        logger.warning(f"Could not get project_id from sandbox {sandbox_id}: {e}")
    return None


# --- Request/Response Schemas ---


class TerminalSessionResponse(BaseModel):
    """Terminal session info response."""

    session_id: str
    container_id: str
    cols: int
    rows: int
    is_active: bool


class CreateTerminalRequest(BaseModel):
    """Request to create terminal session."""

    shell: str = Field(default="/bin/bash", description="Shell to execute")
    cols: int = Field(default=80, description="Terminal columns")
    rows: int = Field(default=24, description="Terminal rows")


# --- REST Endpoints ---


@router.post("/{sandbox_id}/create", response_model=TerminalSessionResponse)
async def create_terminal_session(
    sandbox_id: str,
    request: CreateTerminalRequest,
    _user: User = Depends(get_current_user),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> TerminalSessionResponse:
    """
    Create a new terminal session for a sandbox.

    This creates an interactive shell inside the sandbox container.
    Use the WebSocket endpoint to interact with the terminal.
    """
    adapter = get_sandbox_adapter()

    # Verify sandbox exists
    sandbox = await adapter.get_sandbox(sandbox_id)
    if not sandbox:
        raise HTTPException(status_code=404, detail=f"Sandbox not found: {sandbox_id}")

    # Get container ID (sandbox_id is the container name)
    container_id = sandbox_id

    # Create terminal session
    proxy = get_terminal_proxy()
    try:
        session = await proxy.create_session(
            container_id=container_id,
            shell=request.shell,
            cols=request.cols,
            rows=request.rows,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create terminal session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create terminal session")

    # Emit terminal_started event
    if event_publisher:
        project_id = await get_project_id_from_sandbox(sandbox_id)
        if project_id:
            try:
                # Determine port from terminal proxy (default 7681)
                port = 7681
                # WebSocket URL format: ws://host:port/{session_id}
                ws_url = f"ws://localhost:{port}/{session.session_id}"

                await event_publisher.publish_terminal_started(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    url=ws_url,
                    port=port,
                    session_id=session.session_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish terminal_started event: {e}")

    return TerminalSessionResponse(
        session_id=session.session_id,
        container_id=session.container_id,
        cols=session.cols,
        rows=session.rows,
        is_active=session.is_active,
    )


@router.get("/{sandbox_id}/sessions", response_model=list[TerminalSessionResponse])
async def list_terminal_sessions(
    sandbox_id: str,
    _user: User = Depends(get_current_user),
) -> list[TerminalSessionResponse]:
    """List all terminal sessions for a sandbox."""
    proxy = get_terminal_proxy()

    sessions = []
    for session in proxy._sessions.values():
        if session.container_id == sandbox_id:
            sessions.append(
                TerminalSessionResponse(
                    session_id=session.session_id,
                    container_id=session.container_id,
                    cols=session.cols,
                    rows=session.rows,
                    is_active=session.is_active,
                )
            )

    return sessions


@router.delete("/{sandbox_id}/sessions/{session_id}")
async def close_terminal_session(
    sandbox_id: str,
    session_id: str,
    _user: User = Depends(get_current_user),
    event_publisher: SandboxEventPublisher | None = Depends(get_event_publisher),
) -> dict:
    """Close a terminal session."""
    proxy = get_terminal_proxy()

    session = proxy.get_session(session_id)
    if not session or session.container_id != sandbox_id:
        raise HTTPException(status_code=404, detail="Session not found")

    success = await proxy.close_session(session_id)

    # Emit terminal_stopped event
    if event_publisher and success:
        project_id = await get_project_id_from_sandbox(sandbox_id)
        if project_id:
            try:
                await event_publisher.publish_terminal_stopped(
                    project_id=project_id,
                    sandbox_id=sandbox_id,
                    session_id=session_id,
                )
            except Exception as e:
                logger.warning(f"Failed to publish terminal_stopped event: {e}")

    return {"success": success, "session_id": session_id}


# --- WebSocket Endpoint ---


@router.websocket("/{sandbox_id}/ws")
async def terminal_websocket(
    websocket: WebSocket,
    sandbox_id: str,
    session_id: str | None = None,
) -> None:
    """
    WebSocket endpoint for terminal interaction.

    Message Protocol (JSON):
    - Client -> Server:
        {"type": "input", "data": "ls -la\\n"}
        {"type": "resize", "cols": 120, "rows": 40}
        {"type": "ping"}

    - Server -> Client:
        {"type": "output", "data": "file1.txt\\nfile2.txt"}
        {"type": "error", "message": "Session closed"}
        {"type": "connected", "session_id": "abc123"}
        {"type": "pong"}
    """
    await websocket.accept()

    proxy = get_terminal_proxy()
    session: TerminalSession | None = None

    try:
        # Create or get session
        if session_id:
            session = proxy.get_session(session_id)
            if not session or session.container_id != sandbox_id:
                await websocket.send_json({"type": "error", "message": "Session not found"})
                await websocket.close()
                return
        else:
            # Create new session
            try:
                session = await proxy.create_session(container_id=sandbox_id)
            except ValueError as e:
                await websocket.send_json({"type": "error", "message": str(e)})
                await websocket.close()
                return

        # Send connected message
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session.session_id,
                "cols": session.cols,
                "rows": session.rows,
            }
        )

        # Start output reader task
        async def read_output() -> None:
            """Background task to read and forward output."""
            while session and session.is_active:
                try:
                    output = await proxy.read_output(session.session_id)
                    if output is None:
                        break
                    if output:
                        await websocket.send_json({"type": "output", "data": output})
                except Exception as e:
                    logger.error(f"Output reader error: {e}")
                    break
                await asyncio.sleep(0.01)  # Small delay to prevent CPU spin

        output_task = asyncio.create_task(read_output())

        # Process incoming messages
        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "input":
                    data = msg.get("data", "")
                    await proxy.send_input(session.session_id, data)

                elif msg_type == "resize":
                    cols = msg.get("cols", 80)
                    rows = msg.get("rows", 24)
                    await proxy.resize(session.session_id, cols, rows)

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for session {session.session_id}")

    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}")
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})

    finally:
        # Cleanup
        if "output_task" in locals():
            output_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await output_task

        # Don't close session on disconnect - allow reconnection
        # Session will be cleaned up by cleanup task or explicit close
        with contextlib.suppress(Exception):
            await websocket.close()
