"""Sandbox API helpers and pinned-generation service projections."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.sandbox_runtime import SandboxToolRegistryProtocolV2

logger = logging.getLogger(__name__)


def get_sandbox_adapter() -> MCPSandboxAdapter:
    """Project the adapter from the generation pinned to this ASGI boundary."""
    from src.infrastructure.plugins.v2.sandbox_projection import (
        current_sandbox_application_services_v2,
    )

    return current_sandbox_application_services_v2().adapter


def get_sandbox_token_service() -> SandboxTokenService:
    """Project the token service from the pinned sandbox generation."""
    from src.infrastructure.plugins.v2.sandbox_projection import (
        current_sandbox_application_services_v2,
    )

    return current_sandbox_application_services_v2().token_service


def get_sandbox_orchestrator() -> SandboxOrchestrator:
    """Project the orchestrator from the pinned sandbox generation."""
    from src.infrastructure.plugins.v2.sandbox_projection import (
        current_sandbox_application_services_v2,
    )

    return current_sandbox_application_services_v2().orchestrator


def get_event_publisher(request: Request) -> SandboxEventPublisher | None:
    """Project the event publisher from the pinned sandbox generation."""
    _ = request
    from src.infrastructure.plugins.v2.sandbox_projection import (
        current_sandbox_application_services_v2,
    )

    return current_sandbox_application_services_v2().event_publisher


def get_sandbox_tool_registry() -> SandboxToolRegistryProtocolV2:
    """Project the tool registry from the generation pinned to this ASGI boundary."""
    from src.infrastructure.plugins.v2.sandbox_projection import (
        current_sandbox_application_services_v2,
    )

    return current_sandbox_application_services_v2().tool_registry


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
