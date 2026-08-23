from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.mcp_application_authority_v2 import (
    MCPApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers.mcp.utils import (
    ensure_project_access,
    list_accessible_project_ids,
    resolve_project_tenant_id_for_access,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User, UserProject
from src.infrastructure.plugins.v2.mcp_services import (
    MCP_PROJECT_WRITE_ROLES_V2,
    SqlMCPProjectAccessV2,
)


def _authority(db: AsyncSession, tenant_id: str, user_id: str) -> MCPApplicationAuthorityV2:
    return cast(
        MCPApplicationAuthorityV2,
        SimpleNamespace(
            tenant_id=tenant_id,
            user_id=user_id,
            services=SimpleNamespace(access=SqlMCPProjectAccessV2(_session=db)),
        ),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_project_access_rejects_same_tenant_non_member(
    test_db: AsyncSession,
    test_project_db: Project,
    another_user: User,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await ensure_project_access(
            _authority(test_db, test_project_db.tenant_id, another_user.id),
            test_project_db.id,
            test_project_db.tenant_id,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_project_access_allows_viewer_reads_but_not_writes(
    test_db: AsyncSession,
    test_project_db: Project,
    another_user: User,
) -> None:
    test_db.add(
        UserProject(
            id=str(uuid4()),
            user_id=another_user.id,
            project_id=test_project_db.id,
            role="viewer",
        )
    )
    await test_db.commit()

    await ensure_project_access(
        _authority(test_db, test_project_db.tenant_id, another_user.id),
        test_project_db.id,
        test_project_db.tenant_id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await ensure_project_access(
            _authority(test_db, test_project_db.tenant_id, another_user.id),
            test_project_db.id,
            test_project_db.tenant_id,
            MCP_PROJECT_WRITE_ROLES_V2,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_accessible_project_ids_returns_user_memberships_only(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    another_user: User,
) -> None:
    assert await list_accessible_project_ids(
        _authority(test_db, test_project_db.tenant_id, test_user.id),
    ) == {test_project_db.id}
    assert (
        await list_accessible_project_ids(
            _authority(test_db, test_project_db.tenant_id, another_user.id),
        )
        == set()
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_project_tenant_id_for_access_returns_authorized_project_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    assert (
        await resolve_project_tenant_id_for_access(
            _authority(test_db, test_project_db.tenant_id, test_user.id),
            test_project_db.id,
        )
        == test_project_db.tenant_id
    )
