"""Tests for plan-mode route hardening."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.routers.agent.plans import (
    SwitchModeRequest,
    get_mode,
    get_tasks,
    switch_mode,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentTaskModel,
    Conversation,
    Project,
    Tenant,
    User,
    UserProject,
    UserTenant,
)


async def _add_conversation_task(
    db: AsyncSession,
    *,
    conversation_id: str,
    project_id: str,
    tenant_id: str,
    user_id: str,
) -> None:
    db.add(
        Conversation(
            id=conversation_id,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title="Scoped plan",
        )
    )
    db.add(
        AgentTaskModel(
            id=f"task-{conversation_id}",
            conversation_id=conversation_id,
            content="Authorized task",
            status="pending",
            priority="high",
            order_index=0,
        )
    )
    await db.commit()


class FailingDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("internal db secret")

    async def commit(self) -> None:
        return None


class AuthorizedDb:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(scalar_one_or_none=lambda: "conversation-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_switch_mode_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await switch_mode(
            request_body=SwitchModeRequest(conversation_id="conversation-1", mode="plan"),
            current_user=SimpleNamespace(id="user-1"),
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to switch mode"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_mode_sanitizes_internal_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_mode(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            db=FailingDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get mode"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.parametrize(
    ("operation", "revoked_membership"),
    [
        ("switch", "project"),
        ("switch", "tenant"),
        ("get", "project"),
        ("get", "tenant"),
    ],
)
async def test_plan_mode_rejects_owned_conversation_after_scope_membership_revoked(
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
    operation: str,
    revoked_membership: str,
) -> None:
    conversation_id = f"conversation-{operation}-{revoked_membership}-revoked"
    await _add_conversation_task(
        test_db,
        conversation_id=conversation_id,
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    if revoked_membership == "project":
        statement = delete(UserProject).where(
            UserProject.user_id == test_user.id,
            UserProject.project_id == test_project_db.id,
        )
    else:
        statement = delete(UserTenant).where(
            UserTenant.user_id == test_user.id,
            UserTenant.tenant_id == test_project_db.tenant_id,
        )
    await test_db.execute(statement)
    await test_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        if operation == "switch":
            await switch_mode(
                request_body=SwitchModeRequest(conversation_id=conversation_id, mode="build"),
                current_user=test_user,
                db=test_db,
            )
        else:
            await get_mode(
                conversation_id=conversation_id,
                current_user=test_user,
                db=test_db,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tasks_sanitizes_internal_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingTaskRepository:
        def __init__(self, db: Any) -> None:
            self.db = db

        find_by_conversation = AsyncMock(side_effect=RuntimeError("internal task secret"))

    import src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository as task_repo

    monkeypatch.setattr(task_repo, "SqlAgentTaskRepository", FailingTaskRepository)

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-1",
            current_user=SimpleNamespace(id="user-1"),
            db=AuthorizedDb(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to get tasks"
    assert "internal" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_tasks_returns_tasks_for_owned_tenant_project_conversation(
    test_db: AsyncSession,
    test_user: User,
    test_project_db: Project,
) -> None:
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-owned",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=test_user.id,
    )

    response = await get_tasks(
        conversation_id="conversation-owned",
        status=None,
        current_user=test_user,
        db=test_db,
    )

    assert response.conversation_id == "conversation-owned"
    assert response.total_count == 1
    assert response.tasks[0].id == "task-conversation-owned"
    payload = response.model_dump()
    assert payload["approval"] == {"kind": "legacy_mode_switch"}
    assert "plan_version" not in payload


@pytest.mark.unit
async def test_get_tasks_rejects_another_users_conversation(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
    another_user: User,
) -> None:
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-other-user",
        project_id=test_project_db.id,
        tenant_id=test_project_db.tenant_id,
        user_id=another_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-other-user",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
async def test_get_tasks_rejects_owned_conversation_without_project_membership(
    test_db: AsyncSession,
    test_tenant_db: Tenant,
    test_user: User,
    another_user: User,
) -> None:
    project = Project(
        id="project-without-membership",
        tenant_id=test_tenant_db.id,
        name="Restricted project",
        owner_id=another_user.id,
    )
    test_db.add(project)
    await test_db.commit()
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-restricted-project",
        project_id=project.id,
        tenant_id=test_tenant_db.id,
        user_id=test_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-restricted-project",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
async def test_get_tasks_rejects_owned_conversation_without_tenant_membership(
    test_db: AsyncSession,
    test_user: User,
    another_user: User,
) -> None:
    tenant = Tenant(
        id="tenant-without-membership",
        name="Restricted tenant",
        slug="restricted-tenant",
        owner_id=another_user.id,
    )
    project = Project(
        id="project-in-restricted-tenant",
        tenant_id=tenant.id,
        name="Restricted tenant project",
        owner_id=another_user.id,
    )
    test_db.add_all(
        [
            tenant,
            project,
            UserProject(
                id="stale-project-membership",
                user_id=test_user.id,
                project_id=project.id,
                role="member",
            ),
        ]
    )
    await test_db.commit()
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-restricted-tenant",
        project_id=project.id,
        tenant_id=tenant.id,
        user_id=test_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-restricted-tenant",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.unit
async def test_get_tasks_rejects_conversation_whose_project_belongs_to_another_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    tenant = Tenant(
        id="tenant-mismatched-with-project",
        name="Mismatched tenant",
        slug="mismatched-tenant",
        owner_id=test_user.id,
    )
    test_db.add_all(
        [
            tenant,
            UserTenant(
                id="mismatched-tenant-membership",
                user_id=test_user.id,
                tenant_id=tenant.id,
                role="owner",
            ),
        ]
    )
    await test_db.commit()
    await _add_conversation_task(
        test_db,
        conversation_id="conversation-cross-tenant-project",
        project_id=test_project_db.id,
        tenant_id=tenant.id,
        user_id=test_user.id,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_tasks(
            conversation_id="conversation-cross-tenant-project",
            status=None,
            current_user=test_user,
            db=test_db,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"
