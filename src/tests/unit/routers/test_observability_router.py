"""Unit tests for Avernet-backed observability workspace authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.domain.ports.services.workspace_authority_port import (
    WorkspaceAuthorityResolvedProfile,
)
from src.infrastructure.adapters.primary.web.routers.observability import (
    _require_observability_access,
)


def _request(*, tenant_id: str = "tenant-1", role: str | None = "viewer") -> SimpleNamespace:
    profile = WorkspaceAuthorityResolvedProfile(
        workspace_id="workspace-1",
        tenant_id=tenant_id,
        project_id="project-1",
        name="Observability Workspace",
        created_by="owner-1",
        is_archived=False,
        metadata={},
        member_role=role,
    )
    authority = SimpleNamespace(
        resolve_profiles=AsyncMock(
            return_value={"workspace-1": profile} if role is not None else {}
        )
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(workspace_authority=authority)))


@pytest.mark.unit
class TestObservabilityRouterAuthorization:
    async def test_non_member_cannot_read_workspace_observability(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_observability_access(
                _request(role=None),
                SimpleNamespace(id="user-1", is_superuser=False),
                "tenant-1",
                "workspace-1",
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    async def test_wrong_tenant_scope_returns_not_found(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await _require_observability_access(
                _request(tenant_id="tenant-other"),
                SimpleNamespace(id="user-1", is_superuser=False),
                "tenant-1",
                "workspace-1",
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    async def test_viewer_can_read_but_not_write_observability(self) -> None:
        request = _request(role="viewer")
        user = SimpleNamespace(id="user-1", is_superuser=False)
        await _require_observability_access(request, user, "tenant-1", "workspace-1")

        with pytest.raises(HTTPException) as exc_info:
            await _require_observability_access(
                request,
                user,
                "tenant-1",
                "workspace-1",
                require_editor=True,
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    async def test_editor_can_write_observability(self) -> None:
        await _require_observability_access(
            _request(role="editor"),
            SimpleNamespace(id="user-1", is_superuser=False),
            "tenant-1",
            "workspace-1",
            require_editor=True,
        )

    async def test_superuser_bypasses_workspace_membership(self) -> None:
        request = _request(role=None)
        profile = WorkspaceAuthorityResolvedProfile(
            workspace_id="workspace-1",
            tenant_id="tenant-1",
            project_id="project-1",
            name="Observability Workspace",
            created_by="owner-1",
            is_archived=False,
            metadata={},
            member_role=None,
        )
        request.app.state.workspace_authority.resolve_profiles.return_value = {
            "workspace-1": profile
        }

        await _require_observability_access(
            request,
            SimpleNamespace(id="admin-1", is_superuser=True),
            "tenant-1",
            "workspace-1",
            require_editor=True,
        )
