"""Workspace Context handler coverage for the V2 authority transaction boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.application.schemas.workspace_context import WorkspaceContextSwitchRequest as SwitchSchema
from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSnapshot,
    WorkspaceContextSwitchOutcome,
)
from src.infrastructure.adapters.primary.web.routers import workspace_context as subject
from src.infrastructure.adapters.primary.web.workspace_context_application_authority_v2 import (
    WorkspaceContextApplicationAuthorityV2,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=UTC)


class _Service:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.get_calls: list[str] = []
        self.switch_calls: list[tuple[str, str | None]] = []

    async def get_or_initialize(
        self,
        *,
        user_id: str,
        observed_at: datetime,
    ) -> WorkspaceContextAccess:
        assert observed_at.tzinfo is not None
        self.get_calls.append(user_id)
        if self.unavailable:
            raise WorkspaceContextError(WorkspaceContextErrorCode.UNAVAILABLE)
        return WorkspaceContextAccess(
            context=WorkspaceContextSnapshot(
                tenant_id="tenant-1",
                project_id="project-1",
                revision=2,
                updated_at=_NOW,
            ),
            membership_role="admin",
        )

    async def switch(
        self,
        *,
        user_id: str,
        actor_api_key_id: str | None,
        request: object,
        observed_at: datetime,
    ) -> WorkspaceContextSwitchOutcome:
        assert observed_at.tzinfo is not None
        self.switch_calls.append((user_id, actor_api_key_id))
        return WorkspaceContextSwitchOutcome(
            context=WorkspaceContextSnapshot(
                tenant_id="tenant-2",
                project_id="project-2",
                revision=3,
                updated_at=_NOW,
            ),
            changed=True,
        )


def _authority(service: _Service, db: object) -> WorkspaceContextApplicationAuthorityV2:
    return cast(
        WorkspaceContextApplicationAuthorityV2,
        SimpleNamespace(
            operation=object(),
            db=db,
            api_key=SimpleNamespace(id="key-1", user_id="user-1"),
            services=SimpleNamespace(context=service),
        ),
    )


async def test_get_context_uses_authority_and_commits_once() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    service = _Service()

    response = await subject.get_workspace_context(_authority(service, db))

    assert response.context.project_id == "project-1"
    assert response.membership_role == "admin"
    assert service.get_calls == ["user-1"]
    db.commit.assert_awaited_once_with()


async def test_get_context_judge_failure_keeps_public_error_and_does_not_commit() -> None:
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(HTTPException) as error:
        await subject.get_workspace_context(_authority(_Service(unavailable=True), db))

    assert error.value.status_code == 404
    assert error.value.detail == {"code": "workspace_context_unavailable"}
    db.commit.assert_not_awaited()


async def test_switch_context_delegates_identity_and_commits_once() -> None:
    db = SimpleNamespace(commit=AsyncMock())
    service = _Service()
    body = SwitchSchema(
        tenant_id="tenant-2",
        project_id="project-2",
        expected_revision=2,
        idempotency_key="switch-1",
    )

    response = await subject.switch_workspace_context(body, _authority(service, db))

    assert response.context.project_id == "project-2"
    assert response.changed is True
    assert service.switch_calls == [("user-1", "key-1")]
    db.commit.assert_awaited_once_with()
