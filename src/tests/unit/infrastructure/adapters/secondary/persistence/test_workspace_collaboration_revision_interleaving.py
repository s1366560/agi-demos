"""Deterministic authority interleaving tests independent of PostgreSQL."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_collaboration_authority import (
    WorkspaceCollaborationMutationService,
    WorkspaceCollaborationRevisionConflictError,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspaceCollaborationAuthorityModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_collaboration_authority_repository import (
    SqlWorkspaceCollaborationAuthorityRepository,
)
from src.tests.unit.infrastructure.adapters.secondary.persistence.test_sql_workspace_collaboration_authority_repository import (
    _command,
    _seed_workspace,
)


@pytest.mark.unit
async def test_finalize_rejects_legacy_revision_advanced_after_reserve(
    db_session: AsyncSession,
) -> None:
    actor = await _seed_workspace(db_session)
    service = WorkspaceCollaborationMutationService(
        SqlWorkspaceCollaborationAuthorityRepository(db_session)
    )
    command = _command()
    await service.reserve(actor=actor, command=command)
    authority = await db_session.get(
        WorkspaceCollaborationAuthorityModel,
        actor.workspace_id,
    )
    assert authority is not None
    authority.revision = 3
    await db_session.flush()

    with pytest.raises(WorkspaceCollaborationRevisionConflictError) as exc_info:
        await service.finalize(actor=actor, command=command, duplicate=False)

    assert exc_info.value.expected_revision == 0
    assert exc_info.value.current_revision == 3
