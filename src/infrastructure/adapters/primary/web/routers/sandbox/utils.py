"""Shared utilities for Sandbox API.

Contains singleton management for sandbox adapter, orchestrator, and services.
"""

import asyncio
import logging
import re
import threading
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_event_service import SandboxEventPublisher
from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.application.services.sandbox_token_service import SandboxTokenService
from src.infrastructure.adapters.primary.web.dependencies import (  # noqa: F401
    get_current_user,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

# Thread-safe singleton management with lock
_singleton_lock = threading.Lock()
_sandbox_adapter: MCPSandboxAdapter | None = None
_sandbox_orchestrator: SandboxOrchestrator | None = None
_event_publisher: SandboxEventPublisher | None = None
_sandbox_token_service: SandboxTokenService | None = None
_worker_id: int | None = None  # Track worker ID for multi-worker detection
_sync_pending: bool = False  # Track if sync is pending
_sync_lock = asyncio.Lock()  # Async lock for sync operation


def _get_worker_id() -> int:
    """Get current worker/process ID for tracking."""
    import os

    return os.getpid()


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Get or create the sandbox adapter singleton with thread-safe initialization."""
    global _sandbox_adapter, _worker_id, _sync_pending

    current_worker = _get_worker_id()

    with _singleton_lock:
        # Reinitialize if worker changed (fork detection)
        if _worker_id is not None and _worker_id != current_worker:
            logger.warning(
                f"Worker ID changed from {_worker_id} to {current_worker}. "
                "Reinitializing sandbox adapter for new worker."
            )
            _sandbox_adapter = None
            _worker_id = current_worker
            _sync_pending = False  # Reset sync flag on reinit

        if _sandbox_adapter is None:
            _sandbox_adapter = MCPSandboxAdapter()
            _worker_id = current_worker
            _sync_pending = True  # Mark sync as pending
            logger.info(f"Initialized sandbox adapter for worker {current_worker}")

        return _sandbox_adapter


async def shutdown_sandbox_adapter_singleton() -> None:
    """Close the sandbox adapter singleton without terminating containers."""
    global _sandbox_adapter, _sandbox_orchestrator, _sync_pending

    with _singleton_lock:
        adapter = _sandbox_adapter
        _sandbox_adapter = None
        _sandbox_orchestrator = None
        _sync_pending = False

    if adapter is None:
        return

    await adapter.close()
    logger.info("Sandbox adapter singleton closed")


async def ensure_sandbox_sync() -> None:
    """Ensure sandbox adapter is synced with existing Docker containers.

    This should be called during application startup to discover and recover
    any existing sandbox containers that were created before the adapter was
    (re)initialized.

    This function is idempotent and will only sync once per adapter instance.
    """
    global _sync_pending

    adapter = get_sandbox_adapter()

    async with _sync_lock:
        if not _sync_pending:
            # Already synced
            return

        try:
            count = await adapter.sync_from_docker()
            if count > 0:
                logger.info(f"API Server: Synced {count} existing sandboxes from Docker")
            else:
                logger.info("API Server: No existing sandboxes found in Docker")
            _sync_pending = False
        except Exception as e:
            logger.warning(f"API Server: Failed to sync sandboxes from Docker: {e}")
            _sync_pending = False


def get_sandbox_token_service() -> SandboxTokenService:
    """Get or create the sandbox token service singleton."""
    global _sandbox_token_service

    with _singleton_lock:
        if _sandbox_token_service is None:
            from src.configuration.config import get_settings

            settings = get_settings()
            # Use the application secret as the token signing key.
            _sandbox_token_service = SandboxTokenService(
                secret_key=settings.secret_key,
                token_ttl=300,  # 5 minutes default
            )
        return _sandbox_token_service


def get_sandbox_orchestrator() -> SandboxOrchestrator:
    """Get or create the sandbox orchestrator singleton with thread-safe initialization."""
    global _sandbox_orchestrator, _event_publisher

    # Fast path: if already initialized, return immediately (no lock needed)
    if _sandbox_orchestrator is not None:
        return _sandbox_orchestrator

    # Get adapter BEFORE acquiring the lock to avoid deadlock
    # (get_sandbox_adapter also acquires _singleton_lock)
    adapter = get_sandbox_adapter()

    with _singleton_lock:
        # Double-check after acquiring lock
        if _sandbox_orchestrator is None:
            from src.configuration.config import get_settings
            from src.configuration.di_container import DIContainer

            container = DIContainer()
            settings = get_settings()

            # Initialize event publisher if not already
            if _event_publisher is None:
                _event_publisher = container.sandbox_event_publisher()

            _sandbox_orchestrator = SandboxOrchestrator(
                sandbox_adapter=adapter,
                event_publisher=_event_publisher,
                default_timeout=settings.sandbox_timeout_seconds,
            )
        return _sandbox_orchestrator


def get_event_publisher(request: Request) -> SandboxEventPublisher | None:
    """Get the sandbox event publisher from app container.

    Uses the properly initialized container from app.state which has
    redis_client configured for the event bus.
    """
    global _event_publisher

    with _singleton_lock:
        if _event_publisher is None:
            try:
                # Get container from app.state which has redis_client properly configured
                container = request.app.state.container
                _event_publisher = container.sandbox_event_publisher()
            except Exception as e:
                logger.warning("Could not create event publisher: error_type=%s", type(e).__name__)
                _event_publisher = None
        return _event_publisher


def extract_project_id(project_path: str) -> str:
    """
    Extract project_id from project_path.

    Args:
        project_path: Path in format /tmp/memstack_{project_id}

    Returns:
        Extracted project_id or "default" if not found
    """
    match = re.search(r"memstack_([a-zA-Z0-9_-]+)$", project_path)
    if match:
        return match.group(1)
    return "default"


# ---------------------------------------------------------------------------
# Authorization helpers (P1-15)
# ---------------------------------------------------------------------------


async def list_user_project_ids(*, user: User, db: AsyncSession) -> set[str]:
    """Return the set of project_ids the user is a member of.

    Superusers see all projects (caller should check is_superuser before
    using this set as a filter and skip filtering altogether for them).
    """
    result = await db.execute(
        refresh_select_statement(
            select(UserProject.project_id).where(UserProject.user_id == user.id)
        )
    )
    return {row for row in result.scalars().all() if row}


async def assert_caller_owns_project(
    *,
    project_id: str,
    user: User,
    db: AsyncSession,
) -> None:
    """Raise HTTP 403 unless the caller is a member of the project.

    Superusers bypass the membership check.
    """
    if not project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_("Missing project_id"))
    if user.is_superuser:
        return

    query = select(UserProject).where(
        and_(UserProject.user_id == user.id, UserProject.project_id == project_id)
    )
    result = await db.execute(refresh_select_statement(query))
    if result.scalar_one_or_none() is None:
        # Do not echo project_id back — that would let an attacker map ids.
        logger.warning(
            "[SandboxAuth] denied user=%s on project=%s",
            user.id,
            project_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to sandbox resource"),
        )


async def assert_caller_owns_sandbox(
    *,
    sandbox_id: str,
    user: User,
    db: AsyncSession,
    adapter: MCPSandboxAdapter,
) -> tuple[Any, str]:
    """Resolve sandbox -> project_id and assert the caller owns that project.

    Returns the sandbox instance and the resolved project_id so callers can
    avoid a second lookup.

    Raises HTTPException(404) when the sandbox does not exist (we do this
    before the ownership check so that timing differences do not leak which
    sandbox_ids belong to other tenants).
    """
    instance = await adapter.get_sandbox(sandbox_id)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Sandbox not found"),
        )

    project_id_attr = getattr(instance, "project_id", None)
    project_id = (
        project_id_attr
        if isinstance(project_id_attr, str) and project_id_attr
        else extract_project_id(getattr(instance, "project_path", "") or "")
    )
    await assert_caller_owns_project(project_id=project_id, user=user, db=db)
    return instance, project_id
